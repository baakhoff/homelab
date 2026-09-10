# 0005 — The Pi is the house DNS and the tailnet's door, outside the cluster

- Status: accepted
- Date: 2026-09-10

## Context

The Raspberry Pi 3B+ was originally going to join the cluster as a tainted k3s
agent, for the multi-node lesson. Two things changed that.

First, three amd64 mini PCs arrived. Any multi-node mechanics worth learning
are better learned on nodes that can actually run something; a 1 GB arm64
board adds a scheduling curiosity, not a lesson.

Second, two jobs turned out to be needed that a cluster must never host for
itself:

- **Name resolution for the house.** node01 reboots during experiments. k3s
  upgrades, Flux prunes and Incus restarts are routine there. DNS for the
  household has to survive all of that, so it cannot live on the machine being
  experimented on.
- **A way in when a node's OS is dead.** Tailscale on a node reaches that node
  while its OS runs. The mini PCs' management engine (Intel AMT), the router
  and the switch are LAN-only by design, so reaching them from outside needs
  something on the LAN that advertises the subnet — and that something should
  be the most boring box in the room.

The exit-node role rides along at no cost: full-tunnel through home from public
Wi-Fi, at whatever throughput a 3B+ can push.

## Decision

The Pi 3B+ runs **standalone, outside the cluster**, as hostname `exitnode`,
with three roles:

1. **Pi-hole** — forwarding DNS with blocklists, upstream Quad9 (filtered,
   DNSSEC), serving the LAN through the router's DHCP and the tailnet through
   Tailscale's global nameserver override.
2. **Tailscale subnet router** for the LAN's /22, plus **Tailscale SSH**, so
   LAN-only management surfaces are reachable from any tailnet device and the
   Pi itself stays reachable even with a broken sshd config.
3. **Tailscale exit node.**

Pi-hole was picked over AdGuard Home; the two are equivalent for these
purposes and the choice was taste.

The Pi is the **only** resolver the router hands out. Router-as-secondary was
rejected: clients round-robin across resolvers, so half the queries would skip
blocking, and a DNS outage would become intermittent instead of obvious.

Servers — `node01`, the workbench container, every node that follows — run
`tailscale set --accept-dns=false` and carry their own explicit nameservers,
so a dead Pi cannot blind the cluster or its alerting.

The Pi is **disposable**: nothing on it is backed up, log2ram spares the SD
card, and a runbook rebuilds it from a blank card.

The k3s-agent act is dropped. Nothing a node needs in order to boot or to
reach storage runs here — no k3s, no Ceph, nothing in any data path.

## Consequences

- **The house depends on one Pi for names.** If it dies, the household loses
  DNS until the router's DNS field is set back to automatic — a two-minute
  manual step, written into the disaster-recovery runbook. The mitigation is
  procedural, not automatic, and that is accepted.
- **Tailnet devices carrying the DNS override depend on it too**, wherever
  they are. Same rollback: the override switch in the Tailscale console.
- **Order of operations is a rule now.** The router's DNS field changes last,
  after the resolver has proven it stays up where it lives. The build broke
  this rule once and took the house's DNS down for a few minutes.
- **Wi-Fi is the weak link.** The Pi reaches the LAN over 2.4 GHz Wi-Fi. The
  3B+ radio mishandles the mesh's 5 GHz band steering, and keeps a dead
  association after the router applies a settings change. Power saving is off
  and the band is pinned to 2.4 GHz; after any router settings save the Pi is
  checked and reconnected if needed. Exit-node throughput is a few Mbit/s,
  which DNS and a management console never notice.
- **The subnet route exposes the whole LAN to the tailnet.** Every tailnet
  device reaches every LAN address. On a single-user tailnet that is the
  intended effect; Tailscale ACLs are the tool for narrowing it.
- **Pi-hole listens on every interface**, which is safe only because the Pi
  sits behind NAT with nothing forwarded. Port 53 must never be exposed.
- **DNS-level ad blocking has known gaps** — first-party ad paths and cosmetic
  elements are not DNS-blockable. A browser extension covers those per device.
