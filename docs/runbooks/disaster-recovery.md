# Disaster recovery

How to get the lab back from nothing.

This page is deliberately in the public repo rather than in local notes. Its
entire value is being reachable when the workstation, node01 and everything on
them are gone — from a phone, in a hotel, on someone else's laptop. It contains
no secrets, only an order of operations.

---

## Step 0 — the emergency kit

**Nothing below works without these.** They live outside the lab, in a cloud
password manager and on paper, because the self-hosted vault is one of the
things being recovered. You cannot restore a password manager with a password
manager.

| What | Why it is unrecoverable without it |
|---|---|
| age private key | Decrypts every `*.sops.yaml` in this repo. Without it Flux comes up healthy and decrypts nothing |
| restic repository password | The backup is ciphertext. There is no reset |
| S3 access key + secret | Needed to reach the bucket at all |
| Vaultwarden master password | The vault is end-to-end encrypted; the server never had the plaintext |

Plus account access for GitHub, Cloudflare, Hetzner, Tailscale and
healthchecks.io. Most are email-recoverable — which only helps if your email is
reachable without the lab.

The test for anything else you are tempted to store in the vault:
**if node01 is a brick, can I still get this?**

---

## What survives on its own

Everything under `clusters/homelab/` — every manifest, HelmRelease, Ingress,
RBAC rule, alert rule and dashboard — is in git, on GitHub, and needs no
backup. Flux reconstructs the whole cluster from it.

What is *not* in git, and therefore what the backup exists for:

- The two Incus containers, `agents` and `epicurus`
- Local-path PVC data
- Host configuration under `/etc`
- The age key and other secrets (in the kit, not the backup)

---

## Scenario A — node01 is gone

Replacement hardware, or the same machine reinstalled.

### A1. Base system

Ubuntu Server 24.04 LTS, hostname `node01`, OpenSSH enabled, your key
imported. Then the same host preparation as the original build: swap off
(`swapoff -a` plus the fstab entry), lid switch ignored if it is a laptop,
Tailscale joined.

### A2. Prove you can read the backup *before* anything else

```
sudo apt install restic
sudo install -d -m 0700 /etc/restic
sudo install -m 0600 /dev/null /etc/restic/backup.env
sudo nano /etc/restic/backup.env
```

Fill it from the kit — see
[`hosts/node01/backup/README.md`](../../hosts/node01/backup/README.md) for the
exact variable names. Then:

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic snapshots'
```

A snapshot listing means the credentials, the password and the bucket are all
correct. Find that out now, not after you have spent two hours rebuilding.

### A3. Restore to a staging directory

**Never `restic restore --target /`.** It would drop a stale `/etc` over a
fresh install — fstab, machine-id, network config and all — and produce a
machine that boots into somebody else's identity.

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic restore latest --target /restore'
```

Everything below copies selectively out of `/restore`.

### A4. Incus and the containers

Install Incus from the Zabbly stable repo — the Ubuntu archive version is too
old for nested Docker here — then initialise it minimally so the daemon
directories exist:

```
sudo incus admin init --minimal
```

Stop the daemon, put the backed-up state back, start it again:

```
sudo systemctl stop incus incus.socket
sudo rsync -aHAX --delete /restore/var/lib/incus/ /var/lib/incus/
sudo systemctl start incus.socket incus
incus list
```

This restores the Incus database and the storage pool together, so the
instances come back knowing their own limits, devices and profiles.

**If the daemon refuses to start**, its database was captured mid-write. Fall
back to rebuilding the instances from the inventory dumps, which are plain text
and cannot tear:

```
ls /restore/var/tmp/node01-inventory.*/
```

Create each instance from `incus-config-<name>.yaml`, stop it, and copy the
matching `rootfs` directory out of
`/restore/var/lib/incus/storage-pools/default/containers/<name>/` into the new
one.

Expect the databases inside those containers — analytix's Postgres, ClickHouse
and MinIO, epicurus's Postgres — to replay their write-ahead logs on first
start. That is normal: the backup is crash-consistent by design.

### A5. Host configuration

Copy back selectively. Useful candidates, none of them automatic:

- `/etc/systemd/system/` — the restic units and epicurus's reconcile timer
- `/etc/restic/`
- `/etc/incus/`
- `/etc/rancher/` — k3s config

Leave fstab, machine-id, netplan and cloud-init alone unless the hardware is
identical.

### A6. Kubernetes — rebuild from git, in this order

The order matters and getting it wrong produces a failure that points nowhere
near its cause.

**1. Install k3s** with the same flags as the original build:

```
curl -sfL https://get.k3s.io | sh -s - server --tls-san node01.laperm-map.ts.net --disable traefik
```

`--disable traefik` is not optional: ingress-nginx comes from Flux, and k3s's
bundled Traefik would fight it for ports 80 and 443.

**2. Apply the `sops-age` secret BY HAND**, before Flux exists:

```
kubectl create secret generic sops-age -n flux-system --from-file=age.agekey=<path to the key from the kit>
```

The namespace will not exist yet; create it first. The key filename must end in
`.agekey` — that suffix is what kustomize-controller scans for.

**Skip this step and Flux installs cleanly, syncs happily, and fails to decrypt
every secret in the repo with errors that mention neither age nor this
omission.** It is the single most confusing failure mode in the whole rebuild.

**3. Bootstrap Flux:**

```
flux bootstrap github --owner=baakhoff --repository=homelab --branch=main --path=clusters/homelab --personal
```

