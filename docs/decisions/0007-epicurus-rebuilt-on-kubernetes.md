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

Those two dependencies are being removed **upstream**, and that is the fact this record
turns on. epicurus is not a third-party project here — the images are
`ghcr.io/baakhoff/epicurus-*` and the deployment being tracked is the maintainer's own
`testing` branch. The Docker coupling was self-imposed, so it can be lifted at the source
instead of worked around in the lab. Module lifecycle stops going through the Docker API;
the gateway stops reading container labels. Once both land, a Kubernetes deployment is
not a fork of anyone's deployment story — it is the normal one.

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

Rebuilt rather than moved, specifically: the data is recreated from scratch. This is the
one place where "recreate" is a real cost rather than a simplification, and it is accepted
knowingly — see below.

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

- **The work is upstream, and until it lands the lab has no epicurus.** This record
  depends on two changes in another repository. If they stall, the fallback is not "run it
  in Incus on node01" — that machine is going — but "run it in Incus on a lab node", which
  would be a new decision and a worse one.
- **The data does not come across.** Postgres, the vector store, object storage and the
  vault are recreated empty. For a dogfooding deployment of the maintainer's own
  unreleased work this is acceptable; for anything holding data that mattered it would not
  be, and this line is the one to re-read if that ever changes.
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
