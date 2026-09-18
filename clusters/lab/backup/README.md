# lab cluster backup

Nightly restic backup of the lab cluster's persistent volumes to Hetzner Object
Storage, driven by a CronJob. Weekly retention pass and integrity check
alongside it.

The reasoning that is shared with node01 — why restic, why object storage, why
Object Lock changes what pruning does, why the lifecycle policy exists — is in
[`hosts/node01/backup/README.md`](../../../hosts/node01/backup/README.md) and
[ADR 0004](../../../docs/decisions/0004-restic-to-object-storage.md). This file
covers only what is different here, which is most of the mechanism and none of
the principles.

## How it differs from node01

**It is reconciled by Flux.** node01's backup is a systemd timer installed by
hand, and its README names that as a real gap: nothing detects drift, so an
edit to the script on the box leaves the repo quietly wrong. Everything here is
a Kubernetes object, so Flux reverts drift within minutes.

**The backups are atomic.** `restic-backup.sh` on node01 opens by admitting it
walks a live filesystem, so a database is read over several minutes and what
lands in the repository is crash-consistent rather than atomic — and names the
fix it could not afford: snapshot a copy-on-write pool, back up the frozen
snapshot, delete it. RBD snapshots *are* copy-on-write, so that is exactly what
happens here.

**There is no SQLite dump step.** node01 needs SQLite's online-backup API
because its file walk copies `db.sqlite3`, `-wal` and `-shm` minutes apart and
can catch a set that does not belong together. A snapshot captures all three at
one instant — which is the power-cut case SQLite's WAL recovery is built for.
When Vaultwarden moves here it needs no special handling.

**It is a separate repository.** Same bucket, its own prefix, its own password
and its own retention. node01's repository becomes a frozen archive the day
that machine is switched off, rather than something this cluster keeps writing
into.

## How it works

The driver CronJob, per target volume:

1. creates a `VolumeSnapshot` of the source PVC and waits for `readyToUse`
2. creates a PVC cloned from that snapshot, sized from `status.restoreSize`
3. creates a Job that mounts the clone and runs `restic backup`
4. pulls the Job's output into its own log, then deletes all three

It needs three objects rather than one because a pod whose PVC does not exist
yet is never scheduled — the volume is bound before any container runs, so the
pod that creates the clone cannot be the pod that mounts it.

The snapshot, the clone and the Job all live in the **source volume's**
namespace, because a `VolumeSnapshot` must share a namespace with its PVC, a
clone must share one with its snapshot, and a pod can only mount a PVC in its
own namespace. Only the orchestration is central.

## What is backed up

`monitoring/kube-prometheus-stack-grafana` and the Alertmanager claim. That is
all, and the exclusions are node01's own arguments from
[`restic-excludes.txt`](../../../hosts/node01/backup/restic-excludes.txt)
applied to this cluster:

| Volume | Why not |
|---|---|
| Prometheus | 15d retention and an 8GB cap, so it already deletes itself; its blocks churn constantly and losing it costs history, not capability |
| Loki | same argument at 7d, and its logs only start when Alloy was deployed |
| `agents/*` | a git clone, a login and caches. Nothing on it is an original |

**The first volume here genuinely worth protecting arrives with Vaultwarden.**
This exists now so that it is proven before then, not because Grafana's
dashboards are precious. Adding a volume is one entry in `BACKUP_TARGETS`, a
`RoleBinding` in its namespace, and a copy of the Secret below.

## Install

### 1. The credentials

The Secret is **not in git** and cannot be — it is the one thing here that is
not reconstructible. It must exist in `backup` (for the prune job) and in every
namespace named in `BACKUP_TARGETS` (for the restic Jobs), because Secrets do
not cross namespaces.

Shape — real values go here and nowhere else:

```
RESTIC_REPOSITORY=s3:https://fsn1.your-objectstorage.com/baakhoff-lab-backup/lab
RESTIC_PASSWORD=<a NEW password, not node01's>
AWS_ACCESS_KEY_ID=<Hetzner S3 access key>
AWS_SECRET_ACCESS_KEY=<Hetzner S3 secret key>
HC_URL=<healthchecks.io ping URL, nightly lab backup>
HC_PRUNE_URL=<healthchecks.io ping URL, weekly lab prune>
```

`/lab` on the end of the repository URL is what makes this a separate
repository inside the existing bucket. The bucket's `lifecycle.json` already
applies to the whole bucket, so nothing needs re-applying there.

`RESTIC_PASSWORD` must also exist **outside this cluster**. A backup whose
password only lives in the thing it protects is not a backup.

