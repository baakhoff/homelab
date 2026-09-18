# 0007 — epicurus is rebuilt on Kubernetes, not moved

- Status: accepted
- Date: 2026-09-18

## Context

[0003](0003-epicurus-compose-in-incus.md) put epicurus in an Incus system container on
node01 and ran upstream's `docker compose up -d` unmodified. That decision rested on
three things, and all three have changed.

**Two of them were about the application, not about convenience.** The core service
drives the Docker API — it stops, restarts and removes module containers through a
filtered socket proxy, which is how module removal is confirmed. And the edge gateway
routes by Docker labels, with every HTTP service declaring its routing as container
labels. k3s runs containerd and has no equivalent of either. 0003 was right that porting
would not be a configuration exercise: it would have broken two product features.

**Both dependencies are already gone upstream, and epicurus already ships a Helm chart.**
That is the fact this record turns on, and it dates 0003 rather than merely arguing with
it. epicurus is not a third-party project here — the images are
`ghcr.io/baakhoff/epicurus-*` and the deployment tracked is the maintainer's own — so the
Docker coupling was self-imposed and was lifted at the source rather than worked around
in the lab.

What exists upstream now: a chart under `infra/k8s/epicurus` with templates for the core
app, web, modules, Postgres, NATS, Qdrant, OpenBao (with bootstrap and unseal), MinIO,
Ollama and SearXNG, plus ingress, NetworkPolicy, PodMonitor and Secret — gated in CI by a
smoke run on kind. `core.containerRuntime.kind: kubernetes` replaces the Docker API path:
confirmed module removal scales the module Deployment to zero through a **namespaced**
Role, so the core can never reach another namespace and can create or delete nothing.
There is no Docker socket anywhere in it. Routing is one Ingress to `web`, with modules
and the core deliberately unexposed.

So a Kubernetes deployment here is not a fork of anyone's deployment story. It is the
normal one, and 0003's own revisit trigger — "epicurus grows a first-class Helm chart" —
has already fired.

**The third was memory.** node01 has 16 GB of soldered LPDDR4 with no upgrade path,
a measured minimum of 4.29 GB available across a working day, and the stack costs roughly
3 GB at rest. 0003 concluded there was no headroom and no room to guess wrong. That
argument was sound and is now moot: the lab cluster is three machines with 16 GB of DDR5
each, and epicurus would be scheduled across them rather than squeezed beside everything
else on one laptop.

**And node01 is being decommissioned.** Its workloads are moving to the lab cluster one
at a time, and the Incus workbench beside epicurus is already recorded as retiring in
[0006](0006-claude-code-remote-control-pods.md) — "a pet on the machine that is retiring".
0003 named this exact moment as its own revisit trigger: *"revisit when either changes:
epicurus grows a first-class Helm chart ... or the agent workbench moves off node01"*.
Both halves have now fired.

## Decision

epicurus is **recreated as Kubernetes workloads on the lab cluster**. The Incus container
is not migrated — `incus move`, which 0003 named as the portability story, is deliberately
not used. The container is replaced, verified, and then deleted along with the machine.

Kubernetes takes over both roles the Docker API and the label-routing were doing: module
lifecycle through the API server, HTTP routing through Ingress under the existing lab
wildcard certificate.

The selector-less Service and hand-written EndpointSlice that fronted the container retire
with it. So do the Incus ScrapeConfig, its Grafana dashboard, and `epicurus-rules.yaml`,
all of which watch a container that will not exist.

"Rebuilt" applies to the deployment, not to the data. The workloads are recreated from
manifests; Postgres, the vector store, object storage and the secrets vault are **carried
across**. That is the one part of this that is a migration rather than a rewrite, and it
is the part with real failure modes — see below.

## Consequences

What this buys, most of it by closing costs 0003 accepted at the time:

- **epicurus becomes reconciled by Flux.** 0003's largest accepted cost was that "this
  repository cannot tell you what is running" — the version lived in an untracked `.env`
  on node01, with the control loop belonging to the application rather than to the
  platform. That inverts.
