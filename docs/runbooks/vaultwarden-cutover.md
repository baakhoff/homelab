# Moving Vaultwarden from node01 to the lab cluster

Vaultwarden is the only thing on node01 that cannot be rebuilt from git, a
registry or an upstream. Everything else there is a clone, an image or a
manifest; this is the vault.

The move is a **stop, copy, start** — not a live migration. Vaultwarden keeps
everything in one SQLite database, and copying that while a process is writing
to it is the torn-read problem its own backup script goes to lengths to avoid.
The cost is a few minutes of downtime, during which the vault is unreachable
and every Bitwarden client keeps working from its local cache.

Read the whole thing before starting. Steps 3 to 6 are one sitting.

## Why this is three commits and not three commands

Both clusters are reconciled by Flux, which reverts a hand-scaled Deployment
within a minute. `kubectl scale deploy/vaultwarden --replicas=0` on node01
would come back up on its own — and if that happened mid-copy, Vaultwarden
would start on top of a half-written database.

So each change of state is a commit. Slower, auditable, and it cannot be undone
by a reconcile loop at the worst moment.

The faster alternative, if you would rather do it in one sitting: `flux suspend
kustomization flux-system` on node01's cluster, do steps 3–6 with `kubectl`,
then resume. That suspends everything else on that cluster for the window,
which during a decommission is acceptable. The commit path below is the
default because it leaves a record.

## Before you start

- [ ] The lab cluster's backup runs and has produced snapshots
      (`clusters/lab/backup/README.md`, Verification). Moving the vault onto a
      cluster whose backup is unproven is the one ordering mistake here that
      cannot be walked back.
- [ ] The `restic-repo` Secret exists in the `vaultwarden` namespace on the lab
      cluster. Without it the volume is declared as a backup target and every
      run fails.
- [ ] You can reach both clusters: `kubectl --context <node01> get nodes` and
      `kubectl --context <lab> get nodes`. Context names below are written as
      `node01` and `lab`; use whatever yours are called.
- [ ] Take a manual restic snapshot on node01 first, tagged so retention never
      removes it. This is the rollback of last resort and it costs one command:

      ```
      ssh node01 'sudo bash -c "set -a; . /etc/restic/backup.env; set +a; \
        restic backup --tag keep --tag pre-cutover /var/lib/rancher/k3s/storage"'
      ```

## 1. Land the lab manifests, parked

Merge the PR that adds `clusters/lab/vaultwarden/`. The Deployment is at
`replicas: 0`, so this creates the namespace, the PVC and the Ingress and
starts nothing. The PVC binds immediately — `ceph-block` does not use
`WaitForFirstConsumer`, so the RBD image exists before anything mounts it.

```
kubectl --context lab -n vaultwarden get pvc
```

Expect `vaultwarden-data` `Bound`.

## 2. Confirm nothing is reachable yet

```
dig +short vault.lab.baakhoff.com
```

This must still answer with node01. The Ingress on the lab cluster exists but
no A record points at it, and the Deployment behind it is parked — two
independent reasons nothing is serving, which is the right number while a
password vault is mid-move.

## 3. Stop Vaultwarden on node01

Commit to `clusters/homelab/vaultwarden/deployment.yaml`:

```yaml
  replicas: 0
```

Wait for Flux, then confirm the pod is gone — the RBD/local-path volume must be
unmounted before it is read:

```
kubectl --context node01 -n vaultwarden get pods
```

**The vault is down from here until step 6.**

## 4. Copy the data

Helper pods on both sides, because a PVC with no consumer cannot be read into
or out of. Both run as root so tar can restore ownership; the lab side is
chowned afterwards.

Start a helper on node01:

```
kubectl --context node01 -n vaultwarden run vw-copy \
  --image=busybox:1.37 --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"vw-copy","image":"busybox:1.37","command":["sleep","3600"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"vaultwarden-data"}}]}}'
```

And one on the lab cluster, identical but for the context:

```
kubectl --context lab -n vaultwarden run vw-copy \
  --image=busybox:1.37 --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"vw-copy","image":"busybox:1.37","command":["sleep","3600"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"vaultwarden-data"}}]}}'
```

Record what you are about to copy, so step 5 has something to compare against:

