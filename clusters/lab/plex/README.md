# Plex

[Plex Media Server](https://www.plex.tv): the films and series on the NAS,
played on the TVs, streaming sticks, phones, the gaming PC and in the
browser. What a device cannot play as it is, Plex converts on the fly, on
the node's Intel graphics.

At <https://watch.lab.baakhoff.com/web>, and on Homepage under Everyday →
Play. The apps find it by themselves once signed in.

## How login works

**A plex.tv account, not Pocket ID.** The server is claimed by the owner's
plex.tv account, and every app signs in with one; no Plex app could get
through the oauth2-proxy gate, and Plex has no other login. With Vaultwarden
it is the one exception to Pocket ID in the lab (`clusters/lab/pocket-id/`).

Who may watch is decided on plex.tv: the owner's account, and whoever the
owner adds to Plex Home or shares the libraries with. Nobody else gets in.

**Family and friends watch from their own homes through Plex's Relay**, with
no port open on the router. The server keeps an outbound connection to
Plex's relay, and an app that cannot reach the server directly streams
through it, encrypted. The price is bandwidth: 2 Mbps a stream with Plex
Pass, 1 Mbps without - about 720p - and Plex shrinks the video to fit. In the
house and on the tailnet the apps connect directly, at full quality.

## What is here

| File | What |
|---|---|
| `namespace.yaml` | the namespace, at Pod Security `baseline` |
| `deployment.yaml` | Plex, with the GPU, its database volume, the films read-only, and RAM for transcoding |
| `pvc.yaml` | the database volume on Ceph, and the NAS share `tank/media`, read-only, through csi-driver-nfs |
| `networkpolicy.yaml` | ingress-nginx, Airflow's scheduler and Seerr in |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |
| `service.yaml`, `ingress.yaml` | `watch.lab.baakhoff.com`, with the Homepage tile |

The GPU comes from Intel's device plugin, `clusters/lab/intel-gpu-plugin/`.

## Setup, in this order

Steps 1 to 3 come before the merge; step 3's Secret has to be on the
branch, or the backup fails its whole nightly run.

**1. The nodes have the GPU.** From the workstation:

```
for n in node02 node03 node04; do ssh $n 'hostname; ls -l /dev/dri'; done
```

Each lists `card0` (or `card1`) and `renderD128`. Without them the device
plugin offers no GPU and Plex waits in Pending.

**2. The NAS.** In TrueNAS:

- *Credentials → Groups*: add `media`. *Credentials → Users*: add `media`,
  primary group `media`, password disabled, shell `nologin`, no SMB. Its UID
  and its group's GID must be `PLEX_UID` and `PLEX_GID` in
  `deployment.yaml`, 3001 and 3002 here; `id media` on the NAS shows both.
- *Datasets → tank/media → Permissions → Edit*: owner user and group
  `media`, applied to the children.
- *Shares → NFS → Add*: path `/mnt/tank/media`; networks
  `192.168.68.102/32`, `192.168.68.103/32` and `192.168.68.104/32`; under
  Advanced Options, Mapall user and group `media`, Maproot empty.
- The two library folders, over SSH:

```
sudo install -d -o media -g media /mnt/tank/media/films /mnt/tank/media/series
```

Check with `sudo cat /etc/exports`: the media line shows the three addresses,
each with `all_squash,anonuid=3001,anongid=3002`.

**3. The backup's restic credentials**, as the backup README describes:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: plex/' \
  > clusters/lab/backup/restic-repo-plex.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-plex.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-plex.sops.yaml
```

The `grep` must print `namespace: plex` before you encrypt. Commit and push.

**4. Claim the server**, right after the merge, once `kubectl -n plex get
pods` shows it ready. A new server can be claimed only from its own
network, which a port-forward is:

```
kubectl -n plex port-forward svc/plex 32400:32400
```

Open <http://localhost:32400/web>, sign in with your plex.tv account, name
the server `lab`, and add two libraries: **Films** at `/data/films` and
**Series** at `/data/series`.

**5. Settings**, still over the port-forward (Settings → the server):

| Where | Setting |
|---|---|
| Network | *Custom server access URLs*: `https://watch.lab.baakhoff.com:443` - the address the apps are told to use |
| Network | *LAN Networks*: `192.168.68.0/22,10.42.0.0/16,100.64.0.0/10` - the house, the cluster's pods (every request arrives through ingress-nginx) and the tailnet, so no stream is treated as remote and squeezed |
| Network | *Enable Relay*: on - how family and friends outside the house and the tailnet reach it, capped at 2 Mbps a stream |
| Remote Access | disabled: nothing is forwarded from the internet. Away from home your own apps come in over Tailscale, everyone else's through Relay |
| DLNA | off |
| Transcoder | *Transcoder temporary directory*: `/transcode`; *Use hardware acceleration when available* and *Use hardware-accelerated video encoding*: on (Plex Pass) |
| Library | *Scan my library periodically*: every hour - changes on the NAS are not noticed by themselves over NFS; *Generate video preview thumbnails*: never - they grow the database by gigabytes per film |

Then the address works without the port-forward:
<https://watch.lab.baakhoff.com/web>.

**6. The warehouse's token.** Plex has no keys of limited scope, so
`ingest_plex` uses the server owner's own plex.tv token, read straight from
the server's settings into the Secret without being shown:

```bash
PT=$(kubectl -n plex exec deploy/plex -- sed -n 's/.*PlexOnlineToken="\([^"]*\)".*/\1/p' "/config/Library/Application Support/Plex Media Server/Preferences.xml")
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["PLEX_TOKEN"]' "\"$(printf %s "$PT" | base64 | tr -d '\n')\""
unset PT
```

Commit and push. Once Flux has applied it, restart the scheduler: `kubectl
-n airflow delete pod -l component=scheduler` (not `rollout restart`, which
Flux undoes). Until then `ingest_plex` fails, harmlessly. Signing out of all
devices on plex.tv replaces the token, and this step is repeated.

**7. The devices.** Install Plex on the TV, the stick, the phones and the
PC, and sign in with the plex.tv account - on a TV, through the code it
shows at plex.tv/link. The server appears by itself.

**8. Family and friends.** Each needs a free plex.tv account. Settings →
Manage Library Access → Grant Library Access: their email or username, the
server `lab`, the libraries. On their TV they sign in to their own account
and find `lab` among the shared servers. Watching away from the owner's home
needs Plex Pass on the owner's account, or a Remote Watch Pass on theirs.

The Deco's UPnP is off, so nothing in the house can open a port on the
router by asking.

## What reaches the warehouse

`ods.plex_libraries`: each library and when it was last scanned.
`ods.plex_plays`: every play from Plex's watch history - the film or the
series' episode, the account, the device and the time. The ods layer is
readable by the brand agent, so it can know what was watched; it has no way
to Plex itself.

## Things to know

- **Plex Pass is what turns the GPU on.** Without it the transcoding
  settings are greyed out and Plex converts on up to four CPU cores. Most
  films play directly on a modern TV or phone and never need converting.
- **The films are read-only to Plex.** It cannot delete or rename anything
  on the NAS, whatever its settings say. The download client, when it comes,
  writes into `tank/media` through a volume of its own.
- **Logins go through plex.tv.** If plex.tv is down, apps that are already
  signed in usually keep playing in the house; new sign-ins wait.
- **When the NAS is away, playback stops and resumes** with it: the share is
  mounted `hard`, as Immich's is. After a short power cut the NAS can stay
  off while the nodes come back: `ssh <user>@exitnode wake-nodes nas`.
- **Upgrades** are Renovate PRs for the image tag. Plex's own update offers
  in the web app do nothing here: the version is the image's.

## Backup

- **Plex's database volume** is in the cluster's nightly backup
  (`clusters/lab/backup/`): `plex/plex-config` - the library as Plex
  matched it, watch history and settings.
- **The films** are on the NAS, outside what the cluster backs up, and not
  copied anywhere else: what was downloaded can be downloaded again.
