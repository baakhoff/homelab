# BMM

[BMM](https://github.com/baakhoff/bmm), Better Marketing Management: a
social media manager that is hosted here, with an API for everything its web
app does. A profile is a persona with its own X and Instagram accounts,
images and calendar; a post is drafted, scheduled or published to any of a
profile's accounts, by a person or through the API.

At <https://bmm.lab.baakhoff.com>, and on Homepage under Tools.

## How it is put together

BMM's own Helm chart, pinned to one version (`helmrelease.yaml`): the server
and a Postgres of its own, each on a 5 GiB Ceph volume: `bmm-data` for
uploaded images, `data-bmm-postgres-0` for everything else. The chart also
makes the NetworkPolicies: the database talks to BMM only, and BMM's web
port takes connections from the ingress controller, Airflow and lab-mcp
only. BMM itself may call out, to Pocket ID and to the social networks.

The accounts' access tokens and the networks' app secrets are encrypted in
the database with `secret-key` from the Secret `bmm-lab`. A restore needs
the database and that key together.

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

BMM also has an MCP server of its own, at `/mcp`, with tools made for
posting. It is behind the gate like the rest, so nothing outside the
cluster uses it today; the local agent goes through lab-mcp.

**Publishing is real.** BMM puts no confirmation between a token with
`posts:write` and a published post. What an agent may do is decided by the
scopes of its token (step 6).

The reference, for a signed-in person, is at
<https://bmm.lab.baakhoff.com/api/docs>.

## What goes to the warehouse

Airflow's `ingest_bmm` DAG copies the profiles, accounts, posts, audit log
and list of API tokens into ClickHouse's `raw.bmm` every six hours
(`pipelines/dags/ingest.py`).

| Table | One row per |
|---|---|
| `ods.bmm_profiles` | profile: its name, time zone and notes |
| `ods.bmm_accounts` | connected account: the network, the username, and whether it needs connecting again |
| `ods.bmm_posts` | post: its text, status, when it is due, and how many images and accounts |
| `ods.bmm_post_targets` | account a post goes to: published or not, the link the network gave, or its error |
| `ods.bmm_audit` | sign-in or change: when, what, whether a person or a token did it, to what, and from which address |
| `ods.bmm_tokens` | API token: its name, scopes, first characters, and when it was made, last used and expires |

A token's secret and an account's access tokens are never in BMM's
answers, so they never reach the warehouse. The images stay in BMM.
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
together, the rest of the paste becomes the input. The database password
and the encryption key are generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic bmm-lab \
  --namespace bmm \
  --from-literal=client-id="$CID" \
  --from-literal=client-secret="$CSEC" \
  --from-literal=password="$(openssl rand -hex 24)" \
  --from-literal=secret-key="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml > clusters/lab/bmm/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/bmm/secret.sops.yaml
```

On the Mac's zsh, the `read` lines are `read -rs 'CID?client id: '; echo`
and `read -rs 'CSEC?client secret: '; echo`.

Create it once. Postgres takes `password` when its volume is first made and
keeps it: a new value later locks BMM out of its own database. And with a
new `secret-key` the stored account credentials cannot be read: every
account has to be connected again. To change only the client, edit in place
with `sops clusters/lab/bmm/secret.sops.yaml`.

A Secret made before BMM 0.2 has no `secret-key`. Add one, without touching
the rest:

```bash
sops set clusters/lab/bmm/secret.sops.yaml '["data"]["secret-key"]' "\"$(openssl rand -hex 32 | tr -d '\n' | base64 | tr -d '\n')\""
```

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
`warehouse`, with the scopes `profiles:read`, `accounts:read`, `posts:read`,
`audit:read` and `tokens:read` and no others. A token's scopes cannot be
changed afterwards: for more, make a new token and delete the old one.
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
the scopes the local agent should have. The `:read` scopes let it look.
`media:write` and `posts:write` let it add images and draft, schedule and
publish posts: with those it can post in your name, unasked if a page it
read told it to. Leave them out until you want that.
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

- **One admin, no other users yet.** BMM has a single account. Anyone
  else Pocket ID lets through is refused by BMM.
- **Connecting an account** is done in the web app: first the network's
  developer app (its client ID and secret) under Networks, then Connect on
  a profile, which sends you to the network to sign in. BMM's guides for
  each network are in its repository under `docs/networks/`.
- **Instagram cannot publish yet.** Instagram takes no uploads: it
  downloads each image from a public address, and nothing of BMM is public
  here. X is not affected. Opening it means one path, `/public/`, reachable
  from the internet, which the chart can do through a Cloudflare Tunnel
  (`publicMedia` in its values). Not set up.
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

`bmm/data-bmm-postgres-0` and `bmm/bmm-data` are in the nightly backup
(`clusters/lab/backup/`): the database from a crash-consistent snapshot of
its volume, and the uploaded images. The third part of a restore is
`secret-key`, which is in `secret.sops.yaml` in this repository. A dump by
hand, before an upgrade for instance:

```bash
kubectl -n bmm exec bmm-postgres-0 -- pg_dump -U bmm bmm > bmm.sql
```
