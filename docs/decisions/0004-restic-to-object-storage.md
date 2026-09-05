# 0004 — restic to S3 object storage for backups

- Status: accepted
- Date: 2026-09-05

## Context

Until now the lab had no backups. Incus snapshots existed on both containers,
but they sit on the same NVMe as the data they protect: node01 is a single
ext4 root LV holding k3s state, containerd images, the Incus storage pool and
every local-path PVC together. One disk failure takes all of it.

That gap became urgent for a specific reason: a self-hosted password manager is
going to live here. Everything else on the machine is either reproducible or
merely inconvenient to lose. A password vault is neither.

Three things shaped the design.

**Most of the lab does not need backing up.** Everything under
`clusters/homelab/` is in git and on GitHub already. Flux reconstructs the
entire cluster from it given one secret. What is genuinely irreplaceable is
much smaller than the machine: two Incus containers (~58G), local-path PVC
data, and host configuration under `/etc`.

**The observability data is worth less than it costs.** Prometheus runs 15-day
retention and Loki 7-day, so both already delete themselves, and their storage
churns constantly — including them would have dominated the repository with
data nobody would ever restore.

**Backups are not the same tool as snapshots.** Snapshots answer "I broke it an
hour ago" in seconds. Off-site backups answer "the disk is dead" in hours. Both
are needed and neither substitutes for the other.

## Decision

**restic**, driven by a systemd timer on node01, writing to **Hetzner Object
Storage** (bucket `baakhoff-lab-backup`, Falkenstein), nightly, with a weekly
retention pass and integrity check.

Scope is **default-include with an exclude list**: everything under `/etc`,
`/var/lib/incus`, `/var/lib/rancher/k3s/server` and
`/var/lib/rancher/k3s/storage`, minus the Prometheus and Loki volumes and the
Incus snapshot directory. An include list was rejected because it fails by
silently missing whatever was added last month; the exclude form catches every
future service's PVC automatically.

Kubernetes API objects are **not** backed up. Git holds a better copy.

Recovery depends on four secrets that live **outside the lab** — the age key,
the restic repository password, the S3 credentials, and the vault's master
password. This is not optional bookkeeping: the password manager being
self-hosted means it cannot be part of its own recovery path.

### Alternatives considered

**Velero** is the Kubernetes-native answer and the more familiar one in
production. Rejected because it cannot see Incus, which is roughly 95% of the
payload here; because local-path offers no CSI snapshots, so it falls back to
node-agent file backup — kopia with extra steps; and because the API objects it
does capture are already in git.

**Borg** is excellent and compresses better on text, but is repo-and-SSH bound
and cannot speak object storage.

**rclone** is a sync rather than a backup: deletions propagate.

**Backblaze B2** was materially cheaper — roughly $0.30/month against Hetzner's
$7.99 flat base at this data size — and supports Object Lock in both governance
and compliance modes. Cost was explicitly weighed and judged not to be the
deciding factor at these amounts.

**A Hetzner Storage Box** is about half the price per terabyte with unlimited
traffic, and is the better fit for bulk data. It is not object storage: no S3
API and no Object Lock. Object storage was preferred for the lab's own backup;
bulk NAS data is a separate question with a separate answer.

**A Kubernetes CronJob** instead of a systemd timer was rejected: the job has to
run `incus` commands and read the host filesystem, so it would need a
privileged pod with hostPath mounts — more moving parts, in the very cluster
whose loss it is meant to survive.

## Consequences

**The backup is crash-consistent, not atomic.** It walks the live filesystem,
so the databases inside the Incus containers are captured as though the power
had been cut. Every engine involved survives that by replaying its
write-ahead log, so it is a supported starting point — but restic reads files
over several minutes, and a file can change mid-walk. Making it atomic requires
a copy-on-write storage pool, where an Incus snapshot is instant and free. This
pool is `dir`, where a snapshot is a full 58G copy — correct but too expensive
to take nightly. The imperfect version was shipped deliberately: without it, a
dead NVMe loses the workbench entirely.

**Object Lock makes versioning permanent, which makes pruning a no-op without a
lifecycle rule.** The bucket was created with Object Lock enabled, and a bucket
that has ever had it enabled cannot have versioning suspended again. Under
versioning, the deletes `restic prune` issues write delete markers instead of
freeing space, so the repository would have grown without bound while retention
appeared to work. A bucket lifecycle policy expiring noncurrent versions after
30 days is therefore load-bearing rather than housekeeping, and it lives in
`hosts/node01/backup/lifecycle.json` because Hetzner exposes lifecycle rules
only through the S3 API — there is no console for it, and nothing re-applies it
if the bucket is rebuilt.

**node01 can delete its own backups.** The credential in
`/etc/restic/backup.env` has full bucket access, so compromising the machine
compromises the backup. Enabling Object Lock did not close this: lock without a
default retention period sets no retain-until date on anything, and Hetzner's S3
credentials are project-scoped rather than bucket-scoped, so the key that writes
the backups can also bypass governance-mode retention. Actually breaking the
link needs a bucket policy that denies deletion to this key outside the `locks/`
prefix, with pruning moved to a machine holding a different credential. That is
not configured.

**These files are outside GitOps.** systemd units on the host are not
Kubernetes objects, so `hosts/node01/` is installed by hand and nothing detects
drift between the repo and the machine — unlike everything under
`clusters/homelab/`, where Flux reverts drift within minutes.

**Recovery point is up to 24 hours.** Acceptable for container and PVC data;
noted as coarse for a password vault, whose contents are small enough to
warrant a tighter schedule of its own.

**Restoring PVC data into a rebuilt cluster requires manual work.** local-path
directory names embed the PVC uuid, and a cluster rebuilt from git generates new
ones, so restored directories no longer match. The procedure is written down in
the recovery runbook.

**Backup failure is reported by absence.** The job pings healthchecks.io, which
raises the alarm when a ping fails to arrive — the same inversion already used
for the cluster's dead-man's switch, and the only design that catches a timer
that has silently stopped firing.
