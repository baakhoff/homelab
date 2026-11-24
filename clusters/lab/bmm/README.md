# BMM

[BMM](https://github.com/baakhoff/bmm), Better Marketing Management: a
social media manager that is hosted here, with an API for everything its web
app does. Version 0.1 is the foundation: sign-in, API tokens with scopes,
and an audit log. Connecting accounts and scheduling posts come with later
releases.

At <https://bmm.lab.baakhoff.com>, and on Homepage under Tools.

## How it is put together

BMM's own Helm chart, pinned to one version (`helmrelease.yaml`): the server
and a Postgres of its own, on a 5 GiB Ceph volume. The chart also makes the
NetworkPolicies: the database talks to BMM only, and BMM's web port takes
connections from the ingress controller, Airflow and lab-mcp only. BMM
itself may call out, to Pocket ID now and to the social networks later.

Renovate proposes each new chart version as a pull request. BMM migrates its
own database when the new version starts, and release notes say when a
version needs a step by hand.

## How login works

Pocket ID, through BMM's own OpenID Connect support, behind the oauth2-proxy
gate as well (`ingress.yaml` says why). In practice it is one passkey. There
is no password form.

BMM has one admin. **The first person to sign in becomes that admin**, and
from then on only that Pocket ID identity gets in. So sign in right after
the install (step 4).

## The API

Everything is under `/api/v1`, with an API token made in the web app under
API tokens. A token carries scopes, and can never make a token stronger than
itself.

The gate covers the API as well, so a token does not work through
`bmm.lab.baakhoff.com` from outside the cluster. Inside the cluster the
address is `http://bmm.bmm.svc.cluster.local/api/v1`, for the two callers
the NetworkPolicy admits:

- **lab-mcp**, as the service `social` (`clusters/lab/lab-mcp/`), so the
  local agent reaches BMM through its tools.
- **Airflow**, for the warehouse, below.

The reference, for a signed-in person, is at
<https://bmm.lab.baakhoff.com/api/docs>.

## What goes to the warehouse

Airflow's `ingest_bmm` DAG copies the audit log and the list of API tokens
into ClickHouse's `raw.bmm` every six hours (`pipelines/dags/ingest.py`).

| Table | One row per |
|---|---|
| `ods.bmm_audit` | sign-in or change: when, what, whether a person or a token did it, to what, and from which address |
| `ods.bmm_tokens` | API token: its name, scopes, first characters, and when it was made, last used and expires |

A token's secret is never in BMM's answers, so it never reaches the
warehouse. Profiles, posts and analytics get tables when BMM has them.
BMM's own log lines are in `ods.logs`, like every pod's.

**Who can read it:** anyone who can read `ods`, which includes the brand
agent's `brand` user.

## Setup, in this order

The release waits, with "values reference not found", until step 2's Secret
exists, and installs by itself once it does.

**1. The Pocket ID client.** In Pocket ID at <https://id.lab.baakhoff.com>,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | BMM |
| Callback URLs | `https://bmm.lab.baakhoff.com/api/v1/auth/oidc/callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | a group with only yourself in it |

**2. The Secret, before this merges.** On the workstation from the repo
root, on this branch, in bash. Run the `read` lines one at a time: pasted
together, the rest of the paste becomes the input. The database password is
generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic bmm-lab \
  --namespace bmm \
  --from-literal=client-id="$CID" \
  --from-literal=client-secret="$CSEC" \
  --from-literal=password="$(openssl rand -hex 24)" \
  --dry-run=client -o yaml > clusters/lab/bmm/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/bmm/secret.sops.yaml
```

On the Mac's zsh, the `read` lines are `read -rs 'CID?client id: '; echo`
and `read -rs 'CSEC?client secret: '; echo`.

Create it once. Postgres takes `password` when its volume is first made and
keeps it: a new value later locks BMM out of its own database. To change
only the client, edit in place with `sops clusters/lab/bmm/secret.sops.yaml`.

**3. The backup's Secret,** copied from an existing one without the values
touching the screen (`clusters/lab/backup/README.md`):

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: bmm/' \
  > clusters/lab/backup/restic-repo-bmm.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-bmm.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-bmm.sops.yaml
```

The `grep` must print `namespace: bmm` before you encrypt. Commit and push
both files; the pre-commit hook checks that they are encrypted. Without this
one on `main`, the nightly backup reports the `bmm` target as failed.

**4. Right after the merge: sign in first**, so the admin is you. Run the
schema job now rather than at the hour, so `raw.bmm` exists before the first
ingest, and wait for the release:

```bash
kubectl -n data create job --from=cronjob/clickhouse-schema schema-bmm
kubectl -n bmm wait helmrelease/bmm --for=condition=Ready --timeout=10m
```

Then open <https://bmm.lab.baakhoff.com> and sign in with Pocket ID.

**5. Feed the data warehouse.** In BMM, API tokens → New, named
`warehouse`, with the scopes `audit:read` and `tokens:read` and no others.
On the workstation from the repo root, one line at a time:

```bash
read -rsp 'bmm token: ' BT; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["BMM_API_TOKEN"]' "\"$(printf %s "$BT" | base64 | tr -d '\n')\""
unset BT
```

Commit and push. Once Flux has applied it, restart the scheduler, because a
pod reads its environment only when it starts. Delete the pod rather than
`rollout restart`, which Flux undoes:

```bash
kubectl -n airflow delete pod -l component=scheduler
```

Then, in the Airflow UI, switch `ingest_bmm` on - Airflow pauses every new
DAG until someone does - and trigger it, and after it the `warehouse` DAG.
Until the token exists, that DAG's runs fail and nothing else is affected.

**6. The agent's token.** In BMM, API tokens → New, named `lab-mcp`, with
the scopes the local agent should have. `audit:read` and `tokens:read` let
it look; the `:write` scopes let it act, which matters once BMM can post.
One line at a time:

```bash
read -rsp 'bmm token: ' BT; echo
sops set clusters/lab/lab-mcp/secret.sops.yaml '["data"]["BMM_API_TOKEN"]' "\"$(printf %s "$BT" | base64 | tr -d '\n')\""
unset BT
```

Bump `lab-mcp/secret` in `clusters/lab/lab-mcp/deployment.yaml` in the same
commit, so the pod restarts and reads it. Until then lab-mcp lists `social`
as "not set up yet". Revoking the token in BMM takes the access back.

## Things to know

- **One admin, no other users yet.** BMM 0.1 has a single account. Anyone
  else Pocket ID lets through is refused by BMM.
- **It asks GitHub for new releases** a few times a day, to show a notice in
  the web app. Nothing about the instance is sent. `config.updateCheck:
  false` in `helmrelease.yaml` turns it off.
- **Locked out?** If the admin's Pocket ID identity is lost, set
  `oidc.allowedEmail` in `helmrelease.yaml` to an email Pocket ID reports as
  verified: the first sign-in by that identity links itself to the admin.
- **The pods:** `kubectl -n bmm get pods`. `bmm-…` is the server and
  `bmm-postgres-0` the database. Restart the server with
  `kubectl -n bmm delete pod -l app.kubernetes.io/component=server`.

## Backup

`bmm/data-bmm-postgres-0` is in the nightly backup (`clusters/lab/backup/`):
everything BMM knows, from a crash-consistent snapshot of its Postgres
volume. A dump by hand, before an upgrade for instance:

```bash
kubectl -n bmm exec bmm-postgres-0 -- pg_dump -U bmm bmm > bmm.sql
```
