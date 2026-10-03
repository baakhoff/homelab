# Dawarich

[Dawarich](https://github.com/Freika/dawarich), a self-hosted replacement
for Google Maps Timeline. The phone records where it is and sends it here;
Dawarich draws it on a map and works out trips, visits to places,
countries and cities, and distance per month and year. Old history comes in
from a Google Timeline export, GPX files or OwnTracks.

At <https://location.lab.baakhoff.com>, and on Homepage under Everyday →
Home.

## How login works

Pocket ID, through Dawarich's own OpenID Connect, and nothing else. The
password form and sign-up are off, refused at the API as well as hidden on
the page. An account is created at the person's first Pocket ID login; who
may log in at all is the client's *Allowed User Groups*.

Dawarich has no admin mapping from Pocket ID groups. Admin is set once by
hand, step 3.

The phone apps do not log in. They send points with the account's API key,
which they read from a QR code on the web page (step 4). That is also why
this is **not behind the oauth2-proxy gate**: the gate does not know the
key. ingress.yaml has the rest.

## What is here

| File | What |
|---|---|
| `deployment.yaml` | one pod: the web server, Sidekiq for the background jobs, and Redis between them on loopback; the settings both read, in a ConfigMap |
| `postgres.yaml` | PostGIS 17, where the location history is |
| `pvc.yaml` | the files: import originals, exports |
| `networkpolicy.yaml` | ingress-nginx and Airflow's scheduler to the web server, the pod to Postgres |
| `ingress.yaml` | `location.lab.baakhoff.com`, with the Homepage tile |
| `secret.sops.yaml` | the database password, Rails' secret key and the Pocket ID client - **created by hand, step 2** |

## Setup, in this order

Steps 1 and 2 go on this branch before it merges, together with the backup
Secret in step 2: the backup driver fails its whole nightly run on a target
whose namespace has no `restic-repo` Secret.

**1. Create the OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Dawarich |
| Callback URLs | `https://location.lab.baakhoff.com/users/auth/openid_connect/callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | the people who use it, e.g. `dawarich-users` |

**2. Create the two Secrets on the workstation**, from the repo root. Run
the two `read` lines one at a time: pasted together, the rest of the paste
becomes the input. The other two values are generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic dawarich \
  --namespace dawarich \
  --from-literal=DATABASE_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=SECRET_KEY_BASE="$(openssl rand -hex 64)" \
  --from-literal=OIDC_CLIENT_ID="$CID" \
  --from-literal=OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/dawarich/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/dawarich/secret.sops.yaml
```

Then the backup's copy of the restic credentials, as the backup README
describes:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: dawarich/' \
  > clusters/lab/backup/restic-repo-dawarich.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-dawarich.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-dawarich.sops.yaml
```

The `grep` must print `namespace: dawarich` before you encrypt. Commit both
files and push. The pre-commit hook asserts they are encrypted.

Create the first Secret once. If you run it again, you replace values that
are already in use:

- `DATABASE_PASSWORD` is set in Postgres when the database is first
  created. A new value no longer matches, and Dawarich cannot log in.
- `SECRET_KEY_BASE` is what Dawarich derives its encryption keys from, and
  it encrypts the keys stored in its settings, such as Immich's. A new one
  makes them unreadable, and signs everyone out.

To change only the Pocket ID client, edit the file in place with
`sops clusters/lab/dawarich/secret.sops.yaml`.

**3. Sign in, and make yourself admin.** Open
<https://location.lab.baakhoff.com> and sign in with Pocket ID. The first
start loads every country's border into PostGIS, which takes a few
minutes.

Dawarich's first start also creates a demo admin, `demo@dawarich.app`, with
a password published in its source. With the password login off nobody can
use it, but it should not exist. Once you have signed in, on the
workstation:

```bash
read -rp 'your Pocket ID email: ' ME
kubectl -n dawarich exec deploy/dawarich -c web -- env ME="$ME" bundle exec rails runner '
  User.find_by!(email: ENV["ME"]).update!(admin: true)
  User.find_by(email: "demo@dawarich.app")&.destroy!
  p User.pluck(:email, :admin)'
```

It prints every account with its admin flag: yours with `true`, and no
demo. Admin is what opens the instance settings: reverse geocoding, and
the background-jobs page at `/sidekiq`.

**4. The phone.** Install Dawarich from the App Store or Google Play. In
the web page, open the account's API access page, which shows a QR code;
in the app, choose a self-hosted server and scan it. Then give the app
location access *Always* and, on Android, no battery optimisation. On
iPhone, *Battery saver* mode records only significant moves; *Detailed*
draws the actual path.

The phone reaches the server only at home or with Tailscale on. Away from
both it keeps recording and sends the backlog when it next can.

**5. Feed the data warehouse.** Airflow's `ingest_dawarich` DAG copies
the history into ClickHouse's `raw.dawarich` once a day
(`pipelines/dags/ingest.py`), with an API key. Until the key exists, that
DAG's runs fail and nothing else is affected.

The key is the one on the same API access page. On the workstation from the
repo root, one line at a time:

```bash
read -rsp 'dawarich api key: ' DK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["DAWARICH_API_KEY"]' "\"$(printf %s "$DK" | base64 | tr -d '\n')\""
unset DK
```

On the Mac's zsh, the first line is `read -rs "DK?dawarich api key: "; echo`.
Commit and push. Once Flux has applied it, restart the scheduler, because a
pod reads its environment only when it starts:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
```

Then trigger `ingest_dawarich` in the Airflow UI, and after it the
`warehouse` DAG. The day-by-day view is `ads.location_daily`.

## Importing old history

Google Timeline, from either a Takeout export or the phone's own export
(Google Maps → Your Timeline → Export), GPX, FIT (Garmin workouts), KML,
GeoJSON, CSV and OwnTracks recordings: Dawarich's Imports page. Big files
are processed in the background by Sidekiq and can take a while; the page
shows progress. The upload limit at the Ingress is 2 GB.

The warehouse only reads the last week of points each day, so an import of
older history does not reach it by itself. After an import, trigger
`ingest_dawarich` once with `points_since` set to `2000-01-01` in the
Trigger dialog's run parameters. That one run sends every point; the daily
runs carry on from there.

## What reaches the warehouse

The API key belongs to one account, and Dawarich's API answers for that
account only. So the warehouse holds **one person's history**, the key
owner's. The key has the account's full rights, read and write. It reaches
the web server directly on 3000, not through the Ingress, past a door in
`networkpolicy.yaml`.

- **Points** (`ods.dawarich_points`): each day's run sends the last seven
  days of points, because the whole history is millions of them. The model
  keeps each point once, as first seen, so a point edited or deleted in
  Dawarich later stays as it was. Points Dawarich flagged as GPS jumps are
  not sent.
- **Visits and places** (`ods.dawarich_visits`, `ods.dawarich_places`):
  full snapshots each run, so a deleted one drops out.
- **Per day** (`ads.location_daily`): points, distance, first and last
  point, countries, and the visits that started that day.

## Things to know

- **Nothing leaves the lab.** Reverse geocoding, which turns points into
  street, city and place names, is the lab's own Photon
  (`clusters/lab/photon/`), set in `deployment.yaml`. It holds Denmark,
  the Balkans, Greece, Romania, Turkey, Georgia, Russia, China and
  Kazakhstan; a point elsewhere keeps its country and gets no street.
  Countries are worked out locally, from the borders loaded at the first
  start. The instance settings page shows Photon as pinned by a variable:
  a provider entered there does not replace it. Immich, below, stays
  inside the lab too.
- **Old points are geocoded overnight.** A nightly job looks up every point
  that has no address yet, so an imported history gets its streets and
  cities over the following nights, with no step to run.
- **Immich**, once it is in the lab: each user enters its URL and an Immich
  API key in their own Dawarich settings, and their photos appear on the map
  at the places they were taken. Immich's side will need a door for this
  pod in its NetworkPolicy. The key wants `asset.read` and `asset.view`.
- **A restart loses queued jobs.** Redis keeps no data, as in Paperless. A
  large import that was being processed when the pod restarted has to be
  started again; the points already written stay.
- **Each person has their own map.** Everyone signs in with their own
  Pocket ID and sees only their own history. Dawarich's Family feature,
  in the account settings, lets members share their location with each
  other.
- **Upgrades are migrations.** The web container migrates the database
  forward on start. Rolling back an image bump means restoring the
  database, which is what the backup is for.

## Backup

Both volumes are in the nightly backup (`clusters/lab/backup/`), after
SparkyFitness: `dawarich/data-dawarich-postgres-0`, the database with the
whole history, and `dawarich/dawarich-storage`, the import originals.

Each is a crash-consistent snapshot, taken while the app runs. That is the
state Postgres recovers from after a power cut, so it restores cleanly.
