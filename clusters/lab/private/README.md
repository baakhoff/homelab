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

The order:

1. **Merge the PR that adds the private source on its own.** Never merge the
   PR that removes the objects into its branch first: GitHub moves that PR
   onto `main` once this one's branch is deleted.
2. `flux get kustomization private` shows Ready, at the private repository's
   newest commit.
3. `flux suspend kustomization flux-system`, then `flux reconcile
   kustomization private --with-source`.
4. **The check.** Every line must end in `disabled`:

   ```bash
   C='-o custom-columns=KIND:.kind,NAME:.metadata.name,BY:.metadata.labels.kustomize\.toolkit\.fluxcd\.io/name,PRUNE:.metadata.annotations.kustomize\.toolkit\.fluxcd\.io/prune'
   ```

5. Merge the removal PR, then the private repository's warehouse PR, and
   `flux reconcile kustomization private --with-source` again; it shows
   Ready. The private repository's ConfigMaps and Secret are there:
   `kubectl -n backup get cm backup-extra`, `kubectl -n data get cm
   clickhouse-extra`, `kubectl -n airflow get cm,secret airflow-extra`.
6. The check of step 4 again, then `flux resume kustomization flux-system`.
   pvc,deploy` list what they listed before.

flux-system resumed early by mistake prunes nothing that holds data; carry
on from step 3. `commonMetadata` comes out of `source.yaml` once nothing
else is being handed over; the marks on the objects stay in the private
repository on the namespaces and volumes, as a guard.
