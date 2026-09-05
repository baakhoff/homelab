#!/usr/bin/env bash
#
# Nightly restic backup of node01 to object storage.
#
# WHAT THIS PROTECTS AGAINST: node or disk death. Everything on this machine
# shares one ext4 root LV - k3s state, containerd images, the Incus dir pool and
# every local-path PVC - so a dead NVMe takes all of it at once, OS included.
# Incus snapshots do not help with that: they sit on the same disk.
#
# WHAT IT DELIBERATELY DOES NOT COVER: fat-finger recovery inside a container.
# `incus snapshot` restores that in seconds instead of minutes over the
# internet. The two layers are complementary, not competing - keep both.
#
# CONSISTENCY - READ THIS BEFORE TRUSTING A RESTORE:
# This walks the LIVE filesystem. Databases inside the Incus containers
# (analytix's Postgres/ClickHouse/MinIO, epicurus's Postgres) are copied while
# running, so what lands in the repo is CRASH-CONSISTENT - the state they would
# be in after a power cut. Every one of those engines is built to survive that
# by replaying its write-ahead log, so it is a supported starting point rather
# than corruption.
#
# What it is NOT is ATOMIC. restic reads files one at a time over several
# minutes, so a file can change between the start and the end of the walk.
# restic reports those as "file changed while reading" warnings - grep the
# journal for them rather than assuming they did not happen.
#
# What would make it atomic is a copy-on-write storage pool (btrfs/zfs), where
# `incus snapshot` is instant and costs nothing, so you snapshot, back up the
# frozen snapshot and delete it. This pool is `dir`, where a snapshot is a full
# 58G copy - correct but too expensive to take nightly. Shipping the
# crash-consistent version was the deliberate call: without it a dead NVMe
# loses the workbench entirely, and that is the larger risk by far.
#
# CREDENTIALS come from /etc/restic/backup.env (root-owned, 0600), loaded by
# systemd via EnvironmentFile. Nothing secret is in this file or in git.
#
set -Eeuo pipefail

EXCLUDES="${RESTIC_EXCLUDES:-/etc/restic/excludes.txt}"

# Written fresh each run, backed up, then removed. See dump_inventory().
INVENTORY="$(mktemp -d /var/tmp/node01-inventory.XXXXXX)"

