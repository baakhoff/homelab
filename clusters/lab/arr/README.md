# Radarr, Sonarr and Prowlarr

Films and series that arrive by themselves. Pick a film in
[Radarr](https://radarr.video) or a series in [Sonarr](https://sonarr.tv);
they search the torrent sites through [Prowlarr](https://prowlarr.com),
hand the best release to qBittorrent (`clusters/lab/torrents/`), and when it
has downloaded, hard-link it into the NAS's library under a clean name.
Plex shows it on its next scan. Sonarr keeps following a series and fetches
each new episode.

| App | Address | Homepage |
|---|---|---|
| Radarr | <https://films.lab.baakhoff.com> | Everyday → Play |
| Sonarr | <https://series.lab.baakhoff.com> | Everyday → Play |
| Prowlarr | <https://indexers.lab.baakhoff.com> | Ops → Platform |
| qBittorrent | <https://torrents.lab.baakhoff.com> | Ops → Platform |

## How login works

The admin gate: Pocket ID, members of `lab-admins` only. The apps' own login
is set to `External`, trusting the gate, so there is one login and not two.
Their APIs still need each app's key. None of them has a phone app that
would need to get past the gate.

## How the files move

```
NAS tank/media, mounted at /data in qBittorrent, Radarr and Sonarr
├── downloads/        qBittorrent writes here, and keeps seeding from here
├── films/            Radarr hard-links finished films here      ─┐ Plex reads
└── series/           Sonarr hard-links finished episodes here   ─┘ these
```

A hard link is a second name for the same file on the same disk: the film
appears in the library instantly, takes no extra space, and the torrent goes
on seeding from `downloads/`. It works because all three mount the same
share at the same path. Everything on the share belongs to the NAS's
`media` user, which the share maps every client to.

## What is here

| File | What |
|---|---|
| `namespace.yaml` | the namespace, at Pod Security `baseline` |
| `radarr.yaml`, `sonarr.yaml`, `prowlarr.yaml` | each app with its Service and its database volume on Ceph |
| `flaresolverr.yaml` | a headless browser that gets Prowlarr past Cloudflare's challenge on RuTracker's login |
| `pvc.yaml` | the NAS share `tank/media`, writable, for Radarr and Sonarr |
| `ingress.yaml` | the three hosts, behind the admin gate |
| `networkpolicy.yaml` | who may reach each app |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |
| `secret.sops.yaml` | the three API keys - **created by hand, step 1** |

## Setup, in this order

Steps 1 and 2 come before the merge.

**1. The Secrets**, on the workstation from the repo root. The API keys are
generated and never shown: each goes into the app's Secret, and Radarr's
and Sonarr's into Airflow's too, for the warehouse.

```bash
RK=$(openssl rand -hex 16); SK=$(openssl rand -hex 16); PK=$(openssl rand -hex 16)
kubectl create secret generic arr --namespace arr \
  --from-literal=RADARR_API_KEY="$RK" \
  --from-literal=SONARR_API_KEY="$SK" \
  --from-literal=PROWLARR_API_KEY="$PK" \
  --dry-run=client -o yaml > clusters/lab/arr/secret.sops.yaml
sops --encrypt --in-place clusters/lab/arr/secret.sops.yaml
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["RADARR_API_KEY"]' "\"$(printf %s "$RK" | base64 | tr -d '\n')\""
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["SONARR_API_KEY"]' "\"$(printf %s "$SK" | base64 | tr -d '\n')\""
unset RK SK PK
```

The VPN's login, from the PIA account (the username looks like `p1234567`).
Run the two `read` lines one at a time:

```bash
read -rp 'PIA username: ' PU
read -rsp 'PIA password: ' PP; echo
kubectl create secret generic pia --namespace torrents \
  --from-literal=OPENVPN_USER="$PU" \
  --from-literal=OPENVPN_PASSWORD="$PP" \
  --dry-run=client -o yaml > clusters/lab/torrents/secret.sops.yaml
unset PU PP
sops --encrypt --in-place clusters/lab/torrents/secret.sops.yaml
```

And the backup's restic credentials, as the backup README describes:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: arr/' \
  > clusters/lab/backup/restic-repo-arr.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-arr.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-arr.sops.yaml
```

The `grep` must print `namespace: arr` before you encrypt. Commit all four
files and push.

**2. A quota on `tank/media`.** In TrueNAS, *Datasets → tank/media → Edit →
Quotas*: 600 GiB, or what the disk can spare. Downloads then stop at the
quota instead of filling the pool that `personal` and `immich` share.

**3. Check the VPN**, right after the merge, once `kubectl -n torrents get
pods` shows qBittorrent ready (both containers):

```
kubectl -n torrents logs deploy/qbittorrent -c gluetun | grep -i -E 'public ip|port forward'
kubectl -n torrents exec deploy/qbittorrent -c qbittorrent -- curl -s https://ifconfig.me; echo
```

The address it prints must not be the house's - compare it with
<https://ifconfig.me> in a browser at home, without pasting either anywhere.
The log shows the port PIA forwarded; qBittorrent's settings, under
Connection, show the same one.

**4. Prowlarr**, at <https://indexers.lab.baakhoff.com>:

- *Settings → Indexers → Add (+) → FlareSolverr*: host
  `http://flaresolverr.arr.svc.cluster.local:8191`, tag `flaresolverr`.
  *Test*, *Save*. RuTracker's login is behind a Cloudflare challenge that
  turns away anything but a browser; requests from indexers carrying this
  tag go through FlareSolverr's browser instead.
- *Indexers → Add Indexer → RuTracker.org*: your RuTracker login, the tag
  `flaresolverr`. Turn on *Strip Russian letters*, which helps Radarr and
  Sonarr read release names. *Test*, *Save*.
- *Settings → Apps → Radarr*: Prowlarr server
  `http://prowlarr.arr.svc.cluster.local:9696`, Radarr server
  `http://radarr.arr.svc.cluster.local:7878`, API key from Radarr's
  *Settings → General*. Then the same for Sonarr, at
  `http://sonarr.arr.svc.cluster.local:8989`. Prowlarr now adds RuTracker to
  both by itself.

**5. Radarr**, at <https://films.lab.baakhoff.com>:

- *Settings → Media Management*: root folder `/data/films`; *Rename Movies*
  on; *Use Hardlinks instead of Copy* on (the default).
- *Settings → Download Clients → qBittorrent*: host
  `qbittorrent.torrents.svc.cluster.local`, port `8080`, no username or
  password, category `films`. *Test*, *Save*.
- *Settings → Profiles*: in the profile you will use, *Language* `Any` if
  Russian dubs should count, or `Original` for the film's own language.

**6. Sonarr**, at <https://series.lab.baakhoff.com>: the same, with root
folder `/data/series` and category `series`.

**7. The warehouse.** The keys went into Airflow's Secret in step 1; once
Flux has applied it, restart the scheduler so it reads them: `kubectl -n
airflow delete pod -l component=scheduler` (not `rollout restart`, which
Flux undoes).

Then add a film in Radarr, watch it appear in qBittorrent, and an hour or
less after it finishes, in Plex.

## What reaches the warehouse

`ods.radarr_films` and `ods.sonarr_series`: what is followed, whether it is
in the library, and its size. `ods.radarr_history` and
`ods.sonarr_history`: every release grabbed, imported, failed or deleted,
with its name and quality. Nothing from qBittorrent, and no torrent site
logins: those stay in Prowlarr.

## Things to know

- **All torrent traffic goes through PIA, or none does.** The VPN
  container's firewall lets qBittorrent out through the tunnel only, and it
  resolves names over the tunnel too; if the tunnel drops, torrents stop.
  Radarr, Sonarr and Prowlarr are not behind the VPN: they search the sites
  and fetch descriptions, which is ordinary browsing.
- **No port is open at home.** PIA forwards one port on its server to
  qBittorrent, so other peers can still connect in. The port can change
  when the pod restarts; the VPN container tells qBittorrent each time.
- **Keep seeding.** RuTracker counts what you give back. Hard links mean
  seeding costs no extra space; remove a torrent in qBittorrent only once
  it has seeded its share. Deleting a film in Radarr removes the library's
  name for it; the space comes back once the torrent is removed too.
- **RuTracker depends on FlareSolverr** getting through Cloudflare. When
  Cloudflare changes its challenge, searches fail with a 403 or a timeout
  until FlareSolverr catches up - a Renovate PR, usually within days. A
  different *Base Url* in the indexer's settings sometimes helps meanwhile.
- **Plex scans every hour**, so a finished download can take up to an hour
  to show up there.
- **The library is on one disk with no copy elsewhere**, by choice: what was
  downloaded can be downloaded again. Radarr's and Sonarr's lists of what to
  follow are backed up, so a lost disk means waiting for downloads, not
  rebuilding the lists.

## Backup

Radarr's, Sonarr's and Prowlarr's database volumes are in the cluster's
nightly backup (`clusters/lab/backup/`): the films and series followed,
their profiles and history, and the torrent sites with their logins.
qBittorrent's is not - see `clusters/lab/torrents/README.md`.
