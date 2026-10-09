# CloudBeaver

[CloudBeaver](https://github.com/dbeaver/cloudbeaver) Community, the web
version of [DBeaver](https://dbeaver.io): a tree of every database, schema
and table, an SQL editor with completion, result grids, ER diagrams and
exports, in the browser.

At <https://db.lab.baakhoff.com>, and on Homepage under Data.

## What it reaches

Every database server in the lab, as a shared connection in the tree
(`config.yaml`):

| Connection | Server | What is in it |
|---|---|---|
| ClickHouse - warehouse | `clickhouse.data` | `raw`, `ods`, `ads`, `dm`, and `system` |
| Postgres - Airflow | `airflow-postgres.airflow` | DAG runs, task states, Variables |
| Postgres - SparkyFitness | `sparkyfitness-postgres.sparkyfitness` | the food diary, workouts, measurements |
| Postgres - Dawarich | `dawarich-postgres.dawarich` | the location history (PostGIS) |
| Postgres - Epicurus | `postgres.epicurus` | Epicurus's platform data |

Each Postgres connection shows every database on its server, not only the
app's.

**Read everything, change nothing.** On every server it signs in as a role
named `cloudbeaver` that can read every table and cannot write. That limit
is on the database side, so it holds whatever CloudBeaver does:

- **Postgres:** `pg_read_all_data` and `pg_monitor`, with row-level
  security bypassed, so SparkyFitness's per-user rows are all visible. The
  role is kept by an hourly job in each namespace (`cloudbeaver-reader.yaml`
  there).
- **ClickHouse:** `SELECT` on `*.*` and `readonly = 2`, with a profile that
  caps memory and threads (`clusters/lab/data/README.md`).

Each connection is also marked read-only in CloudBeaver.

**Not here: the SQLite databases.** Vaultwarden, Pocket ID, Firefly,
Paperless, Mealie, Vikunja, n8n and Home Assistant each keep a SQLite file
on a volume that only their own pod can mount, so no network client can
reach them. What the warehouse ingests from them is in ClickHouse under
`ods`.

Your own connections are possible as well: *New connection* in the tree.
They are kept in your project on the volume and survive restarts. Inside
the lab the NetworkPolicy lets CloudBeaver reach only the five servers
above, so another lab server needs a rule in `networkpolicy.yaml` and one
on its own side.

**A database outside the lab** goes through an SSH tunnel: the
connection's SSH tab, *Public key*, and the private key pasted into it.
CloudBeaver keeps the key encrypted in its own database; nothing goes on
the volume by hand. From the Mac, `pbcopy < ~/.ssh/<key>` to copy it and
`pbcopy < /dev/null` after. A database with a public address of its own
needs no tunnel: the NetworkPolicy lets CloudBeaver reach the whole public
internet, on any port, and nothing private - no LAN, no tailnet, no node.
Which hosts is not written down here. Queries over such a tunnel do not reach the warehouse: the
usage feed reads the lab servers' own logs, and only CloudBeaver's
sessions show the visit.

## The AI chat

CloudBeaver's AI chat writes and explains SQL against the open connection.
It runs on [OpenRouter](https://openrouter.ai), through CloudBeaver's
OpenAI engine pointed at OpenRouter's OpenAI-compatible API, set in the
AI section of CloudBeaver's administration settings:

| Field | Value |
|---|---|
| Engine | OpenAI |
| Base URL | `https://openrouter.ai/api/v1/` |
| API token | an OpenRouter key, made at openrouter.ai -> Keys, with a credit limit |
| Model | picked from the list, which CloudBeaver reads from OpenRouter |

The settings are in the workspace (`ai-configuration.json`), the key in
CloudBeaver's encrypted store, and neither is reset by a restart - unlike
the rest of the settings, they live only there, not in git.

**What leaves the lab:** each question goes to OpenRouter and on to the
model's provider, with the schema of the database in scope - table and
column names, and, if you allow it when the chat asks, the results of
queries it runs to answer. For SparkyFitness, Dawarich or anything else
personal, that is the household's data at a third party. OpenRouter's
privacy settings can refuse providers that train on or keep prompts.
None of it reaches the usage feed.

CloudBeaver speaks OpenAI's Responses API, which OpenRouter offers as a
beta. A model that fails there with an error about the request is usually
fine on another.

## How login works

Through the admin gate: oauth2-proxy, `lab-admins` only. ingress-nginx
passes the signed-in Pocket ID address to CloudBeaver in
`X-Auth-Request-Email`, overwriting anything the browser sent, and
CloudBeaver signs that address in. The account is created at the first
visit and is a CloudBeaver admin, because only admins get through the gate.
No second login.

There is also one local account, `cbadmin`, made at the first start with
the password from the Secret. It is the way in if the header ever stops
arriving: *Sign in* -> *Local*. The password is in the Secret:
`sops -d clusters/lab/cloudbeaver/secret.sops.yaml`, key
`CB_ADMIN_PASSWORD`, base64.

## What goes to the warehouse

CloudBeaver Community keeps no query history of its own; that is a feature
of the paid editions. The record comes from the databases it queries, and
from its own database. None of it includes a query's results or a
password.

| Table | One row per | From |
|---|---|---|
| `ods.cloudbeaver_clickhouse_queries` | query on ClickHouse: text, databases and tables, duration, rows and bytes read and returned, error | `system.query_log`, by the `ingest_cloudbeaver` DAG |
| `ods.cloudbeaver_postgres_log` | logged statement or error on a Postgres server: the database, the duration, the text | the servers' own logs, through the log collectors |
| `ods.cloudbeaver_sessions` | CloudBeaver session: who, from which address and browser, from when until the last request | CloudBeaver's database, by the DAG |
| `ods.cloudbeaver_auth_attempts` | sign-in, successful or not | the same |
| `ods.cloudbeaver_users` | account | the same |
| `ads.cloudbeaver_daily` | day and database: statements, errors, time taken, and rows read on ClickHouse | the two query tables |

CloudBeaver's own reads count too. Opening a table in the tree is queries
against `system.*` or `pg_catalog`, so a browse shows up as activity.

**The DAG,** `pipelines/dags/cloudbeaver.py`, runs hourly at :45. It reads
`system.query_log` as dbt, which a row policy limits to `cloudbeaver`'s
rows. It reads three of CloudBeaver's tables as the `ingest` role
(`postgres.yaml`), and cannot read the tables holding saved credentials,
tokens or session state.

**Postgres logs every statement the role runs,** because the reader job
sets `log_min_duration_statement = 0` on the role. It also sets the server's `log_line_prefix` so that each line names the
role and the database. The collectors join a multi-line statement back into
one entry (`clusters/lab/logging/alloy.yaml`). It then reaches `raw.logs`
like every other log line.

**Who can read it:** anyone who can read `ods`, which includes the brand
agent's `brand` user. The query texts are in there.

## Setup, in this order

The pods wait in `CreateContainerConfigError` until the Secrets exist, and
so do the reader jobs.

**1. The passwords, on the workstation,** from the repo root, on this
branch. Nine values, generated and never shown. Each database's reader
password goes into two Secrets: CloudBeaver's, and the one beside that
database.

```bash
CBDB=$(openssl rand -hex 24)
CBADM=$(openssl rand -hex 24)
CBING=$(openssl rand -hex 24)
RCH=$(openssl rand -hex 24)
RAF=$(openssl rand -hex 24)
RSF=$(openssl rand -hex 24)
RDW=$(openssl rand -hex 24)
REP=$(openssl rand -hex 24)

kubectl create secret generic cloudbeaver \
  --namespace cloudbeaver \
  --from-literal=CLOUDBEAVER_DB_PASSWORD="$CBDB" \
  --from-literal=CB_ADMIN_PASSWORD="$CBADM" \
  --from-literal=INGEST_DB_PASSWORD="$CBING" \
  --from-literal=READER_CLICKHOUSE="$RCH" \
  --from-literal=READER_AIRFLOW="$RAF" \
  --from-literal=READER_SPARKYFITNESS="$RSF" \
  --from-literal=READER_DAWARICH="$RDW" \
  --from-literal=READER_EPICURUS="$REP" \
  --dry-run=client -o yaml > clusters/lab/cloudbeaver/secret.sops.yaml

kubectl create secret generic clickhouse-cloudbeaver \
  --namespace data \
  --from-literal=CLOUDBEAVER_PASSWORD="$RCH" \
  --dry-run=client -o yaml > clusters/lab/data/clickhouse-cloudbeaver.sops.yaml

kubectl create secret generic cloudbeaver-reader --namespace airflow \
  --from-literal=PASSWORD="$RAF" \
  --dry-run=client -o yaml > clusters/lab/airflow/cloudbeaver-reader.sops.yaml
kubectl create secret generic cloudbeaver-reader --namespace sparkyfitness \
  --from-literal=PASSWORD="$RSF" \
  --dry-run=client -o yaml > clusters/lab/sparkyfitness/cloudbeaver-reader.sops.yaml
kubectl create secret generic cloudbeaver-reader --namespace dawarich \
  --from-literal=PASSWORD="$RDW" \
  --dry-run=client -o yaml > clusters/lab/dawarich/cloudbeaver-reader.sops.yaml
kubectl create secret generic cloudbeaver-reader --namespace epicurus \
  --from-literal=PASSWORD="$REP" \
  --dry-run=client -o yaml > clusters/lab/epicurus/cloudbeaver-reader.sops.yaml

for f in clusters/lab/cloudbeaver/secret.sops.yaml \
         clusters/lab/data/clickhouse-cloudbeaver.sops.yaml \
         clusters/lab/airflow/cloudbeaver-reader.sops.yaml \
         clusters/lab/sparkyfitness/cloudbeaver-reader.sops.yaml \
         clusters/lab/dawarich/cloudbeaver-reader.sops.yaml \
         clusters/lab/epicurus/cloudbeaver-reader.sops.yaml; do
  sops --encrypt --in-place "$f"
done

sops set clusters/lab/airflow/sources.sops.yaml \
  '["data"]["CLOUDBEAVER_INGEST_PASSWORD"]' "\"$(printf '%s' "$CBING" | base64)\""

unset CBDB CBADM CBING RCH RAF RSF RDW REP
```

**2. The backup's Secret** in this namespace, copied from an existing
one without the values touching the screen (`clusters/lab/backup/README.md`):

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: cloudbeaver/' \
  > clusters/lab/backup/restic-repo-cloudbeaver.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-cloudbeaver.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-cloudbeaver.sops.yaml
```

The `grep` must print `namespace: cloudbeaver` before you encrypt.

**3. Commit and push** the eight files. The pre-commit hook checks that
they are encrypted.

**4. After the merge,** once Flux has applied it (a minute or two), run the
jobs now rather than waiting for the hour. On the workstation:

```bash
kubectl -n data create job --from=cronjob/clickhouse-schema schema-cloudbeaver
for ns in airflow sparkyfitness dawarich epicurus; do
  kubectl -n "$ns" create job --from=cronjob/cloudbeaver-reader cloudbeaver-reader-now
done
kubectl -n airflow rollout restart deployment/airflow-scheduler
kubectl -n cloudbeaver rollout status deployment/cloudbeaver --timeout=10m
kubectl -n cloudbeaver create job --from=cronjob/cloudbeaver-postgres-roles roles-now
```

The schema job makes the ClickHouse user and `raw.cloudbeaver`. The reader
jobs make the Postgres roles. The scheduler restart picks up
`CLOUDBEAVER_INGEST_PASSWORD`. The last job grants the `ingest` role its
three tables; it waits for CloudBeaver's first start because the tables do
not exist before it.

**5. Check.** Open <https://db.lab.baakhoff.com>. You should be signed in
as your Pocket ID address, with five connections in the tree. Open each
one. Then trigger `ingest_cloudbeaver` and `warehouse` in Airflow, and run
`SELECT * FROM ods.cloudbeaver_clickhouse_queries ORDER BY event_time DESC
LIMIT 20` in CloudBeaver itself.

## Things to know

- **Settings live in git.** At every start the init container deletes the
  runtime settings CloudBeaver writes when its Administration pages are
  saved, and puts the shared connections back as `config.yaml` has them. A
  change in the UI lasts until the next restart. To keep a change, edit
  `config.yaml` and bump `cloudbeaver.lab/config-revision` in
  `deployment.yaml`.
- **A connection that will not open:** the reader job in that namespace
  says why (`kubectl -n <ns> logs job/...`). The usual causes are a missing
  Secret, or a password that differs between the two copies.
- **Rotating a reader password:** change it in both Secrets, then rerun
  that namespace's reader job and restart CloudBeaver. For ClickHouse, the
  job to rerun is the schema job.
- **HTTP 431 (Request Header Fields Too Large):** CloudBeaver's web server
  accepts 8 KB of request headers, and the gate's session cookie is
  counted. Signing out of the gate at
  `https://auth.lab.baakhoff.com/oauth2/sign_out` and back in starts a
  fresh, smaller cookie.
- **A first start that fails part-way leaves a half-made schema** that
  every later start trips over (`relation "cb_schema_info" already
  exists`): CloudBeaver does not create its schema in one transaction. With
  nothing in it yet, the way out is a clean start - scale the Deployment to
  0, `DROP SCHEMA cb CASCADE` in `cloudbeaver-postgres-0`, scale back to 1.
  A schema with real users in it wants a restore instead.
- **The upgrade path:** CloudBeaver migrates its own schema on start. Its
  automatic backup before a migration is off (`cloudbeaver.conf`), because
  the image has no `pg_dump`. The nightly backup is the undo.
- **Memory:** about 1 GB in use, with a 1.5 GB limit. Large grids and
  exports are what the headroom is for.
