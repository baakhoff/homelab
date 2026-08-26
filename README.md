# homelab

Building a homelab out of spare hardware to learn production infrastructure end to end —
networking, clustering, Kubernetes, GitOps, observability — and to host agentic dev
tooling (Claude Code instances) off my main workstation.

Everything here is done in public: architecture, decisions, runbooks, and mistakes.

## Hardware

| Device | Specs | Role (planned) | Status |
|---|---|---|---|
| Laptop | TBD — see [docs/hardware.md](docs/hardware.md) | First server node (Kubernetes control plane) | being prepped |
| Raspberry Pi 3B+ | 4× Cortex-A53 @ 1.4 GHz, 1 GB RAM | Learning node / utility (DNS, probes) | waiting |
| More Raspberry Pis | — | Additional workers | planned |
| NAS | build vs buy undecided | Storage, backups | planned |
| Dedicated PC | — | First serious amd64 worker | planned |

## Roadmap

The full phased plan with exit criteria lives in [docs/roadmap.md](docs/roadmap.md). Short version:

0. **Foundation** — laptop becomes a headless Linux server; SSH, remote access, basics.
1. **Kubernetes core** — single-node k3s; ingress, TLS, first real deployments.
2. **GitOps** — the cluster state lives in this repo and reconciles automatically; encrypted secrets.
3. **Multi-node** — the Pi 3B+ joins the cluster; multi-arch images, taints, scheduling.
4. **Observability** — Prometheus, Grafana, Loki, alerting.
5. **Agentic workloads** — isolated, resource-limited environments for Claude Code.
6. **Storage & NAS** — backups first, then the NAS decision, then cluster storage.
7. **Networking deeper** — VLANs, segmentation, controlled external exposure.

## Repo layout

```
docs/
  roadmap.md      # the phased plan, kept current
  hardware.md     # hardware inventory and specs
  decisions/      # architecture decision records (ADRs)
```

## Principles

- Everything as code, GitOps where possible — if it's not in the repo, it doesn't exist.
- No secrets in the repo, ever. Encrypted (SOPS/age) once GitOps needs them.
- Docs updated in the same change that alters behavior, not later.
- Skills over convenience: choices favor what transfers to production work.
