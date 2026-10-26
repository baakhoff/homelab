# Immich

[Immich](https://immich.app), the family's photos and videos in one place:
the phones back up to it, old libraries are imported into it, and it finds
faces, places and things in the pictures - "dog on the beach" - in any of
the household's languages. That machine learning runs here, on the CPU.
The one thing sent out is the [sorting by type](#sorting-by-type): each
picture's preview, to Claude, for a description and a type.

At <https://photos.lab.baakhoff.com>, and on Homepage under Everyday →
Home. The phones use the same address at home and, over Tailscale, away.

## How login works

Pocket ID, through Immich's own OpenID Connect, and nothing else once
setup is done: password login is switched off. An account is created at the
person's first Pocket ID login; who may log in at all is the client's
*Allowed User Groups*, `immich-users`.

Roles come from Pocket ID too, as a custom claim Immich re-reads at every
login: `immich_role` is `user` on the group, and `admin` on the owner's own
user, which wins over the group's value.

The phone apps sign in the same way, through the phone's browser, and then
upload with Immich's own token. That is why this is **not behind the
oauth2-proxy gate**: the gate does not know the token. ingress.yaml has
the rest.

## What is here

| File | What |
|---|---|
| `namespace.yaml` | the namespace, at Pod Security `baseline` |
| `deployment.yaml` | the server - web, API and every background job - with Redis beside it on loopback; the settings it reads at start, in a ConfigMap |
| `machine-learning.yaml` | smart search, faces and text, on the CPU, with its model cache |
| `postgres.yaml` | Immich's own Postgres 18 with VectorChord, on Ceph |
| `pvc.yaml` | the library: the NAS share `tank/immich`, over NFS through csi-driver-nfs |
| `networkpolicy.yaml` | ingress-nginx and Airflow's scheduler to the server, the server to machine learning and Postgres |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |
| `service.yaml`, `ingress.yaml` | `photos.lab.baakhoff.com`, with the Homepage tile |
| `secret.sops.yaml` | the database password - **created by hand, step 3** |

## Setup, in this order

Steps 1 to 3 come before the merge. Step 3's backup Secret has to be on the
branch: the backup driver fails its whole nightly run on a target whose
namespace has no `restic-repo` Secret. Steps 4 and 5 come right after the
merge, without a break: until the first account exists, anyone who can
reach the address can create it.

**1. The NAS.** In TrueNAS:

- *Credentials → Groups*: add `immich`. *Credentials → Users*: add `immich`,
  primary group `immich`, password disabled, shell `nologin`, no SMB. Its
  UID must be the `runAsUser` in `deployment.yaml` and
  `machine-learning.yaml`, 3000; if TrueNAS gave another, change both.
- *Datasets*, under `tank`: `immich`, preset **Generic**, encrypted with a
  key and unlocked at boot like `personal`, record size 1M, atime off, quota
  800 GiB - the size in `pvc.yaml`. Permissions: owner `immich:immich`,
  mode 770. Export the new key to the password manager, and download a fresh
  configuration export (the runbook says why).
- *System → Services → NFS*: NFSv4 only, bound to `192.168.68.105`, started
  automatically.
- *Shares → NFS*: path `/mnt/tank/immich`; networks `192.168.68.102/32`,
  `192.168.68.103/32` and `192.168.68.104/32`; Mapall user and group
  `immich`. Every client is then the `immich` user, root included.

Check over SSH: `sudo cat /etc/exports` shows the three addresses, each with
`all_squash,anonuid=3000,anongid=3000`.

**2. Pocket ID**, at `https://id.lab.baakhoff.com`:

- A group `immich-users`, with the custom claim `immich_role` = `user`, and
  the people who use Immich in it.
- On your own user, the custom claim `immich_role` = `admin` - **before
  your first Immich login**, or the group's `user` takes admin away from the
  account that created the instance.
- Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Immich |
| Callback URLs | `https://photos.lab.baakhoff.com/auth/login`, `https://photos.lab.baakhoff.com/user-settings`, `app.immich:///oauth-callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | `immich-users` |

The client id and secret go into Immich's settings in step 4, not into a
file here. Keep them in the password manager until then.

**3. Create the two Secrets on the workstation**, from the repo root. The
password is generated and never shown; upstream allows letters and digits
only, which hex is.

```bash
kubectl create secret generic immich \
  --namespace immich \
  --from-literal=DB_PASSWORD="$(openssl rand -hex 24)" \
  --dry-run=client -o yaml > clusters/lab/immich/secret.sops.yaml
sops --encrypt --in-place clusters/lab/immich/secret.sops.yaml
```

Then the backup's copy of the restic credentials, as the backup README
describes:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: immich/' \
  > clusters/lab/backup/restic-repo-immich.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-immich.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-immich.sops.yaml
```

The `grep` must print `namespace: immich` before you encrypt. Commit both
files and push.

Create the first Secret once. `DB_PASSWORD` is set in Postgres when the
database is first created; a new value no longer matches, and Immich cannot
log in.

**4. Right after the merge: the first account, then the settings.** Watch
`kubectl -n immich get pods` until all three are ready; the server's log
says `Successfully verified system mount folder checks`. Then open
<https://photos.lab.baakhoff.com> and create the admin account with
**exactly your Pocket ID email** and a long random password you will not
need again. Then, under Administration → Settings:

| Setting | Value |
|---|---|
| Authentication → OAuth | on; issuer `https://id.lab.baakhoff.com`; the client id and secret from step 2; scope `openid email profile`; button text `Sign in with Pocket ID`; auto register on; auto launch on; role claim `immich_role`; storage quota claim `immich_quota`; default storage quota **empty** - 0 would refuse every upload |
| Server | external domain `https://photos.lab.baakhoff.com` |
| New version check | off - Renovate says when there is one |
| Storage template | **on, before anything is uploaded**: files are then kept in year and date folders, readable on the NAS without the database |
| Machine learning → Smart search | model `ViT-B-16-SigLIP2__webli`, which understands searches in any language; the default understands English only. Changing it later means indexing every photo again |
| Machine learning → Facial recognition | `buffalo_l`, the default |
| Video transcoding | threads 2; accepted video codecs H.264 **and HEVC**, so most phone videos are kept as they are rather than converted |
| Job settings | concurrency: thumbnails 2, metadata 2, smart search 1, face detection 1, video conversion 1, OCR 1 |
| Backup → database dump | on, `0 1 * * *`, keep 14 |

Sign out, and sign in with **Sign in with Pocket ID**: Immich links your
Pocket ID login to the account by its email. Then Authentication →
Password login: off.

**5. Setup closes itself.** `IMMICH_ALLOW_SETUP` is `"false"` in
`deployment.yaml`, which switches off the first-account page and restoring a
database from the web. On a fresh install that also blocks step 4: take the
line out until the first account exists, then put it back, bumping
`immich.lab/config-revision` each time.

**6. The warehouse's key.** In Immich, Account settings → API keys → New,
with only the permissions `server.statistics` and `adminUser.read`. Then:

```bash
read -rsp 'immich api key: ' IK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["IMMICH_API_KEY"]' "\"$(printf %s "$IK" | base64 | tr -d '\n')\""
unset IK
```

Commit and push. Once Flux has applied it, restart the scheduler so it reads
the new variable: `kubectl -n airflow delete pod -l component=scheduler` (not
`rollout restart`, which Flux undoes). Until the key exists, `ingest_immich`
fails, harmlessly.

**7. The phones.** Install Immich and Tailscale. Server
`https://photos.lab.baakhoff.com`, sign in with Pocket ID. Backup: choose
the camera albums; keep the Wi-Fi-only default. On Android, turn battery
optimisation off for both apps, or the backup stops in the background; on
an iPhone, keep Background App Refresh on and Low Power Mode off. Do the
first backup at home, charging, with the app open.

**8. The sorting's keys**, for [sorting by type](#sorting-by-type), any
time after step 6. In Immich, Account settings → API keys → New, named
`sorting`, with only `user.read`, `asset.read`, `asset.view`, `tag.read`,
`tag.create`, `tag.asset`, `album.read`, `album.create` and
`albumAsset.create`. And a key
from the Claude Console, <https://console.anthropic.com> → API keys,
ideally in a workspace of its own with a monthly spend limit. Then, one
`read` at a time:

```bash
read -rsp 'immich sorting key: ' IK; echo
read -rsp 'anthropic api key: ' AK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["IMMICH_SORT_API_KEY"]' "\"$(printf %s "$IK" | base64 | tr -d '\n')\""
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["ANTHROPIC_API_KEY"]' "\"$(printf %s "$AK" | base64 | tr -d '\n')\""
unset IK AK
```

Commit and push, and restart the scheduler as in step 6 - after the
*airflow image* workflow in GitHub Actions has finished, if it is running:
the image carries what shrinks the previews, and a scheduler without it
sends them full size, at about 1.7 times the cost. Until the keys exist,
`immich_sort` fails, harmlessly.

## Importing old photos

With [immich-go](https://github.com/simulot/immich-go), on a computer that
holds the files - wired, ideally, since every byte crosses the network
twice when the files are on the NAS's other share. A key from Account
settings → API keys with all permissions, deleted afterwards. A Google
Takeout is read straight from its zips, with every part present at once:
the dates, places and albums are in JSON files that may sit in a different
part from the photo.

```bash
immich-go upload from-google-photos --server=https://photos.lab.baakhoff.com --api-key="$K" --concurrent-tasks=2 takeout-*.zip
immich-go upload from-folder --server=https://photos.lab.baakhoff.com --api-key="$K" --concurrent-tasks=2 <folder>
```

Add `--dry-run` first to see what it would do. It pauses Immich's jobs
while it uploads; when it is done they run, for hours on a large import, at
the concurrency set in step 4. Files already in Immich are skipped, so
running it twice, or importing overlapping sources, is safe.

## Sorting by type

Every hour at :05, `immich_sort` ([`pipelines/dags/immich_sort.py`](../../../pipelines/dags/immich_sort.py))
takes the photos and videos that have no type yet, newest first, and shows
each to Claude Haiku. Claude sees the preview (for a video, one frame),
shrunk to 768 pixels, and the file's name, size, camera, date, and whether
anyone in it has a name here. Claude answers three things:

- **What it shows**, in one to three sentences: who and what is in it,
  the kind of place, what is happening, the gist of any text. That goes
  into the warehouse, below, not into Immich.
- **Its type.** This becomes a tag under **Type**, in the sidebar's Tags:
  Type/Food, Type/Screenshots, Type/Memes. Claude makes the types itself,
  up to 25, and after that only uses those.
- **Whether nobody would miss it.** That means memes, screenshots whose use
  is over, chat videos saved to pass on, and failed shots. These also go
  into the album **To delete**.

The album is for a look, not a bin: nothing is deleted, archived or changed
by the sorting. In the album, select what can go and delete it; it waits
30 days in Immich's trash. Take what is worth keeping out of the album, or
add it to another one.

- **A favourite is never set aside.** The locked folder, the trash and a
  partner's shared photos are never looked at.
- **A picture is sorted once.** Once it has a type it is never looked at
  again, so taking it out of *To delete* is final. Removing its Type tag
  sends it round once more.
- **Types are tags, yours to change.** Rename one in Immich and the next
  run uses the new name. Delete one and its pictures are sorted again.
- **The first runs work through the library**, 2,000 pictures or 40
  minutes a run. After that, a new upload is sorted within the hour; one
  without a preview yet, straight off the phone, waits for the next run.
- **It costs about $0.002 a picture** at Haiku's list price. That makes a
  library of 30,000 about $60 once, then cents a month, and a run at most
  about $4. `ods.immich_sort_runs` has each run's tokens and an estimate in
  dollars; the Console's spend limit is the hard stop. Once it is reached,
  each run fails at its first picture, saying so in its log, until the
  limit is raised or the month turns.
- **The previews leave the house**, to Anthropic's API, which does not
  train on what it is sent. A picture's own text is treated as part of the
  picture, never as an instruction.

## What reaches the warehouse

- **`ods.immich_photos`**: one row per photo or video the sorting has
  looked at - its file name and Immich id, when it was taken, where (city,
  country and coordinates, Immich's own from the file), its type, Claude's
  description, and whether it was set aside. So the warehouse, which the
  brand agent reads, can say what the photos are of and where they were
  taken.
- **`ods.immich_usage`**: each account's photos, videos and bytes, from
  the server's statistics.
- **`ods.immich_users`**: the accounts' names, roles and dates, without
  their emails.
- **`ods.immich_sort_runs`**: each sorting run's counts and tokens.

Faces, people's names and albums are not ingested. Immich's log lines
name files and people, so they stop at Loki and never reach Kafka
(`clusters/lab/logging/alloy.yaml`).

## Things to know

- **The photos are on one disk with no copy elsewhere yet.** The NAS
  snapshots them hourly and daily, which undoes a deletion but not a dead
  disk. Until the NAS has an off-site copy, keep the originals where they
  were - Google Photos, the phones, the PC's copy - and do not use the
  app's *free up space*.
- **When the NAS is away, Immich waits.** The share is mounted `hard`:
  anything touching the library blocks until the NAS answers again, then
  carries on. A pod started meanwhile waits in ContainerCreating. After a
  short power cut the NAS can stay off while the nodes come back: `ssh
  <user>@exitnode wake-nodes nas`.
- **If Immich asks for a first admin again, it has no admin left.** A
  Pocket ID login that carries `immich_role` = `user` takes admin away,
  and when that happens to the only admin, every page leads to the setup
  form, which cannot succeed with an email that is taken. It happened on
  the first day, before the user-level claim was saved. Fix the claim in
  Pocket ID, then give admin back from the command line, with OAuth off
  meanwhile so the next login cannot take it again:

  ```
  kubectl -n immich exec -it deploy/immich-server -c server -- immich-admin disable-oauth-login
  kubectl -n immich exec -it deploy/immich-server -c server -- immich-admin grant-admin
  kubectl -n immich exec -it deploy/immich-server -c server -- immich-admin reset-admin-password
  ```

  Sign in with that password, switch OAuth back on in the settings, and
  test the Pocket ID login in a private window while still signed in.
- **A restart loses queued jobs.** Redis keeps no data. Administration →
  Jobs → *Missing* queues them again.
- **Sessions do not expire, and Pocket ID cannot end them.** To take
  someone's access away, remove them from `immich-users` **and** delete
  their sessions or account in Immich; a signed-in phone keeps working
  otherwise.
- **Shared links work only inside the house and the tailnet**, like
  everything here. Share with family through their own accounts and shared
  albums instead.
- **Upgrades only go forward.** Immich does not support going back even
  one patch release. Before merging a bump: read the release notes, update
  the phone apps first, then take a database dump (Administration →
  Maintenance) and a snapshot of `tank/immich`. Renovate moves the server
  and machine learning in one PR; the Postgres image waits for approval on
  its dashboard.

## Backup

- **The database** is in the cluster's nightly backup
  (`clusters/lab/backup/`): `immich/data-immich-postgres-0`. It holds the
  albums, named faces, favourites and descriptions - painful to lose, though
  the photos survive without it.
- **Immich's own dump** of it is written at 01:00 into `backups/` on the
  NAS share, beside the photos, so every NAS snapshot carries a dump from
  the same night.
- **The library** is on the NAS, outside what the cluster backs up: the
  backup driver snapshots Ceph volumes, and this is NFS. The NAS's ZFS
  snapshots cover it. Its off-site copy is not set up yet - see the first
  point above.
- **Not backed up**: the model cache, downloaded again on first use.
