# Claude Code agent image. One of these runs per project in the `agents`
# namespace and serves Remote Control sessions to claude.ai/code and the Claude
# app. How a pod is bootstrapped: docs/runbooks/agent-pods.md. How this image is
# built and published: README.md beside this file.
#
# Modelled on Anthropic's reference dev container
# (github.com/anthropics/claude-code, .devcontainer/Dockerfile): a Node base
# image, the CLI installed from npm at a pinned version, a non-root user. Trimmed
# to what a headless server needs - no zsh, no sudo, no firewall script (the
# NetworkPolicy on the namespace does that job at the right layer).

# Renovate's dockerfile manager watches this line.
FROM node:22-bookworm-slim

# Pinned, and bumped by Renovate through the regex manager in renovate.json5
# (npm datasource). The CLI's own auto-updater is disabled below: it would try
# to write into /usr/local/lib as an unprivileged user and fail, and a version
# that changes without a commit is exactly what GitOps exists to prevent. The
# CI workflow reads this line to tag the image, so the ARG line must keep this
# exact shape.
ARG CLAUDE_CODE_VERSION=2.1.278

# The toolchain an agent can use inside its pod. Kept general on purpose: a
# project that needs more (a database client, another language) gets its own
# image FROM this one, rather than this list growing for everybody.
#   git, gh         - clone, commit, PRs (gh needs GH_TOKEN; see entrypoint.sh)
#   openssh-client  - git over ssh where a project uses a deploy key
#   netcat-openbsd  - `nc -x` as an ssh ProxyCommand, which is how a remote
#                     that is only reachable through a local SOCKS proxy gets
#                     reached from inside a pod. See the runbook; the pods have
#                     no LAN and no tailnet, so a userspace proxy is the only
#                     route to something not on the public internet.
#   python3, venv   - the Python projects; uv below does the real work
#   build-essential - native extensions in Python and Node dependencies
#   procps, less, jq, curl, unzip - an agent inspects its own environment
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git gh openssh-client netcat-openbsd \
      python3 python3-venv build-essential \
      procps less jq unzip \
 && rm -rf /var/lib/apt/lists/*

# uv: the Python package manager the Python projects use. Copied from its own
# image so the version is pinned here and Renovate bumps it like any other.
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /usr/local/bin/

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# The `node` user (uid 1000) ships with the base image. The pod mounts its
# PersistentVolume over /home/node, so everything under that path - the CLI's
# config directory with the login, the project checkouts - survives restarts
# and parking (replicas: 0). Anything written elsewhere does not.
ENV HOME=/home/node \
    CLAUDE_CONFIG_DIR=/home/node/.claude \
    DISABLE_AUTOUPDATER=1
# NOT set, deliberately: DISABLE_TELEMETRY, DO_NOT_TRACK,
# CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, DISABLE_GROWTHBOOK. Each of them
# turns off the feature-flag evaluation Remote Control depends on, and the
# server then refuses to start ("Remote Control requires feature-flag
# evaluation"). Same for ANTHROPIC_BASE_URL: Remote Control needs the API
# reached directly, never through a gateway or proxy.

USER node
WORKDIR /home/node
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
