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

from pathlib import Path

import pendulum
from cosmos import DbtDag, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import InvocationMode, LoadMode

DBT_PROJECT = Path(__file__).resolve().parent.parent / "dbt"
DBT_EXECUTABLE = "/opt/dbt/bin/dbt"

warehouse = DbtDag(
    dag_id="warehouse",
    description="raw -> ods -> ads -> dm, every model in pipelines/dbt/",
    # No packages to install: the project uses none.
    project_config=ProjectConfig(dbt_project_path=DBT_PROJECT, install_dbt_deps=False),
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
