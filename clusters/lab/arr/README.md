# Radarr, Sonarr, Prowlarr, Bazarr and Seerr

Films and series that arrive by themselves. Pick a film in
[Radarr](https://radarr.video) or a series in [Sonarr](https://sonarr.tv);
they search the torrent sites through [Prowlarr](https://prowlarr.com),
hand the best release to qBittorrent (`clusters/lab/torrents/`), and when it
has downloaded, hard-link it into the NAS's library under a clean name.
Plex shows it on its next scan. Sonarr keeps following a series and fetches
each new episode.

Around them: [Bazarr](https://www.bazarr.media) fetches subtitles for every
film and episode in the household's languages and puts them beside the
video, where Plex finds them. [Seerr](https://github.com/seerr-team/seerr)
is where the rest of the household asks for a film or a series, without
touching Radarr or Sonarr; each person signs in with their plex.tv account.

| App | Address | Homepage |
|---|---|---|
| Radarr | <https://films.lab.baakhoff.com> | Everyday → Play |
| Sonarr | <https://series.lab.baakhoff.com> | Everyday → Play |
| Prowlarr | <https://indexers.lab.baakhoff.com> | Ops → Platform |
| Bazarr | <https://subtitles.lab.baakhoff.com> | Ops → Platform |
| Seerr | <https://requests.lab.baakhoff.com> | Everyday → Play |
| qBittorrent | <https://torrents.lab.baakhoff.com> | Ops → Platform |

## How login works

The admin gate: Pocket ID, members of `lab-admins` only. The apps' own login
is set to `External`, trusting the gate, so there is one login and not two -
Bazarr's is `None`, its name for the same. Their APIs still need each app's
key. None of them has a phone app that would need to get past the gate.

**Seerr is for everyone**, so its gate admits anyone Pocket ID lets through
the oauth2-proxy client, not only `lab-admins`. Behind it Seerr asks for a
plex.tv account, because who may ask for films is who may watch them: the
accounts the owner shares Plex with. The owner's account is Seerr's admin.
Two logins the first time, then the gate's cookie and Seerr's session both
last. Only in the house and on the tailnet, like every lab host - family
watching through Plex's Relay from elsewhere cannot reach it.

## How the files move

```
NAS tank/media, mounted at /data in qBittorrent, Radarr and Sonarr
├── downloads/        qBittorrent writes here, and keeps seeding from here
├── films/            Radarr hard-links finished films here      ─┐ Plex reads
└── series/           Sonarr hard-links finished episodes here   ─┘ these
```

Bazarr mounts the same share at the same path, so the paths Radarr and
Sonarr report are paths it can open, and writes each subtitle beside its
video - `Film (2024).ru.srt` next to `Film (2024).mkv`. Seerr touches no
file; it only talks to Plex, Radarr and Sonarr.

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
| `bazarr.yaml` | Bazarr with its Service and database volume, and the media share writable |
| `seerr.yaml` | Seerr with its Service and database volume; no NAS |
| `pvc.yaml` | the NAS share `tank/media`, writable, for Radarr and Sonarr |
| `ingress.yaml` | the five hosts, four behind the admin gate and Seerr behind the household's |
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

**7. Bazarr**, at <https://subtitles.lab.baakhoff.com>:

- *Settings → General → Security*: Authentication `None`; the gate is the
  login.
- *Settings → Languages*: add English, Russian, Serbian and Kazakh to the
  languages filter, then a profile `Household` with the ones you want
  fetched, in the order you prefer them. Set it as the default for films
  and for series. Serbian subtitles are in Latin script almost
  everywhere; Kazakh ones are rare, so expect few.
- *Settings → Providers*: OpenSubtitles.com (a free account; its login
  goes here), Podnapisi, Titlovi - the Balkans' own - and Embedded
  Subtitles, which uses the ones already inside the file.
- *Settings → Sonarr*: on; address `sonarr.arr.svc.cluster.local`, port
  `8989`, the API key from Sonarr's *Settings → General*. *Test*, *Save*.
  *Settings → Radarr*: the same with `radarr.arr.svc.cluster.local` and
  `7878`. No path mappings: all of them see the share at `/data`.

**8. Seerr**, at <https://requests.lab.baakhoff.com>:

- *Sign in with Plex* with the owner's plex.tv account; it becomes Seerr's
  admin.
- *Plex*: server by hand - `plex.plex.svc.cluster.local`, port `32400`, no
  SSL - then *Sync Libraries*, tick Films and Series, *Start Scan*.
- *Services → Add Radarr*: default server on; hostname
  `radarr.arr.svc.cluster.local`, port `7878`, Radarr's API key; *Test*,
  then the quality profile and root folder `/data/films`. *Add Sonarr* the
  same with `sonarr.arr.svc.cluster.local`, `8989` and `/data/series`.
- *Settings → General*: Application URL `https://requests.lab.baakhoff.com`.
- *Users → Import Plex Users*: the accounts Plex is shared with. Whose
  requests go through without asking is *Auto-Approve* on that user, or
  in *Settings → Users* for everyone; without it a request waits for the
  owner under *Requests*.

**9. The warehouse.** Radarr's and Sonarr's keys went into Airflow's Secret
in step 1. Bazarr and Seerr made their own when they first started; read
each straight into the Secret without showing it:

```bash
BK=$(kubectl -n arr exec deploy/bazarr -- awk '/^auth:/{a=1;next} /^[^ ]/{a=0} a && $1=="apikey:"{print $2}' /config/config/config.yaml)
SK=$(kubectl -n arr exec deploy/seerr -- node -p "require('/app/config/settings.json').main.apiKey")
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["BAZARR_API_KEY"]' "\"$(printf %s "$BK" | base64 | tr -d '\n')\""
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["SEERR_API_KEY"]' "\"$(printf %s "$SK" | base64 | tr -d '\n')\""
unset BK SK
```

Commit and push. Once Flux has applied it, restart the scheduler so it
reads them: `kubectl -n airflow delete pod -l component=scheduler` (not
`rollout restart`, which Flux undoes). Until then `ingest_bazarr` and
`ingest_seerr` fail, harmlessly.

Then ask for a film in Seerr, watch it appear in Radarr and qBittorrent,
and an hour or less after it finishes, in Plex - with its subtitles.

## What reaches the warehouse

`ods.radarr_films` and `ods.sonarr_series`: what is followed, whether it is
in the library, and its size. `ods.radarr_history` and
`ods.sonarr_history`: every release grabbed, imported, failed or deleted,
with its name and quality. `ods.bazarr_films` and `ods.bazarr_series`:
the subtitle languages each film has and lacks, and per series how many
episodes still lack one. `ods.seerr_requests`: every request - what, by
whom, approved or not, arrived or not - and `ods.seerr_users`, the
accounts. Nothing from qBittorrent, and no torrent or subtitle site
logins: those stay in Prowlarr and Bazarr.

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
  to show up there - and a subtitle Bazarr adds later, too.
- **Subtitle sites ration their downloads.** OpenSubtitles' free account
  allows a few dozen a day; a new library's backlog takes Bazarr days, not
  hours, and it carries on by itself.
- **The library is on one disk with no copy elsewhere**, by choice: what was
  downloaded can be downloaded again. Radarr's and Sonarr's lists of what to
  follow are backed up, so a lost disk means waiting for downloads, not
  rebuilding the lists.

## Backup

Radarr's, Sonarr's, Prowlarr's, Bazarr's and Seerr's database volumes are
in the cluster's nightly backup (`clusters/lab/backup/`): the films and
series followed, their profiles and history, the torrent and subtitle
sites with their logins, and the household's requests. The subtitles are
on the NAS beside the films, and can be fetched again like them.
qBittorrent's is not - see `clusters/lab/torrents/README.md`.
