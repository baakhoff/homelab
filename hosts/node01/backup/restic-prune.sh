#!/usr/bin/env bash
#
# Weekly retention pass and integrity check.
#
# Kept separate from the nightly backup on purpose. `prune` is the expensive
# operation - it rewrites pack files and is the only thing here that DELETES -
# so it runs once a week rather than competing with the backup every night, and
# a failure in it never marks the backup itself as failed.
#
# CREDENTIALS come from /etc/restic/backup.env via systemd's EnvironmentFile.
#
set -Eeuo pipefail

hc() {
  [ -n "${HC_PRUNE_URL:-}" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${HC_PRUNE_URL}${1:-}" || true
}

finish() {
  local rc=$?
  hc "/$rc"
  exit "$rc"
}
trap finish EXIT

log() { printf '==> %s\n' "$*"; }

log "applying retention policy"
# Roughly a year of coverage that gets coarser as it ages, which is how
# recovery actually works: you want yesterday at fine grain and last spring at
# all. Snapshots are grouped by host+paths by default, so a hand-made backup of
# a different path set gets its own retention rather than being swept up here.
#
# --keep-tag keep: anything tagged `keep` is never forgotten. That is the
# escape hatch for a deliberate "before I touch something risky" snapshot,
# mirroring why snapshots.expiry.manual is left unset on the Incus side.
restic forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 6 \
  --keep-tag keep \
  --prune

log "verifying repository integrity"
# Structural check plus an actual re-read of 5% of the pack data, which is the
# only thing that catches silent corruption at the provider - a repo can list
# and index perfectly while a pack file has rotted underneath it.
#
# 5% a week means full coverage in about five months. It costs egress: 5% of
# the repo per run, which at this size is a rounding error against the included
# monthly traffic.
restic check --read-data-subset=5%

log "done"
restic stats --mode raw-data || true
