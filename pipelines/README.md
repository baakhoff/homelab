# pipelines

The data warehouse's code: Airflow DAGs and the dbt project they run.
Airflow (`clusters/lab/airflow/`) pulls this directory from `main` once a
minute, so a merged change is live a minute later.

    dags/
      ingest.py      one DAG per service: snapshot its API into Kafka
      warehouse.py   the dbt project as one DAG, a task per model (Cosmos)
    dbt/
      models/ods/    raw parsed into typed tables, one system at a time
      models/ads/    joins and aggregates across systems
      models/dm/     the tables questions and dashboards read
      macros/        the snapshot, timestamp and OTLP helpers the models share

## The flow

    service API --ingest_<source>--> Kafka raw.<source> --> ClickHouse raw.<source>
    Home Assistant, Alloy ---------> Kafka raw.<source> --> ClickHouse raw.<source>
                                                                  |
                                                     warehouse:  ods -> ads -> dm

`raw` is the record of what arrived: the payload exactly as produced, never
edited. Every table above it is rebuilt from it by dbt, so a model can be
fixed and re-run at any time and the history comes out right.

## The models

| Layer | Models |
|---|---|
| `ods` | `firefly_accounts`, `firefly_transactions` (one row per split), `firefly_budgets`, `firefly_categories`, `vikunja_tasks`, `vikunja_projects`, `mealie_recipes`, `mealie_mealplans`, `mealie_shopping_items`, `paperless_documents`, `paperless_tags`, `paperless_correspondents`, `paperless_document_types`, `ha_states`, `logs`, `k8s_events` |
| `ads` | `finance_daily`, `ha_numeric_hourly`, `ha_activity_daily`, `logs_hourly`, `k8s_events_daily`, `tasks_daily`, `documents_daily`, `meals_daily` |
| `dm` | `finance_monthly`, `home_sensors_daily`, `cluster_daily`, `household_daily` |

Two patterns cover the sources:

- **API snapshots** (Firefly, Vikunja, Mealie, Paperless) -
  `snapshot_records()` returns the newest run's records, so a record
  deleted at the source disappears from `ods` too. These models are tables,
  rebuilt every run.
- **Streams** (Home Assistant, logs, Kubernetes events) - incremental: each
  run appends what arrived since the last.

Money stays in its own currency everywhere: nothing sums dinars and euros
into one number (`dm.household_daily` carries a currency -> amount map).

## Working on it locally

dbt runs against any ClickHouse; the profile takes everything from the
environment:

```bash
cd pipelines/dbt
python -m venv .venv && .venv/bin/pip install dbt-core==1.12.5 dbt-clickhouse==1.10.3
CLICKHOUSE_HOST=localhost CLICKHOUSE_USER=default CLICKHOUSE_PASSWORD= \
  DBT_PROFILES_DIR=. .venv/bin/dbt build
```

Against the lab's ClickHouse, port-forward it first
(`kubectl -n data port-forward svc/clickhouse 8123`) and use the `dbt`
user's password.

## Adding things

- **A model**: a `.sql` file in the right layer. It is a task in the
  `warehouse` DAG on the next parse.
- **An API endpoint**: one entry in its source's `endpoints` in
  `dags/ingest.py`, and an `ods` model reading it with
  `snapshot_records('<source>', '<endpoint>')`.
- **A source**: a block in `SOURCES` in `dags/ingest.py`, its word in
  `SOURCES` in `clusters/lab/data/clickhouse-schema.yaml`, a table in
  `dbt/models/sources.yml`, and NetworkPolicy doors on both sides
  (`clusters/lab/airflow/README.md`).
