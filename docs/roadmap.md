# Roadmap

Phased plan. Each phase has a goal, the work-translatable skills it teaches, and exit
criteria. Decisions that are still open are tracked at the bottom and get an ADR in
[decisions/](decisions/) when made.

## Phase 0 — Foundation: laptop becomes a server

- Install Ubuntu Server 24.04 LTS (headless) on the laptop.
- SSH with key-only auth, password auth disabled; static DHCP reservation on the router;
  a hostname scheme.
- Laptop-as-server prep: `HandleLidSwitch=ignore` in logind, suspend disabled, thermals
  checked. The battery doubles as a free mini-UPS — one genuine advantage of laptop
  servers.
- Tailscale for remote access from workstation and phone — no port forwarding, no
  exposure, works behind CGNAT.
- Docker Engine installed (for builds and one-off containers), but long-running services
  wait for Kubernetes — no docker-compose sprawl to migrate later.

**Skills:** Linux server administration, SSH hygiene, DHCP/DNS basics, overlay-network
remote access.

**Exit:** laptop reachable headlessly over the tailnet, lid closed, survives reboot
unattended.

## Phase 1 — Kubernetes core (k3s, single node)

- k3s server on the laptop (bundled Traefik ingress + local-path storage are fine to
  start). `kubectl` + `helm` on the workstation, talking to it remotely.
- First deployments by hand to learn the objects: a demo app, then something genuinely
  useful (e.g. Uptime Kuma). Services, Ingress, namespaces, resource requests/limits.
- cert-manager with Let's Encrypt DNS-01 — valid TLS certificates without opening any
  ports.

**Skills:** core Kubernetes objects, ingress and TLS, debugging pods — the daily
vocabulary of production clusters.

**Exit:** a real app served at `https://<name>.<domain>` over the tailnet with a valid
certificate.

## Phase 2 — GitOps

- Flux (or Argo CD — decision D3) reconciling this repo: a `clusters/` directory becomes
  the source of truth; manual `kubectl apply` stops.
- Secrets encrypted in-repo with SOPS + age. Mandatory — the repo is public.

**Skills:** GitOps is the single most work-translatable practice here; this is how
production fleets are actually run.

**Exit:** a change merged via PR converges into the cluster with no manual steps.

## Phase 3 — Multi-node: the Pi 3B+ joins

Honest reality: 1 GB RAM, Cortex-A53, 100 Mbit NIC on a USB2 bus — the 3B+ is a
*learning* node, not capacity. That's still valuable:

- 64-bit Raspberry Pi OS Lite, k3s agent joining the laptop's control plane.
- Taint the node; schedule only tiny, tolerant workloads (node_exporter, maybe DNS).
- Multi-arch images with `docker buildx` — amd64 + arm64 manifests.

Afterwards (or instead, if joining proves too tight on RAM) the Pi makes a great
standalone Pi-hole/AdGuard DNS box outside the cluster.

**Skills:** multi-node networking, taints/tolerations/affinity, multi-arch builds — all
real production concerns.

**Exit:** `kubectl get nodes` shows 2 Ready nodes; a multi-arch workload runs pinned to
the Pi.

## Phase 4 — Observability

- kube-prometheus-stack (Prometheus, Alertmanager, Grafana) on the laptop node; Loki for
  logs.
- Dashboards for both nodes; alerts pushed to phone (ntfy or similar).

**Skills:** metrics, logs, alerting — SRE bread and butter.

**Exit:** an induced failure (kill a node, fill a disk) pages the phone within minutes.

## Phase 5 — Agentic workloads

The original itch: run Claude Code without cooking the workstation.

- A dedicated dev environment on the server: container or VM with CPU/memory limits,
  project volumes, accessed via SSH + tmux (or code-server in the browser).
- Auth tokens handled as proper secrets, never in images or the repo.
- Later: batch/background agent runs as Kubernetes Jobs with resource quotas.

**Skills:** workload isolation, resource governance, multi-tenancy thinking.

**Exit:** a full Claude Code session runs on the lab from a thin client, with the
workstation idle.

## Phase 6 — Storage & NAS

- Backups come first and don't wait for a NAS: restic from day one for anything stateful
  (external disk and/or B2-class cloud target). A NAS is not a backup; 3-2-1 still
  applies.
- Then decision D4 — build (used SFF box + TrueNAS/ZFS: more learning, more fiddling) vs
  buy (Synology-class: reliability, less learning). Either way it exposes NFS to the
  cluster.
- Then proper cluster storage: NFS provisioner first; Longhorn only when there are ≥2
  capable amd64 nodes.

**Exit:** a restore drill actually performed, not assumed.

## Phase 7 — Networking, deeper

- Managed switch, VLANs (lab / trusted / IoT), inter-VLAN firewall rules.
- Deliberate, minimal external exposure of selected services behind a reverse proxy with
  SSO (Authelia/oauth2-proxy), instead of tailnet-only.
- Possibly a dedicated router/firewall box (OPNsense) as its own project.

**Skills:** L2/L3 fundamentals, segmentation, edge security.

## Later hardware

The planned "PC for services" becomes the first serious amd64 worker — and pushes toward
3 nodes, which unlocks HA control-plane / etcd quorum learning. More Pis slot in as
cheap arm64 workers or utility boxes.

## Open decisions

| # | Decision | Leaning | Decide by |
|---|---|---|---|
| D1 | Proxmox under everything vs bare-metal Ubuntu on the laptop | Depends on laptop RAM: ≥16 GB → Proxmox worth the learning; ≤8 GB → bare metal | Before Phase 0 install |
| D2 | Kubernetes distro | k3s (real conformant k8s, light, huge homelab community) | Phase 1 |
| D3 | GitOps engine: Flux vs Argo CD | Flux for repo-native minimalism; Argo if a UI is wanted | Phase 2 |
| D4 | NAS: build vs buy | Deferred until Phase 6; backups don't wait | Phase 6 |
| D5 | Domain to use for TLS/ingress | Needs a domain with DNS API access (for DNS-01) | Phase 1 |
| D6 | Repo license | — | Whenever |