- **Its state comes within reach of a backup.** 0003 noted that Postgres, the vector
  store, object storage and the secrets vault were Docker named volumes inside an Incus
  container, "two layers below anything the lab backs up today, which is nothing", and
  called that the largest gap made wider. On Ceph they are PVCs, and adding one to
  [`clusters/lab/backup/`](../../clusters/lab/backup/README.md) is an entry in
  `BACKUP_TARGETS`, a RoleBinding and a copy of a Secret.
- **The EndpointSlice that "does not self-heal" disappears.** Nothing reconciled it
  against reality, so a changed container address broke routing silently. Kubernetes
  Services do that reconciliation by construction.
- **Per-service metrics become scrapeable.** 0003 recorded that the application exposes
  its own `/metrics` endpoints and nothing read them. With kube-prometheus-stack on the
  same cluster that becomes a ServiceMonitor.
- **node01 can be switched off.** This was the last workload on it with an architectural
  reason to stay.

What it costs, accepted knowingly:

- **The chart is young and its release train is not.** Only a `0.0.0-testing` build has
  been published to `oci://ghcr.io/baakhoff/charts/epicurus`, because the chart-release
  workflow is manual dispatch — so the lab tracks the chart path in the repository at a
  branch rather than a published version. That is the same dogfooding trade 0003 made and
  for the same reason; it is not the reproducible-release story a stable deployment would
  want.
- **The chart carries no upgrade proof.** Fresh installs are gated by CI; upgrades over
  existing PVCs are not. The operational consequence is a rule rather than a risk: back up
  before every chart upgrade, which is now something this cluster can actually do.
- **The data has to be moved, and it is the hardest part of this.** It currently sits as
  Docker named volumes inside an Incus container — two layers below anything that has ever
  backed it up. Vaultwarden's move is one SQLite file stopped and copied; this is four
  storage engines, each with its own idea of what a consistent copy is, and a file walk
  over a running Postgres or a live object store produces something that restores
  *sometimes*. Each engine gets a native dump or a full stop, not a `tar` of a running
  directory.
- **The credentials file is part of the payload, and losing it is silent.** 0003 recorded
  that epicurus's root `.env` holds the Postgres and MinIO passwords their data
  directories were INITIALISED with — "lose that file and the bytes are unreadable even
  though you still have them". It is untracked, it lives only on node01, and it is the
  single item here whose loss cannot be recovered by re-running anything. It moves first,
  and into a SOPS secret rather than another untracked file.
- **There is no backup to fall back on during the move.** 0003's own consequence — the
  state sits below anything the lab backs up — is still true on the day the copy happens,
  because the thing that fixes it is the destination. Until epicurus's volumes are PVCs
  in `BACKUP_TARGETS`, node01's disk is the only copy, and the migration is the window
  where that matters most.
- **The deployment is no longer upstream's compose file run unmodified.** 0003 valued that
  highly and was right to. What makes it acceptable now is that the Kubernetes manifests
  become upstream's concern too rather than a translation layer maintained here — the same
  argument, arriving at the opposite conclusion because the premise moved.
- **How it updates is an open question.** 0003's deployment tracked the `testing` branch
  through upstream's own pull-reconcile script on a systemd timer, deliberately choosing a
  dogfooding track over a pinned release. That mechanism does not survive the move. Flux
  image automation and Renovate are both candidates, and they differ in an important way:
  Renovate opens a PR a human merges, which is a slower loop than a timer that pulls
  whatever was pushed. Deciding it is part of the port, not of this record.
- **It becomes a neighbour.** Under Incus a runaway stack hit a hard memory limit and
  killed something inside itself. On the lab cluster it shares three nodes with etcd, the
  Ceph OSDs and the agent pods, so the blast radius is now a matter of resource limits and
  a namespace ResourceQuota — and unlike the agent pods, epicurus has no negative priority
  class making it the first thing evicted. That needs setting deliberately when the
  manifests are written.
