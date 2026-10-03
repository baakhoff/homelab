# Airflow for the lab's data pipelines (clusters/lab/airflow/,
# pipelines/). The official image plus two things it lacks: what the DAGs
# import (Cosmos, the Kafka client), and dbt in a virtualenv of its own.
# Built and published by .github/workflows/airflow-image.yml.

# Renovate's dockerfile manager watches this line, and the workflow reads
# the Airflow version out of it for the tag - keep its shape.
FROM apache/airflow:3.2.2-python3.12

# Into Airflow's own environment, under the official constraints for this
# Airflow and Python, so nothing here can move a package Airflow pins.
# Repeating apache-airflow==<version> is the upstream advice: it stops pip
# from "upgrading" Airflow to satisfy something else.
#   astronomer-cosmos - renders the dbt project as the warehouse DAG
#   confluent-kafka   - the ingest DAGs' producer; the constraints pin it
ARG COSMOS_VERSION=1.15.1
RUN AIRFLOW_VERSION=$(python -c 'import airflow; print(airflow.__version__)') \
 && pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      "astronomer-cosmos==${COSMOS_VERSION}" \
      confluent-kafka \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"

# dbt in its own virtualenv at /opt/dbt. dbt and Airflow pin overlapping
# libraries to different versions, and the documented answer is to keep
# them apart: Cosmos calls /opt/dbt/bin/dbt as a subprocess
# (pipelines/dags/warehouse.py). Root-owned and read-only to the airflow
# user, which only needs to run it.
ARG DBT_CORE_VERSION=1.12.5
ARG DBT_CLICKHOUSE_VERSION=1.10.3
USER root
RUN python -m venv /opt/dbt \
 && /opt/dbt/bin/pip install --no-cache-dir \
      "dbt-core==${DBT_CORE_VERSION}" \
      "dbt-clickhouse==${DBT_CLICKHOUSE_VERSION}" \
 && /opt/dbt/bin/dbt --version
USER airflow
