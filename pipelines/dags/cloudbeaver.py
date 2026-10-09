"""How CloudBeaver is used, into the warehouse: who signed in, when, and what
they ran against which database. Never a query's results, and never a
credential.

CloudBeaver Community keeps no query history of its own - that is its paid
editions - so the record of what it ran comes from the databases it ran it
on. Each is read as it is kept:

  ClickHouse  system.query_log, the server's own record of every query: the
              text, the databases and tables it touched, how long it took,
              rows and bytes read and returned, the error if it failed. The
              `cloudbeaver` user's rows only (a row policy shows dbt nothing
              else - clusters/lab/data/clickhouse-schema.yaml). Read from
              where the last run left off, in Variable cloudbeaver_sync.
  Postgres    nothing here: each server logs the `cloudbeaver` role's
              statements and errors, the log collectors already
              carry every log line to raw.logs, and dbt picks them out
              (ods.cloudbeaver_postgres_log).
  CloudBeaver its own database: the sessions (who, from where, with which
              browser, from when to when), the users, and the sign-in
              attempts. A full snapshot each run, like the other sources -
              not the tables holding saved credentials, tokens or session
              state, which the `ingest` role cannot read
              (clusters/lab/cloudbeaver/postgres.yaml).

Everything goes to Kafka topic raw.cloudbeaver in the usual envelope
(pipelines/dags/ingest.py). CLICKHOUSE_PASSWORD (dbt's) and
CLOUDBEAVER_INGEST_PASSWORD come from the airflow-sources Secret.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pendulum
import requests
from airflow.sdk import Variable, dag, task

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
CLICKHOUSE = "http://clickhouse.data.svc.cluster.local:8123/"
CLOUDBEAVER_DB = {
    "host": "cloudbeaver-postgres.cloudbeaver.svc.cluster.local",
    "port": 5432,
    "dbname": "cloudbeaver",
    "user": "ingest",
}
TOPIC = "raw.cloudbeaver"
STATE = "cloudbeaver_sync"
# ClickHouse writes query_log in batches every few seconds, so a row can
# land with a time just before the last one read. Each run reads this far
# back again; the ods model keeps each query once.
OVERLAP = timedelta(minutes=10)
# Queries per run at most. The first run reads the whole log; a backlog
# larger than this takes more than one run.
CLICKHOUSE_BATCH = 50_000

# Finished queries only: a query that ran is logged twice, at its start and
# its end, and the end has everything the start has. Results are not in
# query_log at all, only their size.
QUERY_LOG_SQL = """
SELECT
  toString(event_time_microseconds) AS event_time,
  type,
  query_id,
  initial_query_id,
  query_kind,
  current_database,
  databases,
  tables,
  query,
  toString(normalized_query_hash) AS normalized_query_hash,
  query_duration_ms,
  read_rows,
  read_bytes,
  written_rows,
  result_rows,
  result_bytes,
  memory_usage,
  exception_code,
  exception,
  http_user_agent,
  client_name,
  toString(address) AS address
FROM system.query_log
WHERE user = 'cloudbeaver'
  AND type != 'QueryStart'
  AND event_date >= toDate(parseDateTime64BestEffort({since:String}, 6))
  AND event_time_microseconds > parseDateTime64BestEffort({since:String}, 6)