Then wait. Flux reinstalls cert-manager, ingress-nginx, the monitoring stack,
Loki, Headlamp, Homepage, podinfo and epicurus's routing — everything — from
`main`.

**4. Re-create the wildcard certificate.** cert-manager will request a fresh
one via DNS-01 automatically. Let's Encrypt rate-limits duplicate certificates
to five per week for an identical name set, so if you are rebuilding
repeatedly, that is the limit you will hit first.

### A7. PVC data — the awkward part

Read this before assuming the restore worked.

local-path names each volume's directory `pvc-<uuid>_<namespace>_<name>`, and
the uuid comes from the PVC object. A cluster rebuilt from git creates **new**
PVCs with **new** uuids, so the restored directories no longer match anything
and the workloads come up empty.

For each PVC whose data you actually want back — Grafana's, Alertmanager's,
and later the vault's:

1. Let Flux create the workload and its PVC.
2. Scale the workload to zero so nothing is writing:
   `kubectl -n <ns> scale deployment/<name> --replicas=0`
   (`statefulset/<name>` for Alertmanager and Loki.)
3. Find the new directory name under `/var/lib/rancher/k3s/storage/`.
4. Copy the contents of the old directory from `/restore/...` into it,
   preserving ownership: `sudo rsync -aHAX <old>/ <new>/`
5. Scale back up.

Prometheus and Loki are not in the backup at all — 15d and 7d retention meant
they were already deleting themselves. They start empty and refill. That is the
intended outcome, not a failed restore.

---

## Scenario B — one Incus container is broken

Reach for `incus snapshot` first. It is on the same disk, so it is useless
against hardware failure, but for "I broke it an hour ago" it restores in
seconds instead of pulling gigabytes back over the internet:

```
incus snapshot list <instance>
incus snapshot restore <instance> <snapshot>
```

Only fall through to restic if the snapshot is also gone or too new to help.
Restore that container's directory out of `/restore` with the daemon stopped,
as in A4.

---

## Scenario C — a Kubernetes workload lost its data

Cluster is healthy; one PVC is empty or corrupt.

1. Scale the workload to zero.
2. Restore just that path:

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic restore latest --target /restore --include "/var/lib/rancher/k3s/storage/*_<namespace>_<pvcname>*"'
```

3. `rsync` the contents into the live directory, then scale back up.

Since the cluster was never rebuilt, the uuid still matches and A7's dance does
not apply.

---

## Scenario D — one file

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic find <filename>'
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic restore <snapshot-id> --target /restore --include <path>'
```

`restic mount /mnt/restic` browses every snapshot as a filesystem, which is
usually faster than guessing at snapshot ids.

---

## Scenario E — the password vault

**Try the export first.** A password-protected export imported into any
Bitwarden client takes a minute and needs no lab, no cluster and no restic. Use
this scenario only when the export is stale or missing.

The vault is the one workload with **two copies in every snapshot**, and they
are not equivalent:

| In the snapshot | Use it? |
|---|---|
| `/var/backups/node01-inventory/vaultwarden_vaultwarden-data.sqlite3` | **Yes.** Taken with SQLite's online-backup API and integrity-checked at backup time |
| `.../pvc-*_vaultwarden_vaultwarden-data/db.sqlite3` + `-wal` + `-shm` | Fallback only. Copied file-by-file from a live database, so the three may not belong together |

1. Scale it down, so nothing is writing while you work:

```
kubectl -n vaultwarden scale deployment vaultwarden --replicas=0
```

2. Restore the consistent dump:

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic restore latest --target /restore --include "/var/backups/node01-inventory/vaultwarden_vaultwarden-data.sqlite3"'
```

3. Find the live directory — the uuid is new if the cluster was rebuilt:

```
ls -d /var/lib/rancher/k3s/storage/pvc-*_vaultwarden_vaultwarden-data
```

4. Put the dump in place as `db.sqlite3`, and **delete the old `-wal` and
   `-shm`**. This step is not optional: the dump is a single complete database
   with no write-ahead log, and leaving a WAL from a different database behind
   means SQLite tries to replay frames that do not belong to it.

```
sudo rm -f <pvcdir>/db.sqlite3-wal <pvcdir>/db.sqlite3-shm
sudo cp /restore/var/backups/node01-inventory/vaultwarden_vaultwarden-data.sqlite3 <pvcdir>/db.sqlite3
sudo chown 1000:1000 <pvcdir>/db.sqlite3
```

The `chown` matters — the pod runs unprivileged as uid 1000, and a
root-owned database presents as CrashLoopBackOff rather than a permission
message anywhere obvious.

5. Scale back up and log in:

```
kubectl -n vaultwarden scale deployment vaultwarden --replicas=1
```

`rsa_key.pem` and the attachments live beside the database in the same PVC
directory and come back with a normal Scenario C restore. **Attachments are not
in a Bitwarden export**, so for those the restic copy is the only one.

---

## What this does not cover

- **Anything created after the last nightly run.** The window is up to 24
  hours.
- **The workstation.** Its kubeconfig is regenerated from node01; the age key
  is in the kit; projects are in git. Nothing else there is backed up by this.
- **Tailscale, Cloudflare and healthchecks.io state.** All reconstructed by
  logging in — hence account access being part of the kit.
- **A restore nobody has practised.** A backup that has never been restored is
  a hypothesis. Scenario D costs five minutes and is worth running
  occasionally; Scenario A is worth doing once, deliberately, on scratch
  hardware.