Create it once per namespace and encrypt in place:

```
kubectl create secret generic restic-repo \
  --namespace backup \
  --from-env-file=/path/to/backup.env \
  --dry-run=client -o yaml > clusters/lab/backup/restic-repo.sops.yaml

sops --encrypt --in-place clusters/lab/backup/restic-repo.sops.yaml
```

Repeat with `--namespace monitoring` into
`clusters/lab/backup/restic-repo-monitoring.sops.yaml`. The two files are the
same secret differing only in `metadata.namespace`, which is the same pattern
the cert-manager Cloudflare token already follows across the two clusters.

Delete the plaintext env file afterwards. The pre-commit hook asserts every
staged `*.sops.yaml` is actually encrypted, but only if
`git config core.hooksPath .githooks` has been run in your clone.

### 2. Initialise the repository

Run once, ever. On an already-initialised repository it fails harmlessly.

```
kubectl -n backup run restic-init --rm -it --restart=Never \
  --image=restic/restic:0.19.1 \
  --overrides='{"spec":{"containers":[{"name":"restic-init","image":"restic/restic:0.19.1","args":["init"],"envFrom":[{"secretRef":{"name":"restic-repo"}}]}]}}'
```

### 3. Confirm the target names

The Grafana claim's name is predictable. The Alertmanager one is generated by
the prometheus-operator from the StatefulSet and its volumeClaimTemplate, is
about 98 characters long, and is sensitive to the chart version:

```
kubectl -n monitoring get pvc
```

If either differs from `BACKUP_TARGETS` in `cronjob-backup.yaml`, fix the
manifest. The driver fails loudly on a name it cannot resolve rather than
skipping it — a backup that silently omits the volume it was asked about is the
worst outcome available, because everything stays green.

### 4. Run it once, watched

```
kubectl -n backup create job --from=cronjob/backup backup-manual
kubectl -n backup logs -f job/backup-manual
```

## Verification

A snapshot listing is the only thing that proves the backup exists. A completed
Job proves a container exited zero, which is not the same claim.

```
kubectl -n backup run restic-check --rm -it --restart=Never \
  --image=restic/restic:0.19.1 \
  --overrides='{"spec":{"containers":[{"name":"restic-check","image":"restic/restic:0.19.1","args":["snapshots"],"envFrom":[{"secretRef":{"name":"restic-repo"}}]}]}}'
```

Expect one snapshot per target per night, all with host `lab`, each with its
own path under `/data/<namespace>/<pvc>`.

## Restoring

There is no way to restore *into* a volume a running workload has mounted, so
the shape is always: scale the workload down, restore into a fresh PVC, point
the workload at it.

1. **Scale the workload to zero** so the RBD image is unmapped.

2. **Create a PVC** of at least the original size, `storageClassName:
   ceph-block`.

3. **Run a Job** mounting that PVC at `/restore`, with `envFrom` the
   `restic-repo` Secret in that namespace, and args:

   ```
   restore latest --host lab --path /data/<namespace>/<pvc> --target /restore
   ```

   `--path` is what selects the right volume: every snapshot in this repository
   shares the host `lab`, so the path is the only thing distinguishing them.
   The files land at `/restore/data/<namespace>/<pvc>/`, mirroring the absolute
   path they were backed up from.

4. **Point the workload at the new claim** and scale it back up.

**This has not been rehearsed yet.** Until it has, this section is a plan
rather than a procedure, and the difference matters more here than anywhere
else in the repo.

## Known limitations

- **The restore path is untested**, as above. That is the highest-value next
  piece of work on this, ahead of adding more volumes.
- **No dead-man's switch on the cluster itself.** `HC_URL` catches a backup
  that stops running, but see the Watchdog note in
  `clusters/lab/monitoring/helmrelease.yaml` for the broader gap while node01
  still holds the only healthchecks.io check.
- **The cluster can delete its own backups.** The credential in the Secret has
  full access to the bucket, so a compromise of the cluster is a compromise of
  the backup — identical to node01's position and for the same reason: a
  Hetzner S3 key is project-scoped rather than bucket-scoped. Unchanged, and
  still not fixed.
- **A volume dropped from `BACKUP_TARGETS` keeps its snapshots forever**,
  because retention groups by path and nothing adds to that group again. Often
  what you want; nothing will remind you.
- **The driver image is 300MB of Alpine with kubectl, helm, kustomize and the
  AWS CLI in it**, because both official kubectl images are distroless and have
  no shell to run the driver in. An image built in this repo holding exactly
  kubectl and restic would replace it and let the driver and the restic Jobs
  share one image.
