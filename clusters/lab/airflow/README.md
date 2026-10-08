# airflow

[Apache Airflow](https://airflow.apache.org) runs the data warehouse's
pipelines (`clusters/lab/data/`). The DAGs and the
[dbt](https://www.getdbt.com) project are in [`pipelines/`](../../../pipelines/README.md),
pulled from `main` by git-sync once a minute - a merged change to a DAG or a
model is live a minute later, with no restart.

| DAG | What it does | When |
|---|---|---|
| `ingest_firefly`, `ingest_vikunja`, `ingest_mealie`, `ingest_paperless`, `ingest_sparkyfitness`, `ingest_dawarich` | Snapshot the service's API into Kafka topic `raw.<source>` - one task per endpoint. Dawarich's points are the last week's, not all of them | Vikunja hourly, Dawarich daily at 03:40, the rest every 6 hours |
| `warehouse` | The dbt project: `raw` -> `ods` -> `ads` -> `dm`, one task per model and per model's tests, rendered by [Cosmos](https://github.com/astronomer/astronomer-cosmos) | hourly, at :45 |

UI: <https://airflow.lab.baakhoff.com>, behind the admin gate. That gate is
the only login - Airflow treats everyone who reaches it as an admin.

dbt's own documentation site is at <https://dbt.lab.baakhoff.com>, behind the
same gate: the lineage graph from `raw` to `dm`, each model's SQL, and every
column with its description and ClickHouse type. `dbt-docs.yaml` runs it as a
pod of its own that regenerates the site from `main` every hour, so the page
trails a merge by up to an hour. Deleting the pod regenerates it at once. A
failed run leaves the previous page up and says why in the `generate`
container's log.

## How it runs

- **LocalExecutor**: tasks are processes inside the scheduler pod. No
  Redis, no Celery workers, no pod per task. The scheduler's 2560Mi limit
  is the tasks' limit, which is why at most three tasks run at once
  (`parallelism`). The warehouse DAG's models queue behind each other; a
  full run takes a few minutes longer and never takes the scheduler down.
- **Its own image** (`images/airflow/`): the official one plus Cosmos, the
  Kafka client, and dbt in a separate virtualenv at `/opt/dbt` so that
  dbt's and Airflow's dependencies never meet.
- **Its own Postgres** (`postgres.yaml`) for run history. Losing it loses
  history, not data.
- **dbt connects as the `dbt` ClickHouse user**: it reads `raw` and owns
  `ods`, `ads` and `dm`, nothing else. The data namespace's schema job
  creates it.

## What it can reach

`networkpolicy.yaml` lets Airflow out to GitHub (git-sync) and to exactly
the services its DAGs read - Kafka and ClickHouse, the Firefly broker,
Vikunja, Mealie, Paperless, SparkyFitness, Dawarich. Each of those admits
the scheduler pod by name in its own policy. A new source needs a door on both
sides. The dbt docs pod uses the same rules for ClickHouse and GitHub, and
ClickHouse admits it by name as well.

## Setup, in this order

Three Secrets, all on the workstation from the repo root. Commit and push
them together; until they land, the pods wait in
`CreateContainerConfigError`.

**1. Airflow's own keys and its database password.** Generated, never
typed, never shown:

```bash
PGPW=$(openssl rand -hex 24)
kubectl create secret generic airflow-core \
  --namespace airflow \
  --from-literal=postgres-password="$PGPW" \
  --from-literal=connection="postgresql+psycopg2://airflow:$PGPW@airflow-postgres.airflow.svc.cluster.local:5432/airflow" \
  --from-literal=fernet-key="$(openssl rand -base64 32 | tr '+/' '-_')" \
  --from-literal=api-secret-key="$(openssl rand -hex 32)" \
  --from-literal=jwt-secret="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml > clusters/lab/airflow/core.sops.yaml
unset PGPW
sops --encrypt --in-place clusters/lab/airflow/core.sops.yaml
```

**2. dbt's ClickHouse password**, generated once and written to both
namespaces - the data namespace creates the user with it, Airflow logs in
with it:

```bash
DBTPW=$(openssl rand -hex 24)
kubectl create secret generic clickhouse-dbt \
  --namespace data \
  --from-literal=DBT_PASSWORD="$DBTPW" \
  --dry-run=client -o yaml > clusters/lab/data/clickhouse-dbt.sops.yaml
sops --encrypt --in-place clusters/lab/data/clickhouse-dbt.sops.yaml
```

Keep `DBTPW` set for step 3.

**3. The sources' API tokens.** Create each in its app first:

| App | Where | Token |
|---|---|---|
| Vikunja | Settings -> API Tokens, as the account the data should be read as | read access to projects, tasks and labels |
| Mealie | Profile -> Manage Your API Tokens | any name |
| Paperless | Profile (top right) -> API Auth Token | the account's token |

Then, one `read` at a time:

```bash
read -rsp 'vikunja token: ' VT; echo
read -rsp 'mealie token: ' MT; echo
read -rsp 'paperless token: ' PT; echo

kubectl create secret generic airflow-sources \
  --namespace airflow \
  --from-literal=CLICKHOUSE_PASSWORD="$DBTPW" \
  --from-literal=VIKUNJA_TOKEN="$VT" \
  --from-literal=MEALIE_TOKEN="$MT" \
  --from-literal=PAPERLESS_TOKEN="$PT" \
  --dry-run=client -o yaml > clusters/lab/airflow/sources.sops.yaml
unset DBTPW VT MT PT
sops --encrypt --in-place clusters/lab/airflow/sources.sops.yaml
```

Firefly needs no token here: the broker holds it. SparkyFitness's and
Dawarich's keys are added later, into the same Secret - step 5 of
`clusters/lab/sparkyfitness/README.md` and of `clusters/lab/dawarich/README.md`.
So is CloudBeaver's `CLOUDBEAVER_INGEST_PASSWORD`, for the usage DAG -
`clusters/lab/cloudbeaver/README.md`.

**4. Create the dbt user** once the Secrets have reconciled, rather than
waiting for the hourly schema job:

```bash
kubectl -n data create job --from=cronjob/clickhouse-schema schema-dbt
kubectl -n data logs -f job/schema-dbt --all-containers
```

**5. Check.** In the UI, all five DAGs are listed with no import errors.
Trigger `ingest_vikunja` by hand; when it is green,
`SELECT count() FROM raw.vikunja` in ClickHouse is above zero. Then trigger
`warehouse` and look at `ods.vikunja_tasks`.

## Things to know

- **A failing ods test means a source changed shape.** The models read
  fields by name out of raw JSON; a renamed field reads as empty, and the
  key tests in `pipelines/dbt/models/ods/schema.yml` are what notice.
- **Rotating dbt's password** is steps 2 and 3 again (both copies), then
  the schema job.
- **Task logs are not kept** past the scheduler pod's life; its output is in
  Loki like any pod's.
- **Not backed up**, and nothing here needs to be: the DAGs are in git and
  the data is in ClickHouse.
