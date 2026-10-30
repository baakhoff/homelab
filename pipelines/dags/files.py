"""The NAS archive's inbox, into the archive and the warehouse.

Every hour, each batch dropped into /archive/inbox that has gone quiet is
stored under its hashes and gets its rows in raw.files - archive.py beside
this file does the work, and pipelines/files.md says how to use it.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

# archive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archive  # noqa: E402


@dag(
    dag_id="ingest_files",
    schedule="30 * * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "files"],
    # A retry sends the last group's records again; ods.files keeps each once.
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=5)},
)
def ingest_files():
    @task(execution_timeout=timedelta(minutes=55))
    def sweep() -> None:
        from airflow.sdk import get_current_context

        archive.sweep(archive.Files(get_current_context()["run_id"]))

    sweep()


ingest_files()
