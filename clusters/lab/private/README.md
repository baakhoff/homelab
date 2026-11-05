# private

A second Flux source: the private repository `baakhoff/homelab-private`,
applied to this cluster beside this one. It holds what is better not
published, and plugs into the shared pieces here through a few named
places, each optional - absent, they are simply empty:

| Place | Here | What the private source puts there |
|---|---|---|
| Backup | `BACKUP_TARGETS_EXTRA` in `clusters/lab/backup/cronjob-backup.yaml` | the ConfigMap `backup-extra` in `backup`: more volumes, backed up after this repository's own, each with the RoleBinding and `restic-repo` Secret any target needs |
| Warehouse sources | `SOURCES_EXTRA` in `clusters/lab/data/clickhouse-schema.yaml` | the ConfigMap `clickhouse-extra` in `data`: more Kafka topics and raw tables |
| Ingest and dbt | `/opt/airflow/extra` in Airflow's scheduler and DAG processor (`clusters/lab/airflow/helmrelease.yaml`) | the ConfigMap `airflow-extra` in `airflow`: `sources.json`, more ingest sources in the shape of `pipelines/dags/ingest.py`'s, and dbt models (`pipelines/dbt/dbt_project.yml`) |
| Ingest tokens | `extraEnvFrom` in the same HelmRelease | the Secret `airflow-extra` in `airflow` |

Network policies need no place of their own: they add up, so a policy from
the private source opens a door beside the ones here without touching them.

## What is here

| File | What |
|---|---|
| `source.yaml` | the GitRepository and the Kustomization that applies it |
| `deploy-key.sops.yaml` | the read-only deploy key Flux reads it with - **created by hand**, below |

## The deploy key

Made on the workstation, from the repo root. The private half goes into the
Secret and nowhere else; the public half becomes the repository's read-only
deploy key.

```bash
ssh-keygen -t ed25519 -N '' -C flux-private -f /tmp/flux-private
gh repo deploy-key add /tmp/flux-private.pub --repo baakhoff/homelab-private --title flux
flux create secret git private-repo --namespace flux-system \
  --url=ssh://git@github.com/baakhoff/homelab-private \
  --private-key-file=/tmp/flux-private --export > clusters/lab/private/deploy-key.sops.yaml
sops --encrypt --in-place clusters/lab/private/deploy-key.sops.yaml
rm -f /tmp/flux-private /tmp/flux-private.pub
```

## Handing objects over

Objects that move from this repository to the private one keep running, and
nothing that holds data can be pruned on the way, by two marks:

- **On the objects themselves.** Everything that moves, but the encrypted
  Secrets, carries `kustomize.toolkit.fluxcd.io/prune: disabled` in both
  repositories (a patch in its directory's `kustomization.yaml`; the backup
  RoleBinding has it written in). Flux never prunes an object so marked,
  whichever source applied it last.
- **On everything the private source applies** (`commonMetadata` in
  `source.yaml`), the Secrets included - for as long as it applied them last.
  A Secret pruned anyway is applied again by the private source within ten
  minutes; the pods using it have read it already.

The order, with the exact commands and the checks between the steps, is in
the private repository's `HANDOVER.md`, since it names what moves:

1. The PR that adds the private source is merged on its own - never the
   removal merged into its branch first.
2. The private Kustomization is Ready; flux-system is suspended; the private
   one is reconciled.
3. A check: everything that moves carries the mark.
4. The removal is merged here, then the private repository's own changes;
   the private Kustomization is reconciled and Ready again.
5. The check again, then flux-system is resumed.

flux-system resumed early by mistake prunes nothing that holds data; carry
on from step 3. `commonMetadata` comes out of `source.yaml` once nothing
else is being handed over; the marks on the objects stay in the private
repository on the namespaces and volumes, as a guard.
