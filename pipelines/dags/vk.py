"""A VK ("ВКонтакте") data archive, into the warehouse.

The account was deleted in 2020; its archive - the HTML pages VK's "request
your data" page gave - is all there is, so this loads it once: one file,
made from the zip by pipelines/tools/vk_pack.py on the machine that holds
it and copied into the scheduler pod with `kubectl cp`. Each line is one
message, conversation, track or other entry, and goes to Kafka topic raw.vk
in the usual envelope (pipelines/dags/ingest.py), masked first like every
other source.

Triggered by hand, never on a schedule. The file is deleted once every
record is delivered, so the unmasked copy does not outlive the load; a
failed run leaves it for the retry. Loading it again adds nothing: the ods
models keep each record once. pipelines/vk.md has the procedure.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone

import pendulum
from airflow.sdk import dag, task

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sensitive import mask_record  # noqa: E402

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.vk"


@dag(
    dag_id="ingest_vk",
    schedule=None,
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "vk"],
    # Where `kubectl cp` put the file; another path can be given when
    # triggering.
    params={"path": "/tmp/vk.jsonl.gz"},
    # A retry sends every record again; the ods models keep each once.
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=5)},
)
def ingest_vk():
    @task(execution_timeout=timedelta(hours=1))
    def load() -> None:
        from airflow.sdk import get_current_context
        from confluent_kafka import Producer

        context = get_current_context()
        path = context["params"]["path"]
        extracted_at = datetime.now(timezone.utc).isoformat()
        producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
            # A long message or page stays well under this.
            "message.max.bytes": 8_000_000,
        })
        errors: list[str] = []
        counts: dict[str, int] = {}

        def delivered(err, _msg):
            if err is not None:
                errors.append(str(err))

        # One line at a time: the scheduler's memory is the tasks' memory.
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                record, flags = mask_record(item["record"])
                endpoint, rid = item["endpoint"], item["id"]
                value = json.dumps({
                    "source": "vk",
                    "endpoint": endpoint,
                    "extracted_at": extracted_at,
                    "run_id": context["run_id"],
                    "id": rid,
                    "record": record,
                    **flags,
                }, ensure_ascii=False).encode()
                while True:
                    try:
                        producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                         on_delivery=delivered)
                        break
                    except BufferError:
                        producer.poll(1)
                producer.poll(0)
                counts[endpoint] = counts.get(endpoint, 0) + 1

        left = producer.flush(120)
        if left or errors:
            raise RuntimeError(f"{left} undelivered, errors: {errors[:3]}")
        os.remove(path)
        print(f"to {TOPIC}: {counts}; {path} deleted")

    load()


ingest_vk()
