# claude-agent image

The container image for the agent pods in `clusters/lab/agents/`: Node, the
Claude Code CLI at a pinned version, git and `gh`, Python with `uv`, and an
entrypoint that runs `claude remote-control` — in a project it clones, or in an
empty directory you clone into yourself. What the pods are and how one is
bootstrapped: [the runbook](../../docs/runbooks/agent-pods.md).

## Two shapes of pod, one entrypoint

`REPO_URL` is optional. With it, the pod clones that repo on first start and
serves sessions from it, each in its own git worktree. Without it, the pod is a
**general slot**: it comes up with an empty `~/work`, and you clone whatever you
want from inside a session.

The difference costs one feature and buys another.

What a general slot gives up is `--spawn worktree`, which needs a repository at
the working directory to branch from. Sessions in a slot share one directory, so
two at once can edit the same files. A slot that settles into one project earns
it back by gaining a `REPO_URL` — a one-line edit to its Deployment, after which
the clone is already on the volume.

What it buys is that **nothing about the work is published**. `REPO_URL` and
`PROJECT` are plain environment variables in a Deployment; this repository is
public, so a named pod discloses the project's name and the existence of its
repo, permanently and including in history. Encryption does not help — SOPS
covers `data`/`stringData` in a Secret, not an env var in a Deployment. An
anonymous slot plus `gh auth login` *inside* the pod discloses neither, and
needs no per-repo token: the login lands on the volume at `~/.config/gh`, which
is the PVC, so it survives restarts exactly like the Claude login does.

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

## Visibility

The cluster pulls this image anonymously: there is no image-pull secret, so the
package must be **public**. This image holds nothing secret, so that is fine.

The first build published it public without any manual step: the workflow's
`org.opencontainers.image.source` label links the package to this repository,
and the package took the repository's visibility. Check the package page after
the first build of any new image all the same. If it shows Private, change it:
GitHub → your profile → Packages → the package → Package settings → Danger
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
