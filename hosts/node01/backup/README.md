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
RESTIC_REPOSITORY=s3:https://fsn1.your-objectstorage.com/baakhoff-lab-backup
RESTIC_PASSWORD=<restic repository password>
AWS_ACCESS_KEY_ID=<Hetzner S3 access key>
AWS_SECRET_ACCESS_KEY=<Hetzner S3 secret key>
HC_URL=<healthchecks.io ping URL, nightly backup check>
HC_PRUNE_URL=<healthchecks.io ping URL, weekly prune check>
```

**The location in that hostname must match the bucket's actual location.**
Getting it wrong does not produce a "not found" error: restic cannot see a
bucket at the wrong endpoint, so it tries to *create* one, and the failure
comes back as `client.MakeBucket: The location constraint differs from the
location you are trying to access`. That message is about the create attempt,
not about your repository — the real problem is one word in the URL.

restic's S3 backend reads the standard `AWS_*` variable names regardless of
provider — Hetzner is S3-compatible, not AWS.

The repository URL above is **path-style** (bucket after the host). Hetzner also
serves **virtual-hosted** style, and if the client and the endpoint disagree the
symptom is a bucket-not-found or a signature error rather than anything that
names the real problem. The alternative form, if the one above will not connect:

```
RESTIC_REPOSITORY=s3:https://baakhoff-lab-backup.fsn1.your-objectstorage.com
```

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
and worth reading — a handful is the ClickHouse merge churn described below,
a flood is something else:

```
journalctl -u restic-backup.service | grep -iE 'changed while|no such file'
```

## Object Lock, versioning, and the lifecycle rule

This bucket was created with Object Lock enabled, which turns versioning on
**permanently** — S3 allows suspending versioning, but not on a bucket where
Object Lock has ever been enabled.

That changes what pruning does. `restic forget --prune` repacks the repository
and deletes the pack files it no longer needs, but on a versioned bucket a
delete does not remove anything: it writes a *delete marker* and demotes the
real object to a **noncurrent version**, which is still stored and still
billed. Retention works exactly as configured and the repository still grows
without bound. `restic stats` would report a small repository while the bucket
kept getting larger — the two numbers measure different things, and only the
bucket is on the invoice.

`lifecycle.json` in this directory is the fix. Two rules:

| Rule | Effect |
|---|---|
| `expire-noncurrent-versions` | permanently deletes a version 30 days after it became noncurrent, and cleans up multipart uploads abandoned for 7 days |
| `expire-delete-markers` | removes delete markers once the last version beneath them is gone |

30 days is a deliberate margin, not a minimum. It is how long a mistake stays
reversible: a bad `forget` that drops snapshots it should have kept can be
undone from the noncurrent versions within that window. The cost of the margin
is a month of pruned data still sitting in the bucket, which at this repository
size is noise against the included terabyte.

The second rule matters less than it looks — delete markers are zero-byte — but
without it they accumulate forever, and every `restic` operation lists the
bucket.

**Do not copy the example policy from Hetzner's documentation.** It contains an
`"Expiration": {"Days": 90}` clause alongside the noncurrent rule. That clause
applies to *current* objects: pointed at a restic repository it would delete
live pack files after 90 days and destroy the backup. `lifecycle.json` has no
`Expiration.Days` for exactly that reason. Nothing in this policy may ever
expire a current version.

### Check the lock configuration first

A lifecycle rule cannot delete a version that is under an active Object Lock
retention — the lock wins, and lifecycle simply retries until it lapses. So the
rule's usefulness depends on whether the bucket carries a *default retention*
in addition to having Object Lock enabled:

```
aws s3api get-object-lock-configuration \
  --bucket baakhoff-lab-backup \
  --endpoint-url https://fsn1.your-objectstorage.com
