# 0006 — Claude Code instances run in the cluster as Remote Control server pods

- Status: accepted
- Date: 2026-09-13

## Context

Hosting Claude Code off the workstation is one of the two reasons this lab
exists. Until now that meant one Incus system container on node01 — a home
directory, live checkouts, a Docker daemon and an OAuth login, reached over the
tailnet with SSH and tmux. It worked, and it was a pet: one container that can
only ever be on one machine, holding every project at once, with a terminal
multiplexer as its user interface.

Two things changed the picture.

- **Claude Code gained a server mode.** `claude remote-control` is a headless
  process that serves sessions to claude.ai/code and the Claude mobile app.
  It makes outbound HTTPS requests only, never listens on a port, needs no
  terminal, and one process serves many concurrent sessions, each in its own
  git worktree. The phone and the browser become the interface; the pod is
  just where the commands run.
- **Kubernetes user namespaces became stable.** An agent runs arbitrary
  commands on behalf of a model. With `hostUsers: false` its root is nobody on
  the node, which is what makes running such a thing next to a password vault
  and the GitOps decryption key defensible without any privileged container.

The direction for the cluster is that everything runs on it, agents included,
and the workstation stays a client.

## Decision

Each project gets **one Deployment in the `agents` namespace** running
`claude remote-control` in a checkout of that project on its own volume. The
manifest for one project is the template for the next: name, repository and
resources change, nothing else. See [the runbook](../runbooks/agent-pods.md).

**Per-project pods, not one pod for everything.** A pod lands on one node,
so one pod for all projects would share one node's memory and one failure
domain. Separate pods let the scheduler place each project by its request
wherever there is room, give each project its own limits, and let a project
be parked at zero replicas without touching the others. Never more than one
replica: a second server in the same checkout would conflict, and more
concurrent sessions come from the one server, not from more pods.

**The namespace carries the guard rails**, so a project file cannot forget
them:

- Pod Security Admission enforces the `restricted` profile.
- A PriorityClass below every other workload, with preemption off: under
  memory pressure an agent is evicted first and never displaces anything.
- A ResourceQuota, which also forces every pod to declare requests and limits.
- NetworkPolicies: nothing in the cluster can reach an agent, and an agent
  reaches only cluster DNS and the public internet — not the Kubernetes API,
  not other namespaces, not the LAN, not the tailnet.
- No service-account token mounted, user namespaces on, every capability
  dropped, no privilege escalation.

**The image is built by the repository**, not by hand: a GitHub Actions
workflow publishes it on merge, tagged with the pinned CLI version, and
Renovate bumps the pin from the npm registry. The image holds Node, the CLI,
git, `gh`, Python with `uv`, and an entrypoint that clones the project and
starts the server.

**Authentication is a full claude.ai login per pod**, made once through
`kubectl exec` and kept on the pod's volume. Remote Control requires it; the
long-lived token from `claude setup-token` can only make model requests and
was therefore not an option. Sessions start in the `acceptEdits` permission
mode: edits are automatic, shell commands ask, and the question reaches the
phone.

Rejected along the way:

- **Keeping the Incus workbench.** A pet on the machine that is retiring, and
  no way to grow per project.
- **One pod holding every project as separate containers.** One login instead
  of many was the only gain; the single-node ceiling was the cost.
- **Claude Code on the web with self-hosted runners.** The official shape of
  "cloud sessions on your own hardware", but a Team and Enterprise feature,
  not available on this subscription.

## Consequences

- **Bootstrapping is interactive, once per project.** The login, the workspace
  trust dialog and Remote Control's own confirmation each need a person at a
  terminal, so a new pod waits until someone does them through `kubectl exec`.
  The login expires; a session that outlives it stalls until the login is
  renewed the same way.
- **No Docker inside the pod.** The image and the pod are unprivileged by
  construction, so projects whose tests need a Docker daemon are not served by
  this shape. How to give them one is a separate decision.
- **The pod's volume is not backed up.** It holds a clone, a login, session
  history and dependency caches. Deleting a project's manifest prunes the
  volume, so uncommitted work has the same rule as on a laptop: commit or
  push before relying on it.
- **A pod is pinned to the node its volume was created on**, because the
  volumes are local-path. Moving a project means recreating its volume, which
  costs a fresh clone and a new login.
- **Transcripts of connected sessions are stored on Anthropic's servers**, as
  with any Remote Control use, to keep devices in sync. Execution and files
  stay in the pod.
- **The login on the volume is the credential at risk.** An agent that is
  prompt-injected can reach the internet, so it can leak whatever its volume
  holds — the same exposure as any Claude Code installation. Repository access
  is therefore given per project with scoped tokens, never with a personal
  key, and nothing in the cluster is reachable from the pod.
- **The subscription's rate limit is shared by every instance.** That, not
  node memory, is the real ceiling on concurrent sessions.
- **Verified on node01 the day this was written:** the pod started under the
  restricted profile with user namespaces on, the network policy rejected the
  API server while GitHub answered, and a session served from the pod answered
  from a phone.
