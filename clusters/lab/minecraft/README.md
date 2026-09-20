# minecraft

A Java Edition server for the household. Vanilla, one world, reachable from the
house and from the tailnet, and from nowhere else.

## What is here

| File | What |
|---|---|
| `deployment.yaml` | the server: `itzg/minecraft-server`, one replica, `Recreate`, non-root |
| `pvc.yaml` | the world, 20Gi on `ceph-block` |
| `service.yaml` | `type: LoadBalancer` on 25565, served by k3s ServiceLB on every node |

No Ingress, because Minecraft is not HTTP. No Secret, because the only credential
the server has — its RCON password — is generated at each start and never leaves
the pod. The Homepage tile is a hand-written entry in the Homepage ConfigMap,
since with no Ingress there is nothing for annotation discovery to find. It
carries the one widget on that page that needs no API key: a server-list ping
that shows whether the server is up, who is on, and which Minecraft version the
world is running - the number that matters when reading the paragraph on
restarts below. Editing that ConfigMap needs a Homepage restart to show, for the
reason given in the Homepage Deployment.

## Reaching it

ServiceLB binds 25565 on all three node addresses, so any of `node02.lab`,
`node03.lab` or `node04.lab` works as a server address. The friendlier name is a
**Local DNS Record** in Pi-hole, which resolves from the house and from the
tailnet alike:

| Name | Address |
|---|---|
| `mc.lab` | `192.168.68.102` |

One node, not three. A client resolves a name to one address and connects to
it, so a round-robin record would not survive that node being down either — it
would just fail one time in three instead of always. When node02 is down,
players type another node's name; that is the honest behaviour for a cluster
with no floating address, and the same trade the ingress hostnames already make
in Cloudflare.

Nothing is forwarded from the internet, and this changes nothing about that.
Anyone who should play from outside the house joins the tailnet.

## Operating it

The admin console is RCON, and RCON is reachable only from inside the pod:

```
kubectl -n minecraft exec deploy/minecraft -- rcon-cli list
kubectl -n minecraft exec deploy/minecraft -- rcon-cli op <player>
kubectl -n minecraft exec deploy/minecraft -- rcon-cli say saving in a minute
```

`rcon-cli` reads the generated password from the running container, which is
why nothing needs to be looked up.

**The same console from a browser is Headlamp**, at
[headlamp.lab.baakhoff.com](https://headlamp.lab.baakhoff.com): open the
`minecraft` pod, its *Logs* tab is the live server log, and *Terminal* is a
shell in the container where `rcon-cli` on its own drops into the interactive
console. Sign in with a token that carries exec rights — the one your
kubeconfig uses — since Headlamp's own ServiceAccount is bound to `view` and
deliberately cannot exec.

That is the admin page, by decision rather than by omission. The web console
usually reached for here, rcon-web-admin, has had no commit since June 2020,
ships on a Node 12 base that went end-of-life in 2022, and runs as root; a
dead process with a login page is the wrong thing to add to a repo that pins
and bumps everything else. The full panels — Crafty, Pterodactyl, PufferPanel
— want to own the Java process and would replace this Deployment rather than
sit beside it. Headlamp already exists, is maintained, and gates the console
on cluster auth rather than on a second password. If scheduled restarts or an
in-browser file editor ever become wanted, Crafty is the path, and the world
volume moves across as is.

**A restart is a version change.** `VERSION: LATEST` is resolved when the
container starts, so any restart — an image bump merged from Renovate, a node
drain, a crash — may bring the world up on a newer Minecraft. That upgrade is
one-way. The Deployment comment says why the version floats anyway; the short
version is that the clients float and a vanilla server rejects newer clients.

**Changing a server setting** is an env var on the Deployment; the image
rewrites `server.properties` from its environment at every start, so editing
the file on the volume does not stick. The full list is the image's
documentation, under *Server properties*.

## Backup — not yet, and in this order

The world is the only thing here that is not reconstructible. It is not in the
nightly backup yet because that takes three things, and one of them cannot come
from this repository:

1. **The `restic-repo` Secret in the `minecraft` namespace.** Same values as the
   other copies, differing only in `metadata.namespace`; the backup README has
   the exact commands. Encrypt it into
   `clusters/lab/backup/restic-repo-minecraft.sops.yaml`.
2. **The `RoleBinding`** — already in `clusters/lab/backup/rbac.yaml`, landed
   with the server. Harmless ahead of time: it grants the driver rights in a
   namespace it has no target in yet.
3. **`minecraft/minecraft-data` in `BACKUP_TARGETS`** in
   `clusters/lab/backup/cronjob-backup.yaml`. **Last**, and in a commit after
   the Secret has reconciled. The driver checks for the Secret before it
   snapshots anything and fails the run — the whole run, heartbeat included —
   on a target whose Secret is missing.

What that backup will be: an RBD snapshot of the volume, taken while the server
runs, so it is a crash-consistent copy — the same as every other target, as the
backup README says plainly. Minecraft is written to survive exactly that, and
saves every chunk on its own every few minutes. If a restore ever comes back
with a region file the server refuses, the fix worth building is an RCON
`save-all` immediately before the snapshot; nothing here does that today.