```

`ObjectLockEnabled: Enabled` with **no** `Rule` block means no default
retention: nothing is actually immutable, versioning is the only real effect,
and the lifecycle rule reclaims space normally. If a `DefaultRetention` block is
present, `NoncurrentDays` must be at least its `Days` value or the rule is a
no-op until each lock expires.

This bucket returns the first form — enabled, no default retention — which is
what the console's create-time toggle produces on its own.

### Apply it

Hetzner has no console UI for lifecycle rules; this is the API or nothing. The
AWS CLI reads the same `AWS_*` variables the backup already uses, so sourcing
the existing env file is enough — but it needs a region, which is not in that
file:

```
sudo snap install aws-cli --classic
```

Not `apt install awscli` — that package has been dropped from the Ubuntu
archive, because v1 is end-of-life upstream and v2 is not packaged for Debian
or Ubuntu. `apt` reports it as `has no installation candidate` rather than as
missing, which reads like a broken sources list and is not one. The snap is
AWS's own build of v2 and updates itself, the same argument used above for
preferring the distro `restic` to a downloaded binary. `--classic` is required;
the snap will not install without it.

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; \
  AWS_DEFAULT_REGION=fsn1 aws s3api put-bucket-lifecycle-configuration \
  --bucket baakhoff-lab-backup \
  --endpoint-url https://fsn1.your-objectstorage.com \
  --lifecycle-configuration file://lifecycle.json'
```

That path is relative to the working directory, so run it from this directory —
same convention as installing the units above. `file://` with a relative path is
a real trap here: the AWS CLI reports a missing file as a parse error rather
than as "no such file".

Sourcing rather than passing the keys as arguments keeps them out of `ps` and
out of shell history, the same reasoning as `restic init` above.

A successful put returns nothing at all. Read it back to confirm:

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; \
  AWS_DEFAULT_REGION=fsn1 aws s3api get-bucket-lifecycle-configuration \
  --bucket baakhoff-lab-backup \
  --endpoint-url https://fsn1.your-objectstorage.com'
```

This call replaces the whole configuration rather than merging into it, so
`lifecycle.json` is the complete desired state and editing the bucket means
editing this file and putting it again. It also has to be re-applied by hand if
the bucket is ever recreated — it is not part of `restic init`.

Whether it is working shows up as a bucket that stops growing after a prune,
not as anything in the restic logs. Lifecycle evaluation is asynchronous and
Hetzner does not document the interval, so give it a day before concluding
anything.

Nothing visible happens for the first month, and that is correct rather than
broken. A delete marker only becomes *expired* — and therefore reapable by the
second rule — once no versions remain beneath it, which cannot happen until the
first rule has aged those versions out at 30 days. The two rules run in that
order by construction. Counting delete markers the next morning and finding the
same number is the expected result:

```
sudo bash -c 'set -a; . /etc/restic/backup.env; set +a; \
  AWS_DEFAULT_REGION=fsn1 aws s3api list-object-versions \
  --bucket baakhoff-lab-backup \
  --endpoint-url https://fsn1.your-objectstorage.com \
  --query "length(DeleteMarkers)"'
```

## Known limitations

These are properties of the current setup, recorded so nobody rediscovers them
during a restore:

- **Crash-consistent, not atomic.** The backup walks the live filesystem, so
  databases inside the Incus containers are captured as if the power had been
  cut — recoverable by design, but a file can change mid-walk. A copy-on-write
  storage pool would make this atomic; this pool is `dir`. Full reasoning is in
  the header of `restic-backup.sh`.

  This is not theoretical. The very first run reported ten unreadable files,
  all of them ClickHouse MergeTree parts under
  `analytix-platform_ch_data`: ClickHouse merges parts continuously, so restic
  listed a directory and the entries were deleted before it could stat them.
  Those files are simply absent from that snapshot.

  For ClickHouse specifically that is the weakest point in this design. Parts
  are immutable and ClickHouse quarantines anything incomplete into
  `detached/` on startup, so a restore is expected to come up — but "expected
  to" is doing real work in that sentence, and the honest fix for a database
  is a database-native dump (`BACKUP TABLE`, `clickhouse-backup`) or an atomic
  filesystem snapshot, not a file walk.

- **restic exit code 3 is treated as success.** It means the snapshot was
  saved but some sources could not be read, which is the normal steady state
  here for the reason above. Reporting it as a failure would page every night
  and train you to ignore the alarm. The trade is that a run where a *lot* of
  files were unreadable still reports green — the journal is the only place
  that distinguishes ten files from ten thousand.
- **node01 can delete its own backups.** The credential in
  `/etc/restic/backup.env` has full access to the bucket, so a compromise of the
  machine is a compromise of the backup. Object Lock being enabled does not
  change this: without a default retention period nothing carries a retain-until
  date, and a Hetzner S3 key is project-scoped rather than bucket-scoped, so the
  key that writes the backups could bypass governance retention anyway. Breaking
  the link needs a bucket policy denying deletion to this key outside the
  `locks/` prefix, with pruning moved to a machine holding a different
  credential. Not configured.
- **No drift detection**, as above.
