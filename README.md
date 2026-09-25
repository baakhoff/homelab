# homelab

Building a homelab out of spare hardware to learn production infrastructure end to end —
networking, clustering, Kubernetes, GitOps, observability — and to host agentic dev
tooling (Claude Code instances) off my main workstation.

The build is documented here as it happens: what exists, how it was set up, and which
decisions were made and why.

## The lab, v1.0

![Three HP Elite Mini 600 G9 stacked in a corner, an eight-port switch and a mesh Wi-Fi unit on top of them, a Raspberry Pi 3B+ on the floor alongside](docs/images/rack-v1.0.jpg)

Three mini PCs, the switch, the mesh unit and the Pi, stacked on the floor and cabled
together. The 10″ rack is printed and waiting on its nuts and fittings. This photo gets
replaced as the build changes, and the one it replaces moves to
[the lab over time](docs/history.md) — which is what the version number is for.

## Hardware

| Device | Specs | Status |
|---|---|---|
| Raspberry Pi 3B+ `exitnode` | 4× Cortex-A53 @ 1.4 GHz, 1 GB RAM — [details](docs/hardware.md) | in service: Pi-hole DNS, Tailscale exit node + subnet router, wired |
| 3× HP Elite Mini 600 G9 | i5-12500T · 16 GB DDR5 · 512 GB NVMe · 1 GbE — [details](docs/hardware.md) | in service: a three-node k3s cluster with replicated Ceph storage — [bring-up](docs/runbooks/node-bring-up.md) |
| Switch | TP-Link TL-SG108E, 8 × 1 GbE, web-managed — [details](docs/hardware.md) | in service: the wired backbone — [the network](docs/network.md) |
| Rack | 10″ 3D-printed — [KWS Rack V2](https://makerworld.com/en/models/2139130-kws-rack-v-2-heavy-duty-10-inch-homelab-rack) | printed, waiting on hardware — not assembled |

Hardware that has left service is in [the lab over time](docs/history.md).

## Services

The cluster's web services sign in with a Pocket ID passkey, either through
the app's own login or through the oauth2-proxy gate. Vaultwarden is the
exception: it keeps its own master password.

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
| [IT-Tools](https://github.com/CorentinTh/it-tools) | About eighty small browser-side tools: encoders, formatters, generators and converters. |
| [Firefly III](https://github.com/firefly-iii/firefly-iii) | Household finances: accounts in any currency, budgets, recurring bills and reports. |
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
  reconciled by Flux from `clusters/lab/`. Rook-Ceph runs an OSD on each and
  serves replicated block storage as the cluster's default StorageClass, with a
  CSI snapshot class on top of it. cert-manager and ingress-nginx,
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
  ([how](clusters/lab/cobalt/README.md)), and IT-Tools, a page of small
  browser-side utilities ([how](clusters/lab/it-tools/README.md)), and
  Firefly III for the household's finances in every currency
  ([how](clusters/lab/firefly/README.md)). Nightly restic backup of its volumes
  to object storage, taken from CSI snapshots so each one is atomic rather than
  crash-consistent ([how](clusters/lab/backup/README.md)).
- **exitnode** — Pi-hole answering DNS for the house (through the router's DHCP)
  and for the tailnet (through Tailscale's DNS override); Tailscale exit node and
  subnet router, so LAN-only things are reachable from anywhere on the tailnet
  ([how](docs/runbooks/pi-exitnode.md)). Also the lab's jump host and the sender
  for Wake-on-LAN, being the only always-on Linux box on the wired segment.
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
docs/
  hardware.md       # hardware inventory and specs
  network.md        # addressing, the switch, how the lab is reached from outside
  history.md        # what the lab looked like before it looked like this
  decisions/        # architecture decision records (ADRs)
  runbooks/         # disaster recovery, the Pi, the cluster nodes, the agent pods
```

## Principles

- Everything as code, GitOps where possible — if it's not in the repo, it doesn't exist.
- No secrets in the repo, ever. Encrypted (SOPS/age) once GitOps needs them.
- Docs updated in the same change that alters behavior, not later.
- Docs describe what exists and what was decided — not what might happen.
- Skills over convenience: choices favor what transfers to production work.
