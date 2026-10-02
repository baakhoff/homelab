# codex-agent image

The container image for `clusters/lab/agents/codex.yaml`: Node, OpenAI's Codex
CLI at a pinned version, git with `gh`, Python with `uv`, and an entrypoint
that waits for a login and then runs the Codex app-server with remote control
on, so the pod shows up in the ChatGPT app. Bootstrap:
[the runbook](../../docs/runbooks/agent-pods.md#the-codex-pod).

It is built and tagged exactly like [claude-agent](../claude-agent/README.md),
whose README has the reasoning:

- `.github/workflows/codex-agent-image.yml` builds this directory on every push
  to `main` that touches it, and publishes
  `ghcr.io/baakhoff/codex-agent:<codex-version>`, read from
  `ARG CODEX_VERSION=` in the Dockerfile.
- Renovate bumps that ARG (npm datasource, regex manager in `renovate.json5`),
  and then offers the published tag to the Deployment. Two PRs per release.
- The tag is mutable, because a `gh` bump rebuilds it without a new Codex
  version. That is why the Deployment pulls `Always`.
- The package must be public, because the cluster pulls anonymously. The
  workflow's source label links it to this repository, and it inherits the
  repository's visibility.
