# 0003 — epicurus runs as a compose stack in Incus, not as Kubernetes workloads

- Status: accepted
- Date: 2026-09-03

## Context

The lab has a standing rule: long-running services wait for Kubernetes, so there is no
compose sprawl to migrate later. epicurus is the first real application the lab hosts,
and it is the case that rule was not written for — an upstream project with its own
release cadence, not something built here.

What it is: 23 long-running containers assembled from per-module compose fragments, with
images published to `ghcr.io/baakhoff/epicurus-*`. Two of its dependencies are on Docker
specifically, not on containers generally:

1. **The core service drives the Docker API.** It stops, restarts, and removes module
   containers through a filtered socket proxy — that is how module removal is confirmed
   and how a change to the local model runtime's cache setting is applied. k3s runs
   containerd and has no equivalent object. This is a product feature, not plumbing.
2. **The edge gateway routes by Docker labels.** Every HTTP service declares its routing
   as container labels read by the gateway's Docker provider. On Kubernetes that entire
   layer is replaced by Ingress resources written by hand.

Porting it would therefore not be a configuration exercise. It would fork the
application's deployment story, break two features, and require re-translation on every
upstream change to a compose fragment.

Memory settles the rest. node01 has 16 GB of **soldered** LPDDR4 — eight 2 GB packages
reported as `Form Factor: Row Of Chips`, no DIMM slots, no upgrade path. The measured
minimum available across a full working day is 4.29 GB, and the stack costs roughly 3 GB
at rest. There is no headroom for a duplicate observability stack or a local model, and
none for guessing wrong.

## Decision

epicurus runs in its own Incus system container on node01: nesting enabled, its own
Docker daemon, upstream's `docker compose up -d` unmodified, under a hard memory limit.

Kubernetes still fronts it. A Service with no selector and a hand-written EndpointSlice
point at the container's address, and an Ingress serves it under the existing lab
wildcard certificate. The cluster is the front door; the application is not in it.

The local model runtime stays running but never loads a model — the first-run model pull
is disabled and inference goes to a hosted provider. Upstream supports this explicitly;
it is the difference between fitting on this node and not.

The application's own bundled observability stack stays off. It is opt-in upstream, and
the lab already has Prometheus, Loki, Grafana and Alertmanager.

## Consequences

What this buys:

- Upstream changes apply by pulling images. There is no translation layer to maintain,
  and no fork of anyone's deployment.
- Both Docker-dependent features keep working.
- The blast radius becomes a number you configure. Under a hard memory limit, a runaway
  stack kills something inside itself rather than leaving the kernel to choose a victim
  from the cluster — which, with swap off, it would do instantly.
- It stays portable. `incus move` relocates it to a future dedicated machine, the same
  rule the agent workbench already follows.
- The cluster edge is still exercised end to end: DNS, ACME, TLS termination, ingress,
  and the selector-less Service pattern that is how a Kubernetes edge is put in front of
  anything that is not in Kubernetes.

What it costs, accepted knowingly:

- **epicurus is not reconciled by Flux.** Its version lives in an untracked `.env` on
  node01. Updating is a manual pull-and-restart on the node, and git cannot tell you what
  is running. This is the single largest thing given up.
- **Its state moves further from a backup.** Postgres, the vector store, object storage
  and the secrets vault are Docker named volumes inside an Incus container — two layers
  below anything the lab backs up today, which is nothing. Backups were already the
  largest gap; this widens it.
- **The hand-written EndpointSlice does not self-heal.** Nothing reconciles it against
  reality, so a changed container address breaks routing silently. Mitigated by pinning
  a static address and alerting on the container's absence, not by the platform.
- **Per-service metrics are not scraped.** Container-level CPU and memory come from the
  existing Incus scrape, but the application exposes its own `/metrics` endpoints and
  nothing reads them yet.

Revisit when either changes: epicurus grows a first-class Helm chart — work that belongs
upstream rather than in this repo — or the agent workbench moves off node01 and this node
has room to reconsider what it can afford to run natively.
