"""Pull every record from the lab's services and send it, raw, to Kafka.

One DAG per source system, one task per API endpoint. Each run takes a full
snapshot: every record the endpoint lists, each as its own Kafka message on
the source's topic (raw.<source>), and ClickHouse stores them in
raw.<source>. The record is sent exactly as the API returned it, inside a
small envelope that says where and when it came from:

    {"source": "firefly", "endpoint": "accounts", "extracted_at": "...",
     "run_id": "...", "id": "12", "record": {...the API's JSON...}}

Full snapshots rather than "what changed since": the household's data is
small, every API here can list everything, and a snapshot also records
deletions - a record that stops appearing was deleted. The ods layer keeps
the latest version of each record (pipelines/dbt/).

Credentials come from the airflow-sources Secret as environment variables;
nothing here holds one. Firefly needs none: the broker adds its token
(clusters/lab/firefly-broker/).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pendulum
import requests
from airflow.sdk import dag, task

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
PAGE_SIZE = 100
TIMEOUT = 60


def _firefly_pages(session: requests.Session, url: str):
    """JSON:API, page numbers, meta.pagination.total_pages."""
    page = 1
    while True:
        r = session.get(url, params={"page": page, "limit": PAGE_SIZE}, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        yield from body.get("data", [])
        total = body.get("meta", {}).get("pagination", {}).get("total_pages", 1)
        if page >= total:
            return
        page += 1


def _vikunja_pages(session: requests.Session, url: str):
    """A bare JSON list per page; the page count is in a response header."""
    page = 1
    while True:
        r = session.get(url, params={"page": page, "per_page": PAGE_SIZE}, timeout=TIMEOUT)
        r.raise_for_status()
        yield from r.json() or []
        total = int(r.headers.get("x-pagination-total-pages", "1") or 1)
        if page >= total:
            return
        page += 1


def _mealie_pages(session: requests.Session, url: str):
    """{"items": [...], "total_pages": n}."""
    page = 1
    while True:
        r = session.get(url, params={"page": page, "perPage": PAGE_SIZE}, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        yield from body.get("items", [])
        if page >= body.get("total_pages", 1):
            return
        page += 1


def _paperless_pages(session: requests.Session, url: str):
    """Django REST framework: {"results": [...], "next": url-or-null}."""
    next_url, params = url, {"page_size": PAGE_SIZE}
    while next_url:
        r = session.get(next_url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        yield from body.get("results", [])
        next_url, params = body.get("next"), None


# Per source: where its API is, how it authenticates, how it pages, and the
# endpoints to snapshot. A new endpoint is one entry; a new source is one
# block here plus its word in SOURCES (clusters/lab/data/clickhouse-schema.yaml)
# and its NetworkPolicy doors (clusters/lab/airflow/README.md).
SOURCES = {
    "firefly": {
        "base": "http://firefly-broker.firefly-broker.svc.cluster.local/v1",
        "auth": None,
        "pages": _firefly_pages,
        "endpoints": [
            "accounts", "transactions", "budgets", "categories", "bills",
            "tags", "piggy-banks", "currencies", "recurrences", "rules",
        ],
        "schedule": "15 */6 * * *",
    },
    "vikunja": {
        "base": "http://vikunja.vikunja.svc.cluster.local/api/v1",
        "auth": ("Bearer", "VIKUNJA_TOKEN"),
        "pages": _vikunja_pages,
        "endpoints": ["projects", "tasks", "labels"],
        "schedule": "20 * * * *",
    },
    "mealie": {
        "base": "http://mealie.mealie.svc.cluster.local/api",
        "auth": ("Bearer", "MEALIE_TOKEN"),
        "pages": _mealie_pages,
        "endpoints": [
            "recipes", "households/mealplans", "households/shopping/lists",
            "households/shopping/items", "organizers/categories", "organizers/tags",
        ],
        "schedule": "25 */6 * * *",
    },
    "paperless": {
        "base": "http://paperless.paperless.svc.cluster.local/api",
        "auth": ("Token", "PAPERLESS_TOKEN"),
        "pages": _paperless_pages,
        "endpoints": [
            "documents", "tags", "correspondents", "document_types",
            "storage_paths", "custom_fields",
        ],
        "schedule": "30 */6 * * *",
    },
}


def _session(auth) -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/json"
    if auth:
        scheme, env = auth
        token = os.environ.get(env)
        if not token:
            raise RuntimeError(f"{env} is not set - see clusters/lab/airflow/README.md")
        s.headers["Authorization"] = f"{scheme} {token}"
    return s


def _make_dag(source: str, cfg: dict):
    @dag(
        dag_id=f"ingest_{source}",
        description=f"Snapshot {source}'s API into Kafka topic raw.{source}",
        schedule=cfg["schedule"],
        start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
        catchup=False,
        max_active_runs=1,
        tags=["ingest", source],
        default_args={"retries": 2, "retry_delay": pendulum.duration(minutes=2)},
    )
    def ingest():
        # Each mapped task is labelled with its endpoint in the UI.
        @task(map_index_template="{{ endpoint_label }}")
        def snapshot(endpoint: str, **context) -> int:
            from confluent_kafka import Producer

            context["endpoint_label"] = endpoint

            topic = f"raw.{source}"
            producer = Producer({
                "bootstrap.servers": KAFKA_BOOTSTRAP,
                "compression.type": "zstd",
                "linger.ms": 50,
                # Paperless documents carry their full OCR text.
                "message.max.bytes": 8_000_000,
            })
            errors: list[str] = []

            def delivered(err, _msg):
                if err is not None:
                    errors.append(str(err))

            extracted_at = datetime.now(timezone.utc).isoformat()
            run_id = context["run_id"]
            session = _session(cfg["auth"])
            count = 0
            for record in cfg["pages"](session, f"{cfg['base']}/{endpoint}"):
                rid = str(record.get("id", "")) if isinstance(record, dict) else ""
                envelope = {
                    "source": source,
                    "endpoint": endpoint,
                    "extracted_at": extracted_at,
                    "run_id": run_id,
                    "id": rid,
                    "record": record,
                }
                producer.produce(
                    topic,
                    key=f"{endpoint}:{rid}".encode(),
                    value=json.dumps(envelope, ensure_ascii=False).encode(),
                    on_delivery=delivered,
                )
                producer.poll(0)
                count += 1
            left = producer.flush(60)
            if left or errors:
                raise RuntimeError(f"{left} undelivered, errors: {errors[:3]}")
            print(f"{source}/{endpoint}: {count} records to {topic}")
            return count

        snapshot.expand(endpoint=cfg["endpoints"])

    return ingest()


for _source, _cfg in SOURCES.items():
    globals()[f"ingest_{_source}"] = _make_dag(_source, _cfg)
