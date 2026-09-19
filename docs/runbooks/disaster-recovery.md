# Disaster recovery

How to get the lab back from nothing.

This page is deliberately in the public repo rather than in local notes. Its
entire value is being reachable when the workstation, the cluster and everything
on them are gone — from a phone, in a hotel, on someone else's laptop. It
contains no secrets, only an order of operations.

**Do this from the workstation.** The agent pods run *in* the cluster being
recovered, including the one that edits this repository, so none of them is
available when it matters. See
[agent pods](agent-pods.md#the-pod-that-edits-this-repo-runs-in-this-cluster).

---

## Step 0 — the emergency kit

**Nothing below works without these.** They live outside the lab, in a cloud
password manager and on paper, because the self-hosted vault is one of the
things being recovered. You cannot restore a password manager with a password
manager.

| What | Why it is unrecoverable without it |
|---|---|
| age private key | Decrypts every `*.sops.yaml` in this repo. Without it Flux comes up healthy and decrypts nothing |
| restic password — **lab repository** | The backup is ciphertext. There is no reset |
| restic password — **node01 archive** | A different repository with a different password. Only needed for anything predating the move off that machine |
| S3 access key + secret | Needed to reach the bucket at all |
| Vaultwarden master password | The vault is end-to-end encrypted; the server never had the plaintext |

Plus account access for GitHub, Cloudflare, Hetzner, Tailscale and
healthchecks.io. Most are email-recoverable — which only helps if your email is
reachable without the lab.

The test for anything else you are tempted to store in the vault:
**if all three nodes are bricks, can I still get this?**

---

## What survives on its own

Everything under `clusters/lab/` — every manifest, HelmRelease, Ingress, RBAC
rule, alert rule and dashboard — is in git, on GitHub, and needs no backup.
Flux reconstructs the cluster from it.

What is *not* in git, and therefore what the backup and the kit exist for:

- **Volume contents.** Ceph replicates each block three ways, which survives a
  node but not a cluster. The nightly restic run is the copy that leaves the
  building.
- **The restic credentials Secret.** Deliberately not in git, and not
  reconstructible — see [`clusters/lab/backup/`](../../clusters/lab/backup/README.md).
- **The age key**, which is in the kit.

Agent volumes are excluded from backup on purpose: a git clone, a login and
caches. Nothing on one is an original.

---

## Scenario A — the whole cluster is gone

### A1. Three base systems

Ubuntu Server 24.04 LTS on each, per
[node bring-up](node-bring-up.md) — hostnames `node02`/`node03`/`node04`,
static addressing, swap off, Tailscale joined.

**Create the Ceph OSD volume before Kubernetes exists.** Every OSD in
[`cephcluster.yaml`](../../clusters/lab/rook-ceph/cephcluster.yaml) names
`/dev/ubuntu-vg/cephosd` explicitly, and Rook will not invent it: an empty
logical volume of that name must exist in `ubuntu-vg` on each node. Rook refuses
a device that carries a filesystem, so it must be raw — and if it is missing
entirely, the symptom is an OSD that never appears rather than an error naming
the volume.

### A2. Prove you can read the backup *before* anything else

restic is a single binary and needs no cluster. From the workstation, with the
lab repository's credentials from the kit — variable names are in
[`clusters/lab/backup/`](../../clusters/lab/backup/README.md):

```
restic snapshots --host lab
```

A snapshot listing means the credentials, the password and the bucket are all
correct. Find that out now, not after two hours of rebuilding.

### A3. Install k3s — node02 first

Three servers with embedded etcd. `--disable traefik` is **not optional**:
ingress-nginx comes from Flux and k3s's bundled Traefik would fight it for ports
80 and 443.

```
curl -sfL https://get.k3s.io | sh -s - server \
  --cluster-init \
  --node-ip 192.168.68.102 \
  --disable traefik \
  --secrets-encryption \
  --tls-san 192.168.68.102 --tls-san 192.168.68.103 --tls-san 192.168.68.104 \
  --tls-san node02.laperm-map.ts.net \
  --tls-san node03.laperm-map.ts.net \
  --tls-san node04.laperm-map.ts.net \
  --tls-san k8s.lab --tls-san 192.168.68.10
```

Then node03 and node04, each with its own `--node-ip`, joining the first:

```
curl -sfL https://get.k3s.io | K3S_TOKEN=<token from node02> sh -s - server \
  --server https://192.168.68.102:6443 \
  --node-ip 192.168.68.103 \
  --disable traefik \
  --secrets-encryption \
  --tls-san 192.168.68.102 --tls-san 192.168.68.103 --tls-san 192.168.68.104 \
  --tls-san node02.laperm-map.ts.net \
  --tls-san node03.laperm-map.ts.net \
  --tls-san node04.laperm-map.ts.net \
  --tls-san k8s.lab --tls-san 192.168.68.10
```

The token is at `/var/lib/rancher/k3s/server/token` on node02.

**Do not try to restore an etcd snapshot.** Rebuilding from git is the supported
path here and the reason the repo exists. An etcd restore additionally needs the
*original* cluster token and, because of `--secrets-encryption`, the original
encryption key from `/var/lib/rancher/k3s/server/cred/` — neither of which is in
the kit. A restore without them produces a cluster whose Secrets cannot be
decrypted, which looks like a working cluster full of broken workloads.

### A4. Apply the `sops-age` secret BY HAND, before Flux exists

```
kubectl create namespace flux-system
kubectl create secret generic sops-age -n flux-system \
  --from-file=age.agekey=<path to the key from the kit>
```

The filename must end in `.agekey` — that suffix is what kustomize-controller
scans for.

**Skip this and Flux installs cleanly, syncs happily, and fails to decrypt every
secret in the repo with errors that mention neither age nor this omission.** It
is the single most confusing failure mode in the whole rebuild.

### A5. Bootstrap Flux

```
flux bootstrap github --owner=baakhoff --repository=homelab \
  --branch=main --path=clusters/lab --personal
```

Then wait. Flux installs Rook-Ceph and its CSI drivers, the snapshot controller,
cert-manager and ingress-nginx, kube-prometheus-stack and Loki, Headlamp,
Homepage, Vaultwarden, epicurus and the agent pods.

Ceph first, in practice: nothing with a PVC starts until `ceph-block` exists and
an OSD is up on each node. `kubectl -n rook-ceph get cephcluster` reaching
`HEALTH_OK` is the gate everything else waits behind.

### A6. Re-create the restic Secret

Not in git, and needed in `backup` plus every namespace named in
`BACKUP_TARGETS`, because Secrets do not cross namespaces. The procedure is in
[`clusters/lab/backup/`](../../clusters/lab/backup/README.md). Until it exists
the nightly run fails fast, which is deliberate — a backup that silently does
nothing is worse than one that complains.

### A7. Restore the volumes

The mechanics are in
[`clusters/lab/backup/`](../../clusters/lab/backup/README.md) and are not
duplicated here. The shape: restore into a **fresh** PVC, then swap the workload
onto it — there is no way to restore into a volume a running pod has mounted.

**Count what came back before trusting it.** A `--path` that does not match
restores nothing and exits **zero**, so a silent no-op is indistinguishable from
success. That check is the whole reason the read path was rehearsed before
Vaultwarden's data was ever moved.

Prometheus and Loki are not in the backup at all — 15d and 7d retention meant
they were already deleting themselves. They start empty and refill. That is the
intended outcome, not a failed restore.

### A8. DNS and the certificate

`*.lab.baakhoff.com` resolves to all three nodes as DNS-only A records.
cert-manager requests a fresh wildcard via DNS-01 automatically. Let's Encrypt
rate-limits duplicate certificates to five per week for an identical name set,
so repeated rebuilds hit that before anything else.

---

## Scenario B — one node is gone

The cheapest scenario, and the reason the pool replicates three ways: Ceph
serves from the surviving two while the third is rebuilt, and pods reschedule on
their own. A ReadWriteOnce image is mapped by one node at a time, so a pod whose
node **vanished** stays `Terminating` for roughly six minutes while the node is
marked unreachable and the volume is force-detached. Waiting is correct — the
alternative is two writers on one filesystem.

Rebuild the node per A1, **including the empty `cephosd` volume**, then rejoin
it with the A3 joining-server command and its own `--node-ip`. Rook creates a
fresh OSD and Ceph backfills onto it. Nothing is restored from restic.

---

## Scenario C — a workload lost its data

Cluster is healthy; one volume is empty or corrupt. Scenario A7 without the
rebuild: restore into a fresh PVC, verify the file count, swap the workload
over. Only the swap needs downtime.

---

## Scenario D — one file

```
restic snapshots --host lab
restic find <filename>
```

`restic mount /mnt/restic` browses every snapshot as a filesystem, which is
usually faster than guessing at snapshot ids. Worth running occasionally purely
as a drill — it costs five minutes and it is the only way to know the read path
works.

---

## Scenario E — the password vault

**Try the export first.** A password-protected export imported into any
Bitwarden client takes a minute and needs no lab, no cluster and no restic. Use
this scenario only when the export is stale or missing.

Then it is an ordinary Scenario C restore, and that is worth noticing: on node01
this was the most delicate procedure in the document. Its file walk copied
`db.sqlite3`, `-wal` and `-shm` minutes apart and could catch a set that did not
belong together, so the backup carried a separate SQLite online-backup dump and
restoring meant deleting the WAL by hand. A CSI snapshot captures all three at
one instant — the power-cut case SQLite's WAL recovery is built for — so the
dump, the WAL surgery and the two-copies table are all gone.

`rsa_key.pem` and the attachments live in the same volume and come back with it.
**Attachments are not in a Bitwarden export**, so for those the restic copy is
the only one.

---

## node01 — the archive

node01 ran the lab until its workloads moved to the three-node cluster; what it
held and how it was emptied is in [the lab over time](../history.md).

Its restic repository still exists in the bucket as a **frozen archive** with its
own password. Nothing writes to it. It is the only copy of anything that existed
only on that machine and was never carried across — so the password outliving
the laptop is what keeps the archive readable rather than owned-and-unreadable.

`clusters/homelab/` and [`hosts/node01/`](../../hosts/node01/backup/README.md)
describe a machine that no longer runs anything; they are kept for the reasoning,
not as instructions.

---

## Scenario F — exitnode (the Pi) is gone

The Pi holds nothing worth restoring. What it holds is the house's DNS, and
the symptom of losing it is that nothing resolves while the internet is
otherwise fine — every device, at once.

1. **Give the house its names back first.** Router → DHCP → DNS: set the
   field back to automatic. Clients pick it up at the next lease renewal;
   toggling Wi-Fi forces one. Two minutes, no lab needed.
2. **Tailnet devices** using the global nameserver override lose DNS wherever
   they are. Tailscale console → DNS → switch **Override DNS servers** off
   until the Pi is back.
3. **Rebuild** from a blank card with the [Pi runbook](pi-exitnode.md).
   Nothing is restored; the router's DHCP reservation keeps the address, and
   the allowlist is recreated from the query log as things break.
4. Point the router's DNS field back at the Pi **last**, after the rebuilt Pi
   has answered queries for a while from where it lives.

Two things go with it that are not DNS, and neither is urgent. Remote
**Wake-on-LAN** stops working — magic packets are broadcasts and the Pi is the
only always-on Linux host on the wired segment that can send them; the nodes'
power buttons still work. And the **jump host** into LAN-only devices goes with
it: the switch's web UI and the nodes stay reachable from the LAN itself, just
not from the tailnet, until the subnet route is back.

---

## What this does not cover

- **Anything created after the last nightly run.** The window is up to 24
  hours.
- **The workstation.** Its kubeconfig is regenerated from any server node's
  `/etc/rancher/k3s/k3s.yaml`, with the address swapped for the node's own; the
  age key is in the kit; projects are in git. Nothing else there is backed up by
  this — which includes the local checkouts and working state of every project
  an agent pod holds a copy of.
- **Tailscale, Cloudflare and healthchecks.io state.** All reconstructed by
  logging in — hence account access being part of the kit.
- **A restore nobody has practised.** A backup that has never been restored is
  a hypothesis. Scenario D costs five minutes and is worth running
  occasionally; Scenario A is worth doing once, deliberately, on scratch
  hardware.
