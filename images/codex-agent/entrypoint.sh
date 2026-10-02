#!/usr/bin/env bash
# Entrypoint for the Codex agent pod.
#
# Runs the Codex app-server in the foreground with remote control on, which is
# what makes the pod show up in the ChatGPT app. It is the exact command
# `codex remote-control start` would launch as a background daemon; a pod
# wants it as PID 1 instead, so that a crash is a container restart and not a
# daemon nobody is watching.
#
# Required environment (set in the image):
#   CODEX_HOME   where the CLI keeps its login, config and state
# Optional:
#   PROJECT      the directory under ~/work it starts in; default "work"
set -euo pipefail

: "${CODEX_HOME:?CODEX_HOME must be set}"
project="${PROJECT:-work}"
case "$project" in
  */* | .*) echo "PROJECT must be a plain name, got '$project'" >&2; exit 1 ;;
esac

mkdir -p "$CODEX_HOME" "$HOME/work/$project"
cd "$HOME/work/$project"

# The login is interactive - `codex login --device-auth` prints a URL and a
# code for a browser somewhere else - so this script cannot do it. Until
# someone has, wait and say so. Output goes to /dev/null because `login
# status` prints part of an API key when that is the login in use.
while ! codex login status >/dev/null 2>&1; do
  echo "not logged in yet: exec in and run 'codex login --device-auth' (docs/runbooks/agent-pods.md)"
  sleep 60
done

# `unix://` with no path is the default control socket under CODEX_HOME, the
# one `codex remote-control pair` looks for - so pairing is a `kubectl exec`
# away while this runs.
exec codex app-server --remote-control --listen unix://
