# pipelines

The data warehouse's code: Airflow DAGs and the dbt project they run.
Airflow (`clusters/lab/airflow/`) pulls this directory from `main` once a
minute, so a merged change is live a minute later.

    dags/
      ingest.py      one DAG per service: snapshot its API into Kafka
      telegram.py    Telegram accounts' private chats, logged in as each
      proton.py      a Proton Mail export, loaded by hand from a packed file
      vk.py          the VK data archive, loaded by hand from a packed file
      google.py      the Google account, four DAGs (google.md)
      files.py       the NAS archive's inbox, into the archive and the warehouse (files.md)
      archive.py     files onto the NAS under their hash, a row for each: the helpers
      sensitive.py   masks secrets and identity numbers in every record first
      warehouse.py   the dbt project as one DAG, a task per model (Cosmos)
    tools/
      telegram_login.py  the one-time Telegram login, into the Secret
      proton_pack.py     a Proton Mail export packed into one file for the DAG, its attachments for the archive
      vk_pack.py         the VK data archive packed into one file for the DAG
      google_auth.py     the Google consent, run once on the workstation
      google_takeout_pack.py  a Google Takeout export packed into one file for the DAG
      google_takeout_load.sh  the newest Takeout export packed, loaded and cleaned up, in one go
    telegram.md      what Telegram sends, its setup and renewal
    proton.md        loading a Proton Mail export, and cleaning up after
    vk.md            loading the VK data archive
    google.md        what Google sends, its consent and renewal
    files.md         the NAS archive: where files go, the inbox, finding a file from a row
    sensitive.md     what is masked before data reaches the warehouse, and how
    tests/           tests for sensitive.py, the pack tools, archive.py and telegram.py's choice of files: `uv run --with pytest pytest pipelines/tests`
    dbt/
      models/ods/    raw parsed into typed tables, one system at a time
      models/ads/    joins and aggregates across systems
      models/dm/     the tables questions and dashboards read
      macros/        the snapshot, timestamp and OTLP helpers the models share
    google.md        Google: what is copied, setup, renewing

## The flow

    service API --ingest_<source>--> Kafka raw.<source> --> ClickHouse raw.<source>
    Home Assistant, Alloy ---------> Kafka raw.<source> --> ClickHouse raw.<source>
    NAS inbox ------ingest_files---> Kafka raw.files ----> ClickHouse raw.files
       \--> the file, on the NAS under its hash                   |
                                                     warehouse:  ods -> ads -> dm

`raw` is the record of what arrived: the payload exactly as produced, never
edited. Every table above it is rebuilt from it by dbt, so a model can be
fixed and re-run at any time and the history comes out right.

## The models

| Layer | Models |
|---|---|
| `ads` | `finance_daily`, `ha_numeric_hourly`, `ha_activity_daily`, `logs_hourly`, `k8s_events_daily`, `tasks_daily`, `documents_daily`, `meals_daily`, `nutrition_daily`, `location_daily`, `telegram_daily`, `google_daily`, `people` |
| `dm` | `finance_monthly`, `home_sensors_daily`, `cluster_daily`, `household_daily` |

Five patterns cover the sources:

- **API snapshots** (Firefly, Vikunja, Mealie, Paperless, SparkyFitness,
  Dawarich's visits and places, Outline's documents, Immich's counts per
  with their history, Google's Calendar,
  Contacts, Tasks and Drive) - `snapshot_records()` returns the newest
  run's records, so a record deleted at the source disappears from `ods`
  too. These models are tables, rebuilt every run.
- **API windows** (Dawarich's points) - each run sends only the last week,
  because the whole history is millions of points. `ods.dawarich_points` is
  incremental and keeps each point as first seen, so a point deleted at
  the source stays.
- **Messages sent once** (Telegram, Proton Mail, the NAS archive's files) -
  each message is sent when it is new and again when edited (Telegram) or
  exported again (Proton Mail), and `ods.telegram_messages`,
  `ods.proton_messages` and `ods.files` keep every message's newest copy
  across all runs. Rebuilt every run; a message deleted at the source stays.
- **Changes** (Gmail, Google's activity exports) - the DAG sends only what
  is new or changed, and a tombstone for what was deleted, because a full
  snapshot would be far too large. `accumulated_records()` returns the newest
  version of every record ever sent, minus the deleted ones. Tables, rebuilt
  every run.
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

The rendered documentation - lineage, SQL, columns - is at
<https://dbt.lab.baakhoff.com>, regenerated from `main` hourly
(`clusters/lab/airflow/dbt-docs.yaml`). A model's `description` and its
columns' descriptions in a `schema.yml` are what fill it in.

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
