# Codex agent image. One pod runs it in the `agents` namespace and serves Codex
# remote-control sessions to the ChatGPT app - the OpenAI counterpart of the
# claude-agent image beside it. How the pod is bootstrapped:
# docs/runbooks/agent-pods.md. How this image is built: README.md beside this
# file.
#
# The same shape as claude-agent on purpose: a Node base, the CLI from npm at a
# pinned version, the unprivileged `node` user, no firewall script (the
# namespace's NetworkPolicy does that job). Its toolchain is a subset of
# claude-agent's, and each line there says why it is there.

# Renovate's dockerfile manager watches this line.
FROM node:24-bookworm-slim

# Pinned, and bumped by Renovate through the regex manager in renovate.json5
# (npm datasource). The CI workflow reads this line to tag the image, so the
# ARG line must keep this exact shape.
ARG CODEX_VERSION=0.160.0
ARG GH_VERSION=2.101.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git openssh-client \
      python3 python3-venv build-essential \
      procps less jq unzip \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

# gh from its own release, not Debian's 2.23.0 - claude-agent's Dockerfile
# has the history of what the stale one broke.
RUN set -eux; \
    curl -fsSL -o /tmp/gh.tar.gz \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz"; \
    tar -xzf /tmp/gh.tar.gz -C /tmp "gh_${GH_VERSION}_linux_amd64/bin/gh"; \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh; \
    rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_amd64"; \
    gh --version

# `codex --version` is the guard that the npm package brought its Linux
# binary along; it ships per platform as an optional dependency.
RUN npm install -g "@openai/codex@${CODEX_VERSION}" \
 && npm cache clean --force \
 && codex --version

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# The pod mounts its PersistentVolume over /home/node, so CODEX_HOME - the
# login, config.toml, sessions, the remote-control socket - and ~/work survive
# restarts and parking. Anything written elsewhere does not.
ENV HOME=/home/node \
    CODEX_HOME=/home/node/.codex

USER node
WORKDIR /home/node
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
