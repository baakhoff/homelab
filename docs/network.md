# The network

How the lab is wired and addressed. Written after the wired backbone went in;
everything here describes what exists.

## Shape

A TP-Link Deco mesh does routing, DHCP and NAT for the house. One of its LAN
ports feeds an eight-port managed switch, and everything in the lab hangs off
that switch. The workstation and phones stay on Wi-Fi.

```
internet ── Deco mesh ──┬── Wi-Fi ── workstation, phones
                        │
                        └── TL-SG108E ──┬── node02
                                        ├── node03
                                        ├── node04
                                        └── exitnode (Pi)
```

Node-to-node traffic never leaves the switch, which is what matters for etcd
and, later, Ceph. Anything reaching the internet or the workstation crosses the
mesh.

## Addressing

The LAN is a **`/22`** — `192.168.68.0` through `192.168.71.255`, mask
`255.255.252.0`, gateway `192.168.68.1`. That is 1022 usable addresses, and it
is worth stating explicitly because two of its properties trip people who
assume a `/24`:

- The broadcast address is **`192.168.71.255`**, not `192.168.68.255`.
- `192.168.69.x`, `192.168.70.x` and `192.168.71.x` are the same subnet, not
  neighbours.

Three mechanisms, chosen per device rather than by habit:

| Range | Mechanism | For |
|---|---|---|
| `192.168.68.2` – `.49` | **static, configured on the device** | things with no OS to configure, which must stay reachable when DHCP is the thing that broke |
| `192.168.68.50` – `192.168.71.250` | **DHCP pool** | clients — phones, laptops, everything transient |
| inside the pool | **DHCP reservation** | machines with an OS: the address is pinned centrally, so a rebuilt machine lands on it with no host-side configuration at all |

The rule that matters: **a static address must sit outside the pool.** Inside
it, the server will eventually hand the same address to a laptop, and the
resulting outage arrives weeks later with nothing to connect it to.

| Host | Address | How |
|---|---|---|
| Deco (gateway, DHCP, DNS forwarder) | `192.168.68.1` | fixed |
| Switch management | `192.168.68.2` | static on the device |
| `exitnode` (Pi) | `192.168.68.65` | reservation |
| `node02` | `192.168.68.102` | reservation |
| `node03` | `192.168.68.103` | reservation |
| `node04` | `192.168.68.104` | reservation |
| `node01` (laptop) | DHCP | Wi-Fi, no reservation — it retires when the cluster takes over |

### Reservations and Ubuntu

A DHCP reservation is usually described as pinning an address to a MAC, but
servers match on the client-identifier option when the client sends one — and
`systemd-networkd` sends one by default, derived from `/etc/machine-id` rather
than from the hardware. The reservation then never matches, the machine comes
up on a pool address, and nothing is visibly broken.

Every node therefore carries `dhcp-identifier: mac` in its netplan, which makes
the request identify itself the way the router's UI implies. See
[`hosts/nodes/`](../hosts/nodes/).

## The switch

TL-SG108E, hardware V6, eight ports, gigabit, web-managed.

Firmware was upgraded before anything was configured — the factory build
predated a security fix to the Easy Smart management protocol, and doing it
first meant a settings reset during the upgrade would have cost nothing.
**Upgrade through the web UI only.** The Easy Smart Configuration Utility is
the documented way people brick these.

| Port | Device |
|---|---|
| 1 | uplink to the Deco |
| 2 | `node02` |
| 3 | `node03` |
| 4 | `node04` |
| 5 | `exitnode` |
| 6–8 | free |

VLANs, QoS, IGMP snooping and loop prevention are at defaults. Flat network
first.

Because its address is static, the switch does not appear in the router's
client list — nothing ever asks the router for anything on its behalf. This
page is its inventory entry.

Two features that earn their keep:

- **Port Setting** shows link state and negotiated speed per port. When a
  machine is unreachable, "does the port have link, and at what speed?" splits
  the problem in two before any other guessing: no link is physical, link at
  full speed means the fault is above layer 2.
- **Cable Test** reports pair status and distance to a fault, which catches a
  cheap patch lead that works at 100 Mbit/s but not at gigabit.

## Reaching it from outside

Nothing is forwarded from the internet. Remote access is Tailscale, and the Pi
is the door: it advertises `192.168.68.0/22` as a subnet router, so every
tailnet device reaches every LAN address — the switch's web UI, the Deco's, the
nodes' management engines.

Devices on the LAN need no configuration for this. Tailscale translates
subnet-routed traffic to the subnet router's own address by default, so a
device sees the request arriving from `192.168.68.65`, an address on its own
subnet, and replies normally. No default gateway, no route to `100.64.0.0/10`,
no awareness that Tailscale exists.

macOS, Windows, iOS and Android accept advertised routes by default; **Linux
does not** — `sudo tailscale set --accept-routes`. Avoid enabling it on a
machine that already sits on the LAN, which would route local traffic the long
way round.

The security posture this implies is deliberate. The switch's UI is HTTP with
no TLS and a single shared password; a management engine is a whole computer
below the operating system. Both are acceptable on an authenticated, encrypted
tailnet and unacceptable exposed to the internet. The devices are not hardened
— access to them is.

## Names instead of addresses

Pi-hole serves the house through the router's DHCP and the tailnet through
Tailscale's DNS override, so a **Local DNS Record** there resolves from the
desk, from a phone on mobile data, and from anywhere on the tailnet:

| Name | Address |
|---|---|
| `switch.lab` | `192.168.68.2` |
| `node02.lab` | `192.168.68.102` |
| `node03.lab` | `192.168.68.103` |
| `node04.lab` | `192.168.68.104` |

Machines on the tailnet have MagicDNS names already and do not need records.

## Waking the lab

The nodes' firmware has Wake-on-LAN enabled. A magic packet is a link-local
broadcast and broadcasts do not route, so it has to be sent by something on the
same segment — the Pi, which is wired to the switch, always on, and reachable
over the tailnet:

```
ssh <user>@exitnode wake-nodes
```

See [`hosts/exitnode/`](../hosts/exitnode/).