ORDER BY event_time_microseconds
LIMIT {batch:UInt32}
FORMAT JSONEachRow
"""

# Named columns, not *: a CloudBeaver upgrade that adds a column with
# something sensitive in it does not reach the warehouse unseen.
CLOUDBEAVER_TABLES = {
    "sessions": ("session_id", """
        SELECT session_id, app_session_id, user_id, session_type,
               create_time, last_access_time,
               last_access_remote_address, last_access_user_agent
        FROM cb.cb_session"""),
    "users": ("user_id", """
        SELECT user_id, is_active, create_time, last_login_time,
               default_auth_role, change_date, disabled_by, disable_reason
        FROM cb.cb_user"""),
    "auth-attempts": ("auth_id", """
        SELECT auth_id, auth_status, auth_error, error_code, auth_username,
               session_id, app_session_id, session_type,
               is_main_auth, is_service_auth, create_time
        FROM cb.cb_auth_attempt"""),
}


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set - see clusters/lab/cloudbeaver/README.md")
    return value


class _Raw:
    """The Kafka producer, in the envelope every source uses."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self.run_id = run_id
        self.extracted_at = datetime.now(timezone.utc).isoformat()
        self.errors: list[str] = []
        self.counts: dict[str, int] = {}
        self.producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
            # A query's text can be long.
            "message.max.bytes": 8_000_000,
        })

    def send(self, endpoint: str, rid: str, record: dict) -> None:
        envelope = {
            "source": "cloudbeaver",
            "endpoint": endpoint,
            "extracted_at": self.extracted_at,
            "run_id": self.run_id,
            "id": rid,
            "record": record,
        }
        value = json.dumps(envelope, ensure_ascii=False, default=str).encode()
        while True:
            try:
                self.producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                      on_delivery=self._delivered)
                break
            except BufferError:
                self.producer.poll(1)
        self.producer.poll(0)
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def _delivered(self, err, _msg):
        if err is not None:
            self.errors.append(str(err))

    def flush(self) -> None:
        left = self.producer.flush(60)
        if left or self.errors:
            raise RuntimeError(f"{left} undelivered, errors: {self.errors[:3]}")
        print(f"to {TOPIC}: {self.counts or 'nothing new'}")


@dag(
    dag_id="ingest_cloudbeaver",
    description="CloudBeaver's sessions, and its ClickHouse queries, into Kafka topic raw.cloudbeaver",
    schedule="45 * * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "cloudbeaver"],
    default_args={"retries": 2, "retry_delay": pendulum.duration(minutes=2)},
)
def ingest_cloudbeaver():
    @task
    def clickhouse_queries() -> int:
        """query_log since the last run, oldest first."""
        from airflow.sdk import get_current_context

        state = json.loads(Variable.get(STATE, default="{}"))
        since = state.get("clickhouse_queries")
        if since:
            since = (datetime.fromisoformat(since) - OVERLAP).isoformat()
        else:
            since = "1970-01-01 00:00:00"

        r = requests.post(
            CLICKHOUSE,
            params={"param_since": since, "param_batch": CLICKHOUSE_BATCH},
            data=QUERY_LOG_SQL,
            auth=("dbt", _env("CLICKHOUSE_PASSWORD")),
            timeout=300,
            stream=True,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ClickHouse answered {r.status_code}: {r.text[:500]}")

        raw = _Raw(get_current_context()["run_id"])
        newest = None
        for line in r.iter_lines():
            if not line:
                continue
            row = json.loads(line)
            raw.send("clickhouse-queries", f"{row['query_id']}:{row['type']}", row)
            newest = row["event_time"]
        raw.flush()

        if newest:
            # ClickHouse's "2026-10-08 12:00:00.123456", as ISO for fromisoformat.
            state["clickhouse_queries"] = newest.replace(" ", "T")
            Variable.set(STATE, json.dumps(state, sort_keys=True))
        return raw.counts.get("clickhouse-queries", 0)

    @task
    def cloudbeaver_tables() -> int:
        """CloudBeaver's sessions, users and sign-in attempts, whole."""
        import psycopg2
        import psycopg2.extras
        from airflow.sdk import get_current_context

        raw = _Raw(get_current_context()["run_id"])
        conn = psycopg2.connect(**CLOUDBEAVER_DB, password=_env("CLOUDBEAVER_INGEST_PASSWORD"),
                                connect_timeout=30)
        try:
            conn.set_session(readonly=True)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for endpoint, (key, sql) in CLOUDBEAVER_TABLES.items():
                    cur.execute(sql)
                    for row in cur:
                        raw.send(endpoint, str(row[key]), dict(row))
        finally:
            conn.close()
        raw.flush()
        return sum(raw.counts.values())

    clickhouse_queries()
    cloudbeaver_tables()


ingest_cloudbeaver()
