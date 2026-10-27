# homelab

Building a homelab out of spare hardware to learn production infrastructure end to end —
networking, clustering, Kubernetes, GitOps, observability — and to host agentic dev
tooling (Claude Code instances) off my main workstation.

The build is documented here as it happens: what exists, how it was set up, and which
decisions were made and why.

## The lab, v2.0

![A 10-inch 3D-printed rack with yellow rails on a wooden floor: a mesh Wi-Fi unit on top, an eight-port switch and a keystone patch panel in the top units, three HP Elite Mini 600 G9 in printed mounts below them, and a shelf of power adapters at the bottom, with yellow patch cords still hanging loose out of the front](docs/images/rack-v2.0.jpg)

Everything from the floor is in the rack: the switch and the keystone patch panel at
the top, the three mini PCs in their mounts, the power adapters on the shelf at the
bottom, and the mesh unit sitting on the lid. The patch cords arrived and are plugged
in but not yet dressed, which is why the front looks the way it does. This photo gets
replaced as the build changes, and the one it replaces moves to
[the lab over time](docs/history.md) — which is what the version number is for.

## Hardware

| Device | Specs | Status |
|---|---|---|
| Raspberry Pi 3B+ `exitnode` | 4× Cortex-A53 @ 1.4 GHz, 1 GB RAM — [details](docs/hardware.md) | in service: Pi-hole DNS, Tailscale exit node + subnet router, wired |
| 3× HP Elite Mini 600 G9 | i5-12500T · 16 GB DDR5 · 512 GB NVMe · 1 GbE — [details](docs/hardware.md) | in service: a three-node k3s cluster with replicated Ceph storage — [bring-up](docs/runbooks/node-bring-up.md) |
| NAS `nas` | Pentium Gold G5400 · 16 GB RAM · 256 GB NVMe boot · WD Red Plus 2 TB · 1 GbE — [details](docs/hardware.md#nas--nas) | installed: TrueNAS Community Edition, wired, alerting to Telegram; pool `tank` with an encrypted SMB share and NFS shares for Immich and Plex, snapshotted, single disk, no off-site copy — [bring-up](docs/runbooks/nas-bring-up.md) |
| Switch | TP-Link TL-SG108E, 8 × 1 GbE, web-managed — [details](docs/hardware.md) | in service: the wired backbone — [the network](docs/network.md) |
| Rack | 10″ 3D-printed, 12U — [KWS Rack V2 and the printed mounts](docs/hardware.md#rack) | in service: switch, patch panel, the three mini PCs and their power adapters are mounted; cables still to be dressed |

Hardware that has left service is in [the lab over time](docs/history.md).

## Services

The cluster's web services sign in with a Pocket ID passkey, either through
the app's own login or through the oauth2-proxy gate. Two exceptions:
Vaultwarden keeps its own master password, and Plex signs in with plex.tv
accounts, the only login its TV apps know.

| Service | What it is |
|---|---|
| [Homepage](https://gethomepage.dev) | Dashboard linking everything below, with a health badge on each. |
| [Pocket ID](https://pocket-id.org) | Passkey-only sign-in that every other service in the lab logs in through. |
| [oauth2-proxy](https://github.com/oauth2-proxy/oauth2-proxy) | The login gate for services that have no login of their own. |
| [Vaultwarden](https://github.com/dani-garcia/vaultwarden) | Bitwarden-compatible password vault for the household. |
| [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | Household documents, scanned, OCR'd in four languages and searchable. |
| [ConvertX](https://github.com/C4illin/ConvertX) | Converts files between most formats: images, documents, e-books, audio and video. |
| [Stirling-PDF](https://www.stirlingpdf.com) | Merges, splits, reorders and edits PDFs, and turns a stack of images into one PDF. |
| [cobalt](https://github.com/imputnet/cobalt) | Saves video and audio from a link, streamed straight to the device with nothing kept on the server. |
| [SearXNG](https://github.com/searxng/searxng) | Private web search: one query to dozens of engines, results merged, nothing tracked; the agents search through it too. |
| [IT-Tools](https://github.com/CorentinTh/it-tools) | About eighty small browser-side tools: encoders, formatters, generators and converters. |
| [Firefly III](https://github.com/firefly-iii/firefly-iii) | Household finances: accounts in any currency, budgets, recurring bills and reports. |
| [n8n](https://n8n.io) | Visual automations: schedules, emails and webhooks wired to any service in or outside the lab. |
| [Apache Kafka](https://kafka.apache.org) | The event bus every source writes its raw data to. |
| [Kafbat UI](https://github.com/kafbat/kafka-ui) | A read-only browser view of Kafka: topics, messages and consumer lag. |
| [ClickHouse](https://clickhouse.com) | The column store those events land in, queried in SQL. |
| [Apache Airflow](https://airflow.apache.org) | Runs the data pipelines: API snapshots into Kafka, and the dbt models. |
| [dbt](https://www.getdbt.com) | The SQL models that build the warehouse's layers from the raw data. |
| [CloudBeaver](https://github.com/dbeaver/cloudbeaver) | DBeaver in the browser: every database in the lab, read-only, with an SQL editor and result grids. |
| [Mealie](https://mealie.io) | Recipes imported from any site by link, meal plans and shared shopping lists. |
| [SparkyFitness](https://github.com/CodeWithCJ/SparkyFitness) | Calorie and macro tracking with an AI that logs meals from a photo, plus exercise and weight, with a phone app. |
| [Outline](https://www.getoutline.com) | Notes and documents in a polished web editor, organised in collections, with every edit kept in its history; an agent reads and writes them too. |
| [Dawarich](https://github.com/Freika/dawarich) | Location history from the phone on a map: trips, visits, countries and stats, a self-hosted Google Timeline. |
| [Photon](https://github.com/komoot/photon) | Turns Dawarich's coordinates into streets, cities and places, from OpenStreetMap, without sending them out of the lab. |
| [Immich](https://immich.app) | The family's photos and videos: phones back up to it, with faces, places and search in any language, and the library on the NAS. |
| [Plex](https://www.plex.tv) | Films and series from the NAS to the TVs, phones and browsers, converting on the cluster's Intel graphics what a device cannot play. |
| [Radarr](https://radarr.video) | Films on request: pick one, and it finds, downloads and files it for Plex, upgrading the quality later. |
| [Sonarr](https://sonarr.tv) | The same for series, fetching each new episode as it airs. |
| [Prowlarr](https://prowlarr.com) | The torrent sites, kept in one place for Radarr and Sonarr. |
| [qBittorrent](https://www.qbittorrent.org) | The torrent client they hand downloads to, only ever through the VPN. |
| [Grafana](https://grafana.com/oss/grafana/) | Dashboards for the cluster's metrics and logs. |
| [Prometheus](https://prometheus.io) | The metrics store and its alert rules. |
| [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) | Firing alerts and silences; notifications go to Telegram. |
| [Loki](https://grafana.com/oss/loki/) | Log storage for every pod, queried from Grafana. |
| [Headlamp](https://headlamp.dev) | Kubernetes UI: pods, logs, events and Flux state. |
| [epicurus](https://github.com/baakhoff/epicurus) | The assistant: its core, web shell and modules. |
| [Minecraft server](https://github.com/itzg/docker-minecraft-server) | Java Edition server for the household. |
| [Pi-hole](https://pi-hole.net) | DNS and ad blocking for the house and the tailnet, on the Pi. |

## Where things run

- **node02, node03, node04** — k3s with embedded etcd, all three as servers,
  reconciled by Flux from `clusters/lab/`, and from a second, private
  repository for what is better not published
  ([how](clusters/lab/private/README.md)). Rook-Ceph runs an OSD on each and
  serves replicated block storage as the cluster's default StorageClass, with a
  CSI snapshot class on top of it; csi-driver-nfs mounts NAS shares, one
  static volume per share and no StorageClass. cert-manager and ingress-nginx,
  kube-prometheus-stack and Loki, Headlamp and Homepage, Vaultwarden, epicurus
  ([ADR 0007](docs/decisions/0007-epicurus-rebuilt-on-kubernetes.md)), and the
  agent pods: Claude Code Remote Control servers on volumes that follow the pod
  between nodes ([how](docs/runbooks/agent-pods.md), [how the nodes got
  here](docs/runbooks/node-bring-up.md)), and a Minecraft server for the
  household, the one thing on the cluster that reaches the LAN as raw TCP
  rather than through the ingress controller
  ([how](clusters/lab/minecraft/README.md)), and Pocket ID, a passkey-only
  OpenID Connect provider that Grafana signs in through, and that
  oauth2-proxy puts in front of everything with no login of its own
  ([how](clusters/lab/pocket-id/README.md)), and Paperless, the household's
  documents scanned, OCR'd and searchable
  ([how](clusters/lab/paperless/README.md)), and ConvertX, file conversion
  between most formats in the browser, behind that same gate
  ([how](clusters/lab/convertx/README.md)), and Stirling-PDF beside it for
  merging, splitting and reordering PDFs
  ([how](clusters/lab/stirling-pdf/README.md)), and cobalt, which saves video
  and audio from a link straight to the device
  ([how](clusters/lab/cobalt/README.md)), and SearXNG, private web search for
  the household and the agents ([how](clusters/lab/searxng/README.md)), and IT-Tools, a page of small
  browser-side utilities ([how](clusters/lab/it-tools/README.md)), and
  Firefly III for the household's finances in every currency
  ([how](clusters/lab/firefly/README.md)), and Mealie for recipes, meal plans
  and shopping lists ([how](clusters/lab/mealie/README.md)), and SparkyFitness
  for calories, meals and exercise ([how](clusters/lab/sparkyfitness/README.md)), and
  Dawarich keeping the phones' location history ([how](clusters/lab/dawarich/README.md)), with
  Photon naming its streets and places ([how](clusters/lab/photon/README.md)), and
  Immich for the family's photos and videos, its library on the NAS
  ([how](clusters/lab/immich/README.md)), and
  Plex for films and series, also from the NAS, transcoding on the nodes'
  Intel graphics through Intel's device plugin
  ([how](clusters/lab/plex/README.md)), and
  Radarr, Sonarr and Prowlarr filling that library from the torrent sites,
  through a qBittorrent that reaches the internet only over a VPN
  ([how](clusters/lab/arr/README.md)), and
  Outline for notes and documents ([how](clusters/lab/notes/README.md)), and n8n for
  automations between all of it ([how](clusters/lab/n8n/README.md)), and Kafka
  feeding ClickHouse, where every source's raw data is kept for querying
  ([how](clusters/lab/data/README.md)), and Airflow running the pipelines
  that pull the services' data in and the dbt models that shape it
  ([how](clusters/lab/airflow/README.md)), and CloudBeaver reading every
  database in the lab from the browser ([how](clusters/lab/cloudbeaver/README.md)). Nightly restic backup of its volumes
  to object storage, taken from CSI snapshots so each one is atomic rather than
  crash-consistent ([how](clusters/lab/backup/README.md)).
- **exitnode** — Pi-hole answering DNS for the house (through the router's DHCP)
  and for the tailnet (through Tailscale's DNS override); Tailscale exit node and
  subnet router, so LAN-only things are reachable from anywhere on the tailnet
  ([how](docs/runbooks/pi-exitnode.md)). Also the lab's jump host and the sender
  for Wake-on-LAN, being the only always-on Linux box on the wired segment.
- **nas** — TrueNAS Community Edition on its own box, outside the cluster
  ([why](docs/decisions/0008-truenas-for-the-nas.md),
  [how](docs/runbooks/nas-bring-up.md)). On the LAN and alerting to the same
  Telegram chat as Alertmanager. One pool on one disk, snapshotted hourly and
  daily, shares an encrypted `personal` dataset to Windows over SMB, and
  Immich's photo library and Plex's films to the cluster's nodes over NFS. No
  redundancy and no off-site copy, so it is not the only copy of anything.
- **Workstation** — a client: `kubectl`, `flux`, git. Hosts nothing.

Every machine is wired to one managed switch; addressing, the port map and how
it is all reached from outside are in [the network](docs/network.md).

## Repo layout

```
clusters/           # Flux-reconciled Kubernetes manifests, one directory per component
  lab/              #   the node02-04 cluster
hosts/              # host-level config installed by hand, outside GitOps
  node01/backup/    #   the retired laptop's restic units, kept as a record
  exitnode/         #   the Pi: sshd hardening, forwarding sysctl, cloud-init guard, wake-nodes
  nodes/            #   node02-04, configured identically: netplan, cloud-init guard, sshd
images/
  claude-agent/     # container image for the Claude Code agent pods, built by GitHub Actions
  paperless-ngx/    # upstream Paperless-ngx plus extra OCR languages, built the same way
  cobalt-web/       # cobalt's web page, which upstream does not publish, built the same way
  airflow/          # Airflow plus Cosmos, the Kafka client and dbt, built the same way
pipelines/          # the data warehouse's Airflow DAGs and dbt project, pulled by Airflow
docs/
  hardware.md       # hardware inventory and specs
  network.md        # addressing, the switch, how the lab is reached from outside
  history.md        # what the lab looked like before it looked like this
  decisions/        # architecture decision records (ADRs)
  runbooks/         # disaster recovery, the Pi, the cluster nodes, the NAS, the agent pods
```

## Principles

- Everything as code, GitOps where possible — if it's not in the repo, it doesn't exist.
- No secrets in the repo, ever. Encrypted (SOPS/age) once GitOps needs them.
- Docs updated in the same change that alters behavior, not later.
- Docs describe what exists and what was decided — not what might happen.
- Skills over convenience: choices favor what transfers to production work.
