#!/usr/bin/env bash
# Entrypoint for a Claude Code agent pod. One pod = one project.
#
# Required environment (set in the project's Deployment):
#   PROJECT           short name: the checkout directory and the session title
#   REPO_URL          what to clone on the first start
#   CLAUDE_CONFIG_DIR where the CLI keeps its login and state (set in the image)
# Optional:
#   GH_TOKEN          fine-grained GitHub token. If present, gh becomes git's
#                     credential helper so clone and push work on private repos.
#   PERMISSION_MODE   starting permission mode for the server's sessions.
#                     Default acceptEdits: file edits are automatic, shell
#                     commands still ask - and the ask reaches the phone.
set -euo pipefail

: "${PROJECT:?PROJECT must be set}"
: "${REPO_URL:?REPO_URL must be set}"
: "${CLAUDE_CONFIG_DIR:?CLAUDE_CONFIG_DIR must be set}"

work="$HOME/work/$PROJECT"
mkdir -p "$HOME/work" "$CLAUDE_CONFIG_DIR"

if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git
fi

if [ ! -d "$work/.git" ]; then
  echo "first start: cloning $REPO_URL into $work"
  git clone "$REPO_URL" "$work"
fi
cd "$work"

# The one-time bootstrap is interactive and this script cannot do it:
# `claude auth login` needs a browser round-trip, and both the workspace-trust
# dialog and Remote Control's "Enable Remote Control? (y/n)" want a person.
# Until someone has done those inside the pod and dropped the marker file,
# this waits and says so. The steps are in docs/runbooks/agent-pods.md.
marker="$CLAUDE_CONFIG_DIR/.remote-control-enabled"
while [ ! -f "$marker" ]; do
  echo "not bootstrapped yet: waiting for $marker (docs/runbooks/agent-pods.md)"
  sleep 60
done

# Server mode: no terminal UI, sessions are served to claude.ai/code and the
# Claude app. --spawn worktree gives every session started from a device its
# own git worktree, so two sessions on one project never edit the same files.
exec claude remote-control \
  --name "$PROJECT" \
  --spawn worktree \
  --permission-mode "${PERMISSION_MODE:-acceptEdits}"