# ---------------------------------------------------------------------------
# Reporting
#
# The single most common way a homelab backup fails is silently: the timer
# stops firing and nobody notices for four months. A metric emitted by this
# script cannot catch that, because a script that never runs emits nothing.
# An external check that expects to hear from us can.
#
# Every ping is best-effort - a healthchecks.io outage must never turn a
# successful backup into a failed one, hence the `|| true`.
# ---------------------------------------------------------------------------
hc() {
  [ -n "${HC_URL:-}" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${HC_URL}${1:-}" || true
}

finish() {
  local rc=$?
  rm -rf "$INVENTORY"
  # healthchecks.io treats /0 as success and /1../255 as failure, so the exit
  # status carries straight through and the dashboard shows WHY it failed.
  hc "/$rc"
  exit "$rc"
}
trap finish EXIT

log() { printf '==> %s\n' "$*"; }

# ---------------------------------------------------------------------------
# Inventory
#
# Incus keeps its own state in a dqlite database that is being written while we
# read it, so the file-level copy of /var/lib/incus/database that lands in the
# repo is not something to stake a restore on. These text dumps are the path
# that actually works: they let you recreate an instance with the right limits,
# devices and profiles, and then put the rootfs back underneath it.
#
# All of it is small - kilobytes - and it dedups to nothing between runs.
# ---------------------------------------------------------------------------
dump_inventory() {
  log "collecting host inventory"

  incus list --format yaml           > "$INVENTORY/incus-instances.yaml"
  incus storage list --format yaml   > "$INVENTORY/incus-storage.yaml"

  while read -r inst; do
    [ -n "$inst" ] || continue
    incus config show "$inst" --expanded > "$INVENTORY/incus-config-${inst}.yaml"
  done < <(incus list --format csv --columns n)

  # `profile list` and `network list` do not take --columns the way `list` does,
  # so the first CSV field is taken by hand. Both `show` calls are guarded:
  # `network list` includes unmanaged host interfaces that `show` refuses, and
  # losing one optional dump is never a reason to fail the whole backup.
  while read -r prof; do
    [ -n "$prof" ] || continue
    incus profile show "$prof" > "$INVENTORY/incus-profile-${prof}.yaml" 2>/dev/null || true
  done < <(incus profile list --format csv 2>/dev/null | cut -d, -f1)

  while read -r net; do
    [ -n "$net" ] || continue
    incus network show "$net" > "$INVENTORY/incus-network-${net}.yaml" 2>/dev/null || true
  done < <(incus network list --format csv 2>/dev/null | cut -d, -f1)

  # Rebuilding node01 means reinstalling k3s, incus, tailscale, sing-box and
  # the rest. This is the list of what was here - a reference, not a promise
  # that `dpkg --set-selections` will reproduce it.
  dpkg --get-selections > "$INVENTORY/dpkg-selections.txt"

  # So a restore does not silently land on a different kernel or OS major.
  { uname -a; echo; cat /etc/os-release; } > "$INVENTORY/system.txt"

  # Which local-path PVC directory belongs to which workload. The directory
  # names encode it (pvc-<uuid>_<namespace>_<name>) but only while you can
  # still read them; this survives into the backup as plain text.
  ls -1 /var/lib/rancher/k3s/storage 2>/dev/null > "$INVENTORY/local-path-pvcs.txt" || true
}

# ---------------------------------------------------------------------------
# What gets backed up
#
# DEFAULT-INCLUDE WITH AN EXCLUDE LIST, on purpose. An include list fails by
# silently not backing up the thing you added last month; the exclude form
# catches every future service's PVC without anyone having to remember.
#
# NOT here, because git already holds it better: every Kubernetes object in the
# cluster. Flux rebuilds all of it from main given the age key. See
# docs/runbooks/disaster-recovery.md.
# ---------------------------------------------------------------------------
backup_paths=(
  # Host configuration: netplan, sshd, systemd units (including epicurus's
  # reconcile timer), incus daemon config, unattended-upgrades.
  /etc

  # The Incus pool - the two containers ARE the payload. 58G of workbench and
  # epicurus data that exists nowhere else. Includes epicurus's root .env,
  # which holds the Postgres and MinIO passwords its data directory was
  # INITIALISED with: lose that file and the bytes are unreadable even though
  # you still have them. That is the argument for backing up whole
  # filesystems rather than curated paths.
  /var/lib/incus

  # k3s server state: the CA and node token (so an existing kubeconfig and any
  # joined agent still work after a restore), the bundled manifests, and
  # server/db - the SQLite store holding every Kubernetes object.
  #
  # That database is a FALLBACK, not the restore path. The intended rebuild is
  # k3s -> sops-age by hand -> flux bootstrap, which reconstructs the cluster
  # from git; restoring a live-copied SQLite file risks a torn read and brings
  # back stale objects on top of a GitOps repo that is the source of truth.
  # It is a few hundred MB, so keeping the option costs nothing - and it is the
  # only thing that preserves PV uuids, which is what makes local-path PVC
  # directory names line up again. See the recovery runbook.
  #
  # /var/lib/rancher/k3s/agent is NOT listed: it is containerd's image cache,
  # every layer of which is re-pullable, and it churns.
  /var/lib/rancher/k3s/server

  # Every local-path PVC. Two are excluded in excludes.txt; everything else,
  # present and future, is caught here.
  /var/lib/rancher/k3s/storage

  # Root's own dotfiles and anything left in /root by a past session.
  /root
)

main() {
  log "restic backup starting"
  restic version

  dump_inventory

  log "backing up"
  # --tag lets `restic snapshots --tag nightly` separate these from any
  # hand-made snapshot taken before something risky.
  #
  # EXIT CODE 3 IS NOT A FAILURE HERE, and treating it as one is the trap this
  # block exists to avoid. restic returns 3 when the snapshot was saved but
  # some source files could not be read. On this host that is the NORMAL
  # STEADY STATE, not an anomaly: ClickHouse inside the `agents` workbench
  # merges MergeTree parts continuously, so restic lists a directory, and by
  # the time it stats the entries some of them have been merged away and
  # deleted. The first run hit ten of them.
  #
  # Left unhandled, `set -e` kills the script on a perfectly good backup and
  # the heartbeat reports FAILED every single night. An alarm that cries wolf
  # nightly is worse than no alarm - it trains you to ignore the one that
  # matters. Same lesson as the four permanently-red scrape targets in #11.
  #
  # What it does NOT mean is that the backup is complete. The vanished files
  # are absent from the snapshot, and for a database that is a real (if
  # usually recoverable) gap - see the consistency note at the top of this
  # file. The warning is loud in the journal on purpose.
  set +e
  restic backup \
    --exclude-file="$EXCLUDES" \
    --exclude-caches \
    --tag nightly \
    --tag node01 \
    "${backup_paths[@]}" \
    "$INVENTORY"
  local rc=$?
  set -e

  case "$rc" in
    0)
      log "backup complete, all sources read"
      ;;
    3)
      log "WARNING: snapshot saved, but some files vanished mid-walk (restic exit 3)."
      log "WARNING: expected for ClickHouse part merges; grep this unit's journal"
      log "WARNING: for 'no such file' to see which paths, and read them."
      ;;
    *)
      log "restic backup FAILED with exit $rc"
      return "$rc"
      ;;
  esac

  log "repository stats"
  restic stats --mode raw-data latest || true

  log "done"
}

main "$@"
