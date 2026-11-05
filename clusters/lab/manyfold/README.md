# Manyfold

[Manyfold](https://manyfold.app) keeps the 3D models - downloaded from
Printables, Thingiverse or MakerWorld, bought, or designed here - in one
library, sorted by creator, collection and tag. Each model is shown in a
3D viewer in the browser, with its pictures and instructions beside it,
and goes to the slicer in one click: Bambu Studio, Orca, PrusaSlicer or
Cura.

At <https://models.lab.baakhoff.com>, and on Homepage under Home.

## How it is put together

| File | What |
|---|---|
| `namespace.yaml` | the namespace, at Pod Security `baseline` |
| `deployment.yaml` | the app - web server and background workers in one container - with Redis beside it on loopback; its settings, in a ConfigMap |
| `postgres.yaml` | its own Postgres 18, on Ceph |
| `pvc.yaml` | the library: the NAS share `tank/models`, over NFS through csi-driver-nfs |
| `networkpolicy.yaml` | ingress-nginx, Airflow's scheduler and the brand agent to the app, the app to Postgres |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |
| `service.yaml`, `ingress.yaml` | `models.lab.baakhoff.com`, with the Homepage tile |
| `secret.sops.yaml` | the app's keys, the database password and the Pocket ID client - **created by hand, step 3** |

The files are on the NAS, in a folder per model, as they were downloaded
or uploaded. Manyfold writes beside them: a `datapackage.json` per model
with its name, tags, creator and licence, and the previews and renders it
makes, under `.manyfold/`. So the folders still say what each model is
without the database.

The container starts as root, gives its temporary folders to the NAS's
`manyfold` user and runs the app as that user, with only the capabilities
that hand-over needs - upstream's [hardening
guide](https://manyfold.app/sysadmin/security.html), read-only root and
all.

## Login

Pocket ID, through Manyfold's own sign-in, and behind the oauth2-proxy gate
as well, like Karakeep. In practice it is one passkey. There are no
Manyfold passwords: the password form is off (`FORCE_OIDC`).

**Manyfold makes an account for anyone Pocket ID lets through**, whatever
its own sign-up settings say, so who may sign in is decided in Pocket ID
alone: the client's *Allowed User Groups*. The first account to sign in is
the admin.

## Slicers

"Open in Bambu Studio" (and the others) hands the slicer a link to the
file, which it downloads by itself, without the browser's login. Those
links are open past the gate (`ingress.yaml`): each carries a signature
Manyfold made for that one file, valid for an hour. Bambu Studio opens
3MF files this way only; for an STL, download it and open it.

## Setup, in this order

Steps 1 to 3 come before the merge. Step 3's backup Secret has to be on the
branch: the backup driver fails its whole nightly run on a target whose
namespace has no `restic-repo` Secret. The pod waits in
`CreateContainerConfigError` until step 3's first Secret exists.

**1. The NAS.** In TrueNAS:

- *Credentials → Groups*: add `manyfold`. *Credentials → Users*: add
  `manyfold`, primary group `manyfold`, password disabled, shell
  `nologin`, no SMB. Its UID and GID must be `PUID` and `PGID` in
  `deployment.yaml`, 3002 and 3003, the next free ones after `media`; if
  TrueNAS gave others, change both.
- *Datasets*, under `tank`: `models`, preset **Generic**, not encrypted
  (like `media`: models can be fetched again, and the CPU's AES is slow),
  record size 1M, atime off, quota 200 GiB - the size in `pvc.yaml`.
  Permissions: owner `manyfold:manyfold`, mode 770.
- *Shares → NFS*: path `/mnt/tank/models`; networks `192.168.68.102/32`,
  `192.168.68.103/32` and `192.168.68.104/32`; Mapall user and group
  `manyfold`.

Check over SSH: `sudo cat /etc/exports` shows the new share for the three
addresses, each with `all_squash,anonuid=3002,anongid=3003`.

**2. Pocket ID**, at `https://id.lab.baakhoff.com`: a group
`manyfold-users` with the people who use Manyfold in it, then
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Manyfold |
| Callback URLs | `https://models.lab.baakhoff.com/users/auth/openid_connect/callback` |
| PKCE | off - Manyfold does not send it |
| Public Client | off |
| Allowed User Groups | `manyfold-users` |

**3. The Secrets, on the workstation** from the repo root, on this branch,
in bash. Run the `read` lines one at a time: pasted together, the rest of
the paste becomes the input. The other two values are generated and never
shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic manyfold \
  --namespace manyfold \
  --from-literal=SECRET_KEY_BASE="$(openssl rand -hex 64)" \
  --from-literal=DATABASE_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=OIDC_CLIENT_ID="$CID" \
  --from-literal=OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/manyfold/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/manyfold/secret.sops.yaml
```

Create it once. `DATABASE_PASSWORD` is set in Postgres when the database is
first created, and `SECRET_KEY_BASE` signs every session and file link: new
values lock Manyfold out of its database and sign everyone out. To change
only the client, edit in place with
`sops clusters/lab/manyfold/secret.sops.yaml`.

Then the backup's copy of the restic credentials:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: manyfold/' \
  > clusters/lab/backup/restic-repo-manyfold.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-manyfold.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-manyfold.sops.yaml
```

The `grep` must print `namespace: manyfold` before you encrypt. Commit and
push both files; the pre-commit hook checks that they are encrypted.

**4. Right after the merge: sign in first**, so the admin account is yours.
Run the schema job now rather than at the hour, so `raw.manyfold` exists
before the first ingest, and wait for the app:

```bash
kubectl -n data create job --from=cronjob/clickhouse-schema schema-manyfold
kubectl -n manyfold rollout status deploy/manyfold --timeout=10m
```

Then make the library, before anyone signs in. Manyfold sends everyone
who is not its admin away while it has no library - its Pocket ID sign-in
included, so with no admin yet, nobody gets in. Upstream expects its own
local admin to make the first library, and `FORCE_OIDC` has none. So it is
made from the command line, as the NAS user, which also checks the share
is writable:

```bash
kubectl -n manyfold exec deploy/manyfold -c manyfold -- s6-setuidgid 3002:3003 bin/rails runner 'l = Library.create!(path: "/libraries/models", name: "Models"); puts l.id'
```

It prints the library's number. "Path must be writable" means the dataset
is not owned by `manyfold`, mode 770 (step 1). Then open
<https://models.lab.baakhoff.com> and sign in with Pocket ID. Usage
reporting, under Settings, is off as it starts and stays off.

**5. Feed the data warehouse.** In Manyfold, Settings → API keys → New
API key: name `warehouse`, redirect URI `urn:ietf:wg:oauth:2.0:oob` (there
is none: the DAG asks for its own token), confidential, scopes **read**
only. It reads what your account can see, and changes nothing. Its UID and
secret, one line at a time:

```bash
read -rsp 'manyfold client id: ' MID; echo
read -rsp 'manyfold client secret: ' MSEC; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["MANYFOLD_CLIENT_ID"]' "\"$(printf %s "$MID" | base64 | tr -d '\n')\""
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["MANYFOLD_CLIENT_SECRET"]' "\"$(printf %s "$MSEC" | base64 | tr -d '\n')\""
unset MID MSEC
```

Commit and push. Once Flux has applied it, restart the scheduler, because a
pod reads its environment only when it starts. Delete the pod rather than
`rollout restart`, which Flux undoes:

```bash
kubectl -n airflow delete pod -l component=scheduler
```

Then, in the Airflow UI, switch `ingest_manyfold` on - Airflow pauses every
new DAG until someone does - and trigger it, and after it the `warehouse`
DAG. Until the keys exist, that DAG's runs fail and nothing else is
affected.

**6. The brand agent's key.** In Manyfold, Settings → API keys → New API
key: name `brand`, redirect URI `urn:ietf:wg:oauth:2.0:oob`, confidential,
scopes **read** only. It reads every model and file your account can see
and changes nothing. Brand asks for a token with it (`POST /oauth/token`,
`grant_type=client_credentials`, `scope=read`, valid two hours) and sends
`Accept: application/vnd.manyfold.v0+json`; the API's own description is
at `/api` on the site. Put the key's UID and secret in brand's
`~/.config/brand/secrets.env` as `MANYFOLD_CLIENT_ID` and
`MANYFOLD_CLIENT_SECRET`, with
`MANYFOLD_URL=http://manyfold.manyfold.svc.cluster.local`, then restart
brand so it reads them:
`kubectl -n agents delete pod -l app.kubernetes.io/name=brand`. Deleting
the key in Manyfold takes the access back.

## What goes to the warehouse

Airflow's `ingest_manyfold` DAG copies what the `warehouse` application's
account can see into ClickHouse's `raw.manyfold`, daily at 04:10
(`pipelines/dags/ingest.py`). Every model and every file is a request of
its own, so once a day rather than every six hours.

| Table | One row per |
|---|---|
| `ods.manyfold_models` | model: name, caption, description, licence, creator, collections, tags, how many files, links |
| `ods.manyfold_model_files` | file of a model: name, type, size, whether it is presupported |
| `ods.manyfold_creators` | creator, with their links |
| `ods.manyfold_collections` | collection, with its creator and the collection it sits in |

The files themselves stay on the NAS.

**Who can read it:** anyone who can read `ods`, which includes the brand
agent's `brand` user.

## Things to know

- **Adding models**: upload in the web app (up to 1 GiB a file, zips
  unpacked), or copy folders onto the NAS share and run a scan from the
  library's menu. A folder per model; Manyfold finds the rest.
- **When the NAS is away, Manyfold waits.** The share is mounted `hard`:
  anything touching the library blocks until the NAS answers again. A pod
  started meanwhile waits in ContainerCreating.
- **A restart loses queued jobs.** Redis keeps no data. A scan from the
  library's menu queues what is missing again.
- **Upgrades only go forward.** Manyfold migrates its database at every
  start. Renovate opens a PR for each release - often, every week or two;
  read the release notes before merging. The nightly backup is the undo.

## Backup

- **The database** is in the cluster's nightly backup
  (`clusters/lab/backup/`): `manyfold/data-manyfold-postgres-0`. It holds
  the tags, creators, collections and accounts.
- **The library** is on the NAS, outside what the cluster backs up: the
  NAS snapshots it with ZFS, hourly and daily. Each model's
  `datapackage.json` carries its details too, so a library scanned into a
  fresh database gets them back.
