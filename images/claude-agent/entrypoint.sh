#!/usr/bin/env bash
# Entrypoint for a Claude Code agent pod. One pod = one slot.
#
# Required environment (set in the slot's Deployment):
#   PROJECT           short name: the checkout directory and the session title
#   CLAUDE_CONFIG_DIR where the CLI keeps its login and state (set in the image)
# Optional:
#   REPO_URL          a repo to clone on the first start. Omit it for a GENERAL
#                     slot: the pod comes up with an empty ~/work and you clone
#                     whatever you want from inside a session. See the runbook
#                     for what that costs - it is the worktree spawn, below.
#   GH_TOKEN          fine-grained GitHub token. If present, gh becomes git's
#                     credential helper so clone and push work on private repos.
#                     A general slot usually wants `gh auth login` inside the
#                     pod instead: it persists on the volume, covers every repo
#                     the account can see, and puts no repo name in this repo.
#   PERMISSION_MODE   starting permission mode for the server's sessions.
#                     Default acceptEdits: file edits are automatic, shell
#                     commands still ask - and the ask reaches the phone.
set -euo pipefail

: "${PROJECT:?PROJECT must be set}"
: "${CLAUDE_CONFIG_DIR:?CLAUDE_CONFIG_DIR must be set}"

# PROJECT names a directory under ~/work and is used to clean up after a failed
# clone, so it has to be a plain name. Rejected here rather than assumed safe
# further down, where the check would be a comment instead of a check.
case "$PROJECT" in
  */* | .*) echo "PROJECT must be a plain name, got '$PROJECT'" >&2; exit 1 ;;
esac

mkdir -p "$HOME/work" "$CLAUDE_CONFIG_DIR"

if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git
fi

if [ -n "${REPO_URL:-}" ]; then
  work="$HOME/work/$PROJECT"
  if [ ! -d "$work/.git" ]; then
    echo "first start: cloning $REPO_URL into $work"
    # A failed clone must not kill the pod. Under `set -e` it would, and the
    # pod would CrashLoopBackOff on the one thing you cannot fix from outside:
    # the bootstrap below is interactive and needs a running container to
    # `kubectl exec` into. A private repo with no GH_TOKEN fails exactly here,
    # and the fix - `gh auth login` inside the pod - is unreachable if the pod
    # is not up. So warn, fall back, and retry on the next restart.
    if ! git clone "$REPO_URL" "$work"; then
      echo "clone FAILED: $REPO_URL"
      echo "  the pod stays up so you can fix it. Most likely the repo is"
      echo "  private and this pod has no credentials: exec in, run"
      echo "  'gh auth login', then restart the pod and the clone is retried."
      # Clear the half-written directory so the retry is not refused with
      # "already exists and is not an empty directory". Safe because PROJECT is
      # a validated plain name, so $work is exactly one level under ~/work.
      rm -rf -- "$work"
      work="$HOME/work"
    fi
  fi
else
  # No repo pinned: the slot starts in the parent directory and whatever is
  # cloned in later lives beside it. Deliberately NOT auto-detecting a single
  # checkout and adopting it - that would make the server's working directory
  # depend on what is on the volume, and change silently the day a second repo
  # is cloned.
  echo "no REPO_URL: general slot, starting in $HOME/work"
  work="$HOME/work"
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

# --spawn worktree gives every session started from a device its own git
# worktree, so two sessions on one project never edit the same files. It needs
# a repository at the working directory to branch from, which a general slot
# does not have, so it is passed only when there is one. A slot that settles
# into one project earns it back by gaining a REPO_URL - a one-line edit to its
# Deployment, after which the clone is on the volume already.
spawn=()
if [ -d "$work/.git" ]; then
  spawn=(--spawn worktree)
fi

# Server mode: no terminal UI, sessions are served to claude.ai/code and the
# Claude app.
exec claude remote-control \
  --name "$PROJECT" \
  "${spawn[@]}" \
  --permission-mode "${PERMISSION_MODE:-acceptEdits}"
