"""The warehouse DAG: the dbt project in pipelines/dbt/, run by Airflow.

Cosmos turns the dbt project into an Airflow DAG with one task per model
(and per model's tests), wired in dbt's own dependency order - raw -> ods ->
ads -> dm. A model added to the project is a task in this DAG on the next
parse; nothing here names a model.

dbt runs from its own virtualenv in the image (/opt/dbt, images/airflow/),
so its dependencies never fight Airflow's. Cosmos copies the project to a
temporary directory for every run, which is why a read-only git checkout
is fine as its source.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pendulum
from cosmos import DbtDag, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import InvocationMode, LoadMode

DBT_PROJECT = Path(__file__).resolve().parent.parent / "dbt"
DBT_EXECUTABLE = "/opt/dbt/bin/dbt"
# The models another Flux source mounts (dbt/extra links here).
EXTRA = Path("/opt/airflow/extra")


def _extra_version() -> str:
    """A fingerprint of the mounted models. Cosmos keys its cache of `dbt ls`
    on this project's files, and the mount is outside them: without this, a
    model arriving there would stay out of the DAG until something here
    changed."""
    h = hashlib.sha256()
    if EXTRA.is_dir():
        for p in sorted(EXTRA.iterdir()):
            if p.suffix in (".sql", ".yml", ".yaml") and not p.name.startswith(".") and p.is_file():
                h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:16]


warehouse = DbtDag(
    dag_id="warehouse",
    description="raw -> ods -> ads -> dm, every model in pipelines/dbt/",
    # No packages to install: the project uses none.
    # The fingerprint goes in as an environment variable, which is part of
    # Cosmos's cache key; dbt itself ignores it.
    project_config=ProjectConfig(dbt_project_path=DBT_PROJECT, install_dbt_deps=False,
                                 env_vars={"WAREHOUSE_EXTRA_VERSION": _extra_version()}),
    profile_config=ProfileConfig(
        profile_name="warehouse",
        target_name="lab",
        profiles_yml_filepath=DBT_PROJECT / "profiles.yml",
    ),
    # A subprocess of dbt's own executable: dbt is not importable from
    # Airflow's environment, by design.
    execution_config=ExecutionConfig(
        dbt_executable_path=DBT_EXECUTABLE,
        invocation_mode=InvocationMode.SUBPROCESS,
    ),
    # `dbt ls` reads the project exactly as dbt does - macros, configs,
    # refs - and Cosmos caches the result between parses.
    render_config=RenderConfig(
        load_method=LoadMode.DBT_LS,
        dbt_executable_path=DBT_EXECUTABLE,
        invocation_mode=InvocationMode.SUBPROCESS,
    ),
    # Hourly, after the ingest DAGs' minutes (pipelines/dags/ingest.py).
    # The streaming sources arrive continuously; each run picks up what is
    # new since the last.
    schedule="45 * * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dbt", "warehouse"],
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=5)},
)
