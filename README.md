# homelab

Building a homelab out of spare hardware to learn production infrastructure end to end —
networking, clustering, Kubernetes, GitOps, observability — and to host agentic dev
tooling (Claude Code instances) off my main workstation.

The build is documented here as it happens: what exists, how it was set up, and which
decisions were made and why.

## Hardware

| Device | Specs | Status |
|---|---|---|
| Laptop `node01` | i5-1240P · 16 GB RAM · 512 GB NVMe · Wi-Fi only — [details](docs/hardware.md) | in service: k3s + Flux, Incus workbench |
| Raspberry Pi 3B+ `exitnode` | 4× Cortex-A53 @ 1.4 GHz, 1 GB RAM — [details](docs/hardware.md) | in service: Pi-hole DNS, Tailscale exit node + subnet router |
| 3× HP Elite Mini 600 G9 | i5-12500T · 16 GB DDR5 · 512 GB NVMe · 1 GbE — [details](docs/hardware.md) | Ubuntu Server installed, not yet in service |
| Rack | 10″ 3D-printed — [KWS Rack V2](https://makerworld.com/en/models/2139130-kws-rack-v-2-heavy-duty-10-inch-homelab-rack) | printing |

## Where things run

- **node01** — k3s (single node) reconciled by Flux from `clusters/homelab/`:
  ingress-nginx with cert-manager certificates, kube-prometheus-stack and Loki,
  Headlamp, Homepage, Vaultwarden. Beside the cluster, two Incus containers: the
  epicurus stack and the Claude Code workbench. Nightly restic backup to object
  storage ([how](hosts/node01/backup/README.md)).
- **exitnode** — Pi-hole answering DNS for the house (through the router's DHCP)
  and for the tailnet (through Tailscale's DNS override); Tailscale exit node and
  subnet router, so LAN-only things are reachable from anywhere on the tailnet
  ([how](docs/runbooks/pi-exitnode.md)).
- **Workstation** — a client: `kubectl`, `flux`, git. Hosts nothing.

## Repo layout

```
clusters/homelab/   # Flux-reconciled Kubernetes manifests, one directory per component
hosts/              # host-level config installed by hand, outside GitOps
  node01/backup/    #   restic units, script, excludes, bucket lifecycle policy
  exitnode/         #   the Pi: sshd hardening, forwarding sysctl, cloud-init guard
docs/
  hardware.md       # hardware inventory and specs
  decisions/        # architecture decision records (ADRs)
  runbooks/         # rebuilding things: disaster recovery, the Pi
```

## Principles

- Everything as code, GitOps where possible — if it's not in the repo, it doesn't exist.
- No secrets in the repo, ever. Encrypted (SOPS/age) once GitOps needs them.
- Docs updated in the same change that alters behavior, not later.
- Docs describe what exists and what was decided — not what might happen.
- Skills over convenience: choices favor what transfers to production work.