```
kubectl --context node01 -n vaultwarden exec vw-copy -- \
  sh -c 'cd /data && find . -type f | sort | xargs sha256sum' > /tmp/vw-before.txt
wc -l /tmp/vw-before.txt
```

Then stream it across. tar rather than `kubectl cp`, which mangles symlinks and
has no useful failure mode on a partial transfer:

```
kubectl --context node01 -n vaultwarden exec vw-copy -- tar -C /data -cf - . \
  | kubectl --context lab -n vaultwarden exec -i vw-copy -- tar -C /data -xf -
```

## 5. Verify the copy before starting anything

```
kubectl --context lab -n vaultwarden exec vw-copy -- \
  sh -c 'cd /data && find . -type f | sort | xargs sha256sum' > /tmp/vw-after.txt

diff /tmp/vw-before.txt /tmp/vw-after.txt && echo "IDENTICAL"
```

`IDENTICAL` is the gate. Anything else — stop, and do not proceed to step 6.
The vault on node01 is untouched and step 3 is reversible by reverting its
commit.

Then fix ownership. `fsGroup: 1000` on the Deployment sets the GROUP on the
volume's contents but not the owner, and these files arrived carrying node01's
uids:

```
kubectl --context lab -n vaultwarden exec vw-copy -- chown -R 1000:1000 /data
```

Clean up both helpers:

```
kubectl --context node01 -n vaultwarden delete pod vw-copy
kubectl --context lab     -n vaultwarden delete pod vw-copy
```

## 6. Start it on the lab cluster

Commit to `clusters/lab/vaultwarden/deployment.yaml`:

```yaml
  replicas: 1
```

Wait for the pod to become ready, then check it before any DNS change. The
Service is reachable without the Ingress:

```
kubectl --context lab -n vaultwarden port-forward svc/vaultwarden 8080:80
```

Open `http://localhost:8080`, log in, and confirm the vault decrypts and the
entries are there. A vault that loads but shows nothing means the database
copied and the RSA keypair did not.

## 7. Cut the name over

Add an explicit A record for `vault.lab.baakhoff.com` pointing at the lab
cluster's ingress-nginx address. The wildcard `*.lab.baakhoff.com` stays on
node01; a specific record beats it, so only this one name moves.

```
dig +short vault.lab.baakhoff.com
```

**Rollback at this point is deleting that record.** node01 still holds a valid
certificate for the name and its Vaultwarden is intact at `replicas: 0` —
reverting step 3's commit brings it back exactly as it was. That reversibility
is why node01's copy is not deleted in the same change.

Check from a phone on mobile data as well as from the desk: Pi-hole answers for
both the house and the tailnet, so a record that works in one place and not the
other is a real and common outcome.

## 8. Confirm the backup picks it up

Do not wait for 02:00:

```
kubectl --context lab -n backup create job --from=cronjob/backup vw-first-backup
kubectl --context lab -n backup logs -f job/vw-first-backup
```

Expect `vaultwarden/vaultwarden-data` to snapshot, clone and back up before the
two monitoring volumes — it is first in `BACKUP_TARGETS` for exactly this
reason.

**The vault is not migrated until this passes.** Until then it exists in one
place again, which is where it started.

## 9. Only then, remove it from node01

A separate commit, deliberately later than everything above: delete
`clusters/homelab/vaultwarden/`. Flux prunes the Deployment, the Service, the
Ingress **and the PVC**, and the PVC is the data.

Leave at least one successful nightly backup on the lab cluster between step 8
and this. There is no hurry, and the only thing this step buys is tidiness.

## If it goes wrong

| Symptom | What it means |
|---|---|
| Pod CrashLoopBackOff, permission errors in `logs --previous` | the chown in step 5 was skipped |
| Vault loads, no entries | `db.sqlite3` copied, `rsa_key*` did not — re-check the diff from step 5 |
| Web vault loads but login fails | DNS points at the lab cluster while the Deployment is still parked, or `DOMAIN` does not match the URL you are visiting |
| Passkeys/hardware keys rejected | `DOMAIN` mismatch. It must be `https://vault.lab.baakhoff.com` on both clusters and unchanged by the move |
| Backup job fails on the vaultwarden target | the `restic-repo` Secret is missing from the `vaultwarden` namespace |
