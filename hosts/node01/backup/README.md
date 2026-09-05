# node01 backup

Nightly [restic](https://restic.net/) backup of node01 to Hetzner Object Storage,
driven by a systemd timer. Weekly retention pass and integrity check alongside it.

## Why this lives outside `clusters/homelab/`

Flux reconciles Kubernetes objects. A systemd timer on the host is not one, so
these files are installed by hand.

That is a real gap and worth naming: nothing detects drift here. If someone edits
`/usr/local/sbin/restic-backup.sh` on node01 and does not mirror the change back
into git, the repo is quietly wrong and nothing says so — unlike everything under
`clusters/homelab/`, where Flux reverts drift within minutes.

## What is backed up

Everything under these paths, minus `restic-excludes.txt`:

| Path | Why |
|---|---|
| `/etc` | netplan, sshd, systemd units, incus daemon config |
| `/var/lib/incus` | **the payload** — the `agents` and `epicurus` containers |
| `/var/lib/rancher/k3s/server` | CA, node token, bundled manifests, and the SQLite object store — a fallback, not the restore path |
| `/var/lib/rancher/k3s/storage` | every local-path PVC except the two excluded |
| `/root` | dotfiles and anything left there |

Plus a small inventory dumped fresh on each run: Incus instance/profile/network
configs as text, `dpkg --get-selections`, kernel and OS release, and the
local-path PVC directory listing.

**Kubernetes objects are deliberately absent.** Flux rebuilds every one of them
from `main` given the age key. Backing them up would store a worse copy of what
git already holds. See [the disaster recovery runbook](../../../docs/runbooks/disaster-recovery.md).

## Install

Everything below runs on **node01**.

### 1. restic

```
sudo apt install restic
```

The distro package rather than a downloaded binary, because `unattended-upgrades`
is already enabled here and will patch it. A hand-placed binary in
`/usr/local/bin` gets security fixes only when someone remembers. The apt version
lags upstream, which is an acceptable trade for a long-lived root cron job —
repository format v2 and zstd compression both landed in restic 0.14, well below
what Ubuntu 24.04 ships.

### 2. Credentials

```
sudo install -d -m 0700 /etc/restic
sudo install -m 0600 /dev/null /etc/restic/backup.env
sudo nano /etc/restic/backup.env
```

Shape of the file — **real values go here and nowhere else, never into git**:

```
RESTIC_REPOSITORY=s3:https://hel1.your-objectstorage.com/baakhoff-lab-backup
RESTIC_PASSWORD=<restic repository password>
AWS_ACCESS_KEY_ID=<Hetzner S3 access key>
AWS_SECRET_ACCESS_KEY=<Hetzner S3 secret key>
HC_URL=<healthchecks.io ping URL, nightly backup check>
HC_PRUNE_URL=<healthchecks.io ping URL, weekly prune check>
```

restic's S3 backend reads the standard `AWS_*` variable names regardless of
provider — Hetzner is S3-compatible, not AWS.

The repository URL is in this file rather than in the units because there is no
reason to publish where the backups live, even though a bucket name is not a
secret and is useless without the keys.

`RESTIC_PASSWORD` and the S3 keys must also exist **outside this machine** —
see the recovery runbook. A backup whose password only lives on the machine it
protects is not a backup.

### 3. Initialise the repository

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic init'
```

Sourcing rather than passing values as arguments keeps them out of `ps` and out
of shell history.

Run once, ever. On an already-initialised repository this fails harmlessly.

### 4. Install the script and units

From a checkout of this repo on node01, or after copying the files across:

```
sudo install -m 0755 restic-backup.sh /usr/local/sbin/restic-backup.sh
sudo install -m 0755 restic-prune.sh  /usr/local/sbin/restic-prune.sh
sudo install -m 0644 restic-excludes.txt /etc/restic/excludes.txt
sudo install -m 0644 restic-backup.service restic-backup.timer \
                     restic-prune.service restic-prune.timer \
                     /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5. First run, watched

```
sudo systemctl start restic-backup.service
```

```
journalctl -u restic-backup.service -f
```

The first run uploads everything and takes a while — roughly 58G of container
filesystems, compressed by restic before it leaves the machine. Every run after
it ships only changed chunks.

### 6. Enable the timers

```
sudo systemctl enable --now restic-backup.timer restic-prune.timer
```

```
systemctl list-timers 'restic-*'
```

## Verification

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; restic snapshots'
```

A snapshot listing is the only thing that proves the backup exists. A green
systemd unit proves the script exited zero, which is not the same claim.

Grep the journal for consistency warnings, which are expected in small numbers
and worth reading:

```
journalctl -u restic-backup.service | grep -i 'changed while'
```

## Object Lock and versioning

If the bucket was created with Object Lock enabled, versioning is on
permanently. That changes what pruning does: `restic forget --prune` deletes
objects, but under versioning a delete creates a *noncurrent version* rather
than freeing space. Storage keeps growing even though the retention policy is
working correctly.

The fix is a bucket lifecycle rule expiring noncurrent versions after a short
window. Without one, watch the bucket size rather than trusting the retention
policy to bound it.

## Known limitations

These are properties of the current setup, recorded so nobody rediscovers them
during a restore:

- **Crash-consistent, not atomic.** The backup walks the live filesystem, so
  databases inside the Incus containers are captured as if the power had been
  cut — recoverable by design, but a file can change mid-walk. A copy-on-write
  storage pool would make this atomic; this pool is `dir`. Full reasoning is in
  the header of `restic-backup.sh`.
- **node01 can delete its own backups.** The credential in
  `/etc/restic/backup.env` has full access to the bucket, so a compromise of the
  machine is a compromise of the backup. Object Lock retention or a bucket
  policy denying `DeleteObject` outside the `locks/` prefix would break that
  link; neither is configured.
- **No drift detection**, as above.
