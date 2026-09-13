# claude-agent image

The container image for the agent pods in `clusters/homelab/agents/`: Node,
the Claude Code CLI at a pinned version, git and `gh`, Python with `uv`, and an
entrypoint that clones a project and runs `claude remote-control` in it. What
the pods are and how one is bootstrapped: [the runbook](../../docs/runbooks/agent-pods.md).

## How it is built

`.github/workflows/claude-agent-image.yml` builds this directory on every push
to `main` that touches it, and publishes to
`ghcr.io/baakhoff/claude-agent:<claude-code-version>`. The tag is the CLI
version read from the `ARG CLAUDE_CODE_VERSION=` line in the Dockerfile.

Nothing is built locally and nothing is pushed by hand. The image a pod runs is
always one that a merged commit produced.

## Why the tag is the CLI version

So that updates flow through Renovate in two ordinary PRs:

1. Renovate bumps `ARG CLAUDE_CODE_VERSION` in the Dockerfile (npm datasource,
   regex manager in `renovate.json5`). Merging builds and pushes the new tag.
2. Renovate sees the new tag on GHCR and offers it to the Deployments that pin
   the image (kubernetes manager, docker datasource). Merging deploys.

The trade, worth knowing: a Dockerfile change **without** a version bump
rebuilds the same tag, and a pod that already runs it keeps the old image
until it is restarted (`imagePullPolicy: IfNotPresent`). When the image must
change for a reason other than a CLI release, bump the version anyway or
restart the pods after the build.

## First publish

GHCR creates a new package as **private**, and a private package needs an
image-pull secret in the cluster. This image holds nothing secret, so after the
first successful build make the package public instead:
GitHub → your profile → Packages → `claude-agent` → Package settings → Danger
zone → Change visibility → Public. Once. Every later build lands in the same
package.

## What is deliberately not in it

- **No Docker.** Projects whose tests need a Docker daemon are not served by
  this image yet.
- **No sudo, no package installs at runtime.** The pod runs unprivileged with
  every capability dropped. A project that needs more tooling gets its own
  image `FROM` this one.
- **No telemetry opt-outs.** `DISABLE_TELEMETRY`, `DO_NOT_TRACK`,
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` and `DISABLE_GROWTHBOOK` each
  switch off the feature-flag evaluation that Remote Control needs to start.
