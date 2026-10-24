# 0008 — TrueNAS Community Edition on the NAS, not Ubuntu with ZFS by hand

- Status: accepted
- Date: 2026-10-24

## Context

The household NAS is its own machine, outside the k3s cluster: a Pentium Gold
G5400 on an H310 board, a 256 GB NVMe boot drive and a SATA data disk
([hardware](../hardware.md#nas--nas)). The question is what runs on it.

**The first plan was Ubuntu Server with ZFS set up by hand.** It had real
arguments. It matches the three nodes, so the NAS would be one more machine of
a kind the lab already runs. Its host files would sit in git the way
[`hosts/nodes/`](../../hosts/nodes/) does. And 26.04 ships OpenZFS 2.4.

**What was wanted instead was dedicated NAS software with a UI.** Pools,
encryption, shares, snapshots, scrubs and disk-health alerts are this machine's
whole job, and on Ubuntu every one of them is assembled and kept up by hand.

**Two further requirements narrowed the field.** The install was to be
offline, at a bench, with no network — the condition that left the nodes'
interfaces administratively down after their Ubuntu install
([node bring-up](../runbooks/node-bring-up.md)). And ZFS was wanted as the
system's own filesystem, not as an add-on.

## Decision

The NAS runs **TrueNAS Community Edition** 25.10, installed offline from USB
onto the whole NVMe.

- It is a maintained appliance, with a web UI for pools, encryption, shares,
  snapshots, scrubs, SMART alerts, Telegram alerts and cloud sync.
- It installs offline and, with no network configured, runs DHCP on every NIC —
  there is no interface left down to find later at a console.
- It is built on ZFS rather than offering it.

**OpenMediaVault was rejected.** Its install guide requires an internet
connection during installation, and ZFS on it comes only through a third-party
plugin.

**Ubuntu Server with ZFS by hand was rejected** for the reason it was
reconsidered: it is a general-purpose server, not NAS software with a UI.

## Consequences

- **The configuration is not in git.** It lives in TrueNAS's own database,
  `/data/freenas-v1.db`. The repository holds the
  [runbook](../runbooks/nas-bring-up.md) that produced it, and TrueNAS's
  configuration export is the backup of record. This is a knowing exception to
  the principle that what is not in the repo does not exist.
- **The host is an appliance, not a Linux box to customise.** The root
  filesystem is read-only and apt is disabled. Nothing gets installed on it the
  way packages go onto the nodes.
- **The NVMe is the boot pool and nothing else.** TrueNAS takes the whole
  256 GB drive, so nothing else can live on it — object-storage metadata, for
  one.
- **No OIDC login in 25.10.** Pocket ID can only sit in front of the UI as a
  gate, with TrueNAS's own local login still behind it: two logins where the
  cluster's services have one.
- **No object storage** in this setup.
- **The pool upgrade button is not pressed casually.** ZFS feature flags are
  one-way. Once enabled, they block importing the pool into any OpenZFS version
  that lacks them, including the one in an earlier boot environment: rolled
  back to it, TrueNAS could not import its own pool.
