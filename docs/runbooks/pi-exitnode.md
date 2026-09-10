# exitnode — the Pi 3B+ build

How the Pi became the house's DNS server and the tailnet's door, in the order
that worked. Written after the build; the detours that cost an evening are
folded in as rules rather than retold.

Why these roles, and why on this box: [ADR 0005](../decisions/0005-pi-house-dns-and-tailnet-door.md).

The Pi is disposable. Nothing on it is backed up; this page plus a blank card
rebuilds it in about an hour.

---

## Parts

- Raspberry Pi 3B+ with the official 5 V / 2.5 A supply.
- SanDisk Extreme 32 GB microSDHC (A1 / V30). Card quality is the single
  biggest factor in a Pi's lifespan.
- Raspberry Pi OS Lite, 64-bit, on the Debian 13 ("trixie") base.

## Network facts used below

| What | Value |
|---|---|
| LAN | `192.168.68.0/22`, router `192.168.68.1`, DHCP from the router |
| The Pi | `192.168.68.65`, a DHCP reservation on its Wi-Fi interface |
| Upstream DNS | Quad9 filtered with DNSSEC — `9.9.9.9`, `149.112.112.112` |

---

## 1. Image the card

Raspberry Pi Imager → Raspberry Pi OS Lite (64-bit). In the customisation
dialog: hostname `exitnode`, a user, Wi-Fi credentials, locale, SSH enabled.

On the Debian 13 image these settings are applied on **first boot by
cloud-init**, not written into the image. Two consequences that bit:

- First boot ends on the console with `completed socket interaction for boot
  stage final`. That is cloud-init finishing, not a hang.
- After an unclean power-off, cloud-init re-ran on the next boot and **dropped
  the Wi-Fi profile it had created**: `nmcli connection show` listed only the
  wired profile and `wlan0` sat disconnected. Section 7 disables cloud-init's
  networking for good. Until then, and as a habit after: `sudo poweroff`
  before pulling the plug.

If the Wi-Fi profile is ever missing, recreate it at the console:

```
sudo nmcli --ask device wifi connect "<SSID>"
```

`--ask` prompts for the password instead of taking it on the command line, so
it stays out of the shell history.

## 2. Find it and get in

From the workstation:

```bash
sudo nmap -sn 192.168.68.0/22 | grep -B2 -i raspberry
```

mDNS (`exitnode.local`) was unreliable from the workstation; the address is the
dependable handle. Reserve it on the router before doing anything else so the
address survives rebuilds.

```bash
ssh <user>@192.168.68.65
```

## 3. SSH: keys only

Push the workstation key, then close password login with the drop-in from
`hosts/exitnode/00-hardening.conf`.

```bash
ssh-copy-id <user>@192.168.68.65
```

On the Pi:

```
sudo install -m 0644 00-hardening.conf /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t && sudo systemctl reload ssh
```

The `00-` prefix is load-bearing. sshd keeps the **first** value it reads for
a keyword, and the `Include /etc/ssh/sshd_config.d/*.conf` line sits at the
top of the main config, so the drop-in that sorts first wins over both the main
file and every other drop-in. A file named `hardening.conf` loses to the
image's own `50-cloud-init.conf`, which turns password authentication back on.

Test from the workstation, in this order: key login works; then a forced
password attempt is refused.

```bash
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password <user>@192.168.68.65
```

Expected: `Permission denied (publickey)`. Never run the second test before
the first has passed — locking yourself out of a headless box means the
keyboard and screen come out again.

## 4. log2ram

Pi OS writes logs to the card continuously; log2ram mounts `/var/log` in RAM
and flushes it to the card daily and at shutdown. The package comes from its
maintainer's repository (azlux), where the suite name is the Debian codename:

```
echo "deb [signed-by=/usr/share/keyrings/azlux-archive-keyring.gpg] http://packages.azlux.fr/debian/ trixie main" | sudo tee /etc/apt/sources.list.d/azlux.list
sudo wget -O /usr/share/keyrings/azlux-archive-keyring.gpg https://azlux.fr/repo.gpg
sudo apt update && sudo apt install log2ram
sudo reboot
```

After the reboot:

```
systemctl status log2ram
df -h /var/log
```

Expected: `active`, and `/var/log` on a 128 MB tmpfs.

## 5. Pi-hole

```
curl -sSL https://install.pi-hole.net -o pihole-install.sh && sudo bash pihole-install.sh
```

Choices made in the installer: interface `wlan0`; upstream Quad9 (filtered,
DNSSEC); the default blocklist; web interface and query logging on. Then set
the admin password:

```
pihole setpassword
```

Pi-hole v6 listens only on the LAN interface by default. The tailnet's queries
arrive on `tailscale0`, so the listening mode has to be widened:

```
sudo pihole-FTL --config dns.listeningMode ALL
```

This is safe **only because the Pi sits behind NAT with nothing forwarded**.
Port 53 open to the internet is an amplification relay; never forward it.

Blocklists were added in the admin UI (Lists), both in adblock format via
jsDelivr, then gravity rebuilt:

| List | URL |
|---|---|
| Hagezi Pro++ | `https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.plus.txt` |
| Hagezi Threat Intelligence Feed | `https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/tif.txt` |

```
pihole -g
```

Hagezi's multi-tier lists already fold in the regional lists for most
languages, so nothing regional needs adding on top. Expect a larger gravity
database and slower `pihole -g` runs on a 3B+; false positives are allowlisted
from the query log.

Verify **on the Pi**, against Pi-hole directly:

```
dig @127.0.0.1 doubleclick.net +short
dig @127.0.0.1 example.com +short
```

Expected: `0.0.0.0` for the first, a real address for the second. `getent
hosts` on the Pi is not a Pi-hole test — NetworkManager keeps the Pi's own
resolver pointed at the router, which is correct (the Pi must resolve even
when its own Pi-hole is broken) but means only `dig @127.0.0.1` tests the
service.

## 6. The router's DNS field — last

The router hands the Pi out as the **only** DNS server: DHCP settings → DNS →
primary `192.168.68.65`, secondary empty. Reason for no secondary: clients
round-robin across resolvers, so a second one would leak half the queries
around the blocklists and turn a Pi outage into intermittent weirdness instead
of a clear failure.

**Do this last**, after the Pi has answered queries for a while from the spot
it will live in. During the build the field was flipped before the Wi-Fi was
stable; the Pi dropped off minutes later and the house had no DNS until the
field was reverted. Rollback is that same field, back to automatic.

Clients pick up the new resolver at lease renewal; toggling Wi-Fi forces it.
Verify from the workstation:

```bash
resolvectl status | grep -A2 'DNS Servers'
dig doubleclick.net +short
```

Expected: the Pi's address as the DNS server, `0.0.0.0` for the ad domain.
On a phone, `http://pi.hole/admin` loads and the query log shows its lookups.

Two bypasses to know about on clients: Firefox's DNS-over-HTTPS (check
`about:networking#dns` — TRR must be off) and Android's Private DNS setting.
Both send queries past any local resolver.

## 7. Tailscale

Install, enable forwarding (the file is `hosts/exitnode/99-tailscale.conf`),
bring it up:

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo install -m 0644 99-tailscale.conf /etc/sysctl.d/99-tailscale.conf && sudo sysctl --system
sudo tailscale up --ssh --advertise-exit-node --advertise-routes=192.168.68.0/22 --accept-dns=false
```

Each flag has a reason:

- `--ssh` — Tailscale SSH, authenticated by the tailnet identity. A second door
  that does not depend on the sshd config from section 3.
- `--advertise-exit-node` — offer full-tunnel through home.
- `--advertise-routes=192.168.68.0/22` — offer the LAN. This is the out-of-band
  path: the router's UI, the switch, and the mini PCs' AMT are LAN-only, and
  through this route they are reachable from any tailnet device.
- `--accept-dns=false` — the Pi must never take its own DNS from the tailnet.
  The tailnet's DNS *is* this Pi; a loop here would take the Pi's own
  resolution down with it.

In the Tailscale admin console:

1. Machines → the Pi → Edit route settings → approve the exit node and the
   subnet route. Advertised routes do nothing until approved.
2. Same machine → Disable key expiry. A DNS server whose auth key expires in
   180 days is a scheduled outage.
3. DNS → Nameservers → Add nameserver → Custom → the Pi's tailnet address,
   with **Use with exit node** on. Without it, a device that selects the Pi as
   its exit node hands DNS to the Pi's own resolver — the router — and loses
   blocking exactly when it routes through home.
4. DNS → **Override DNS servers** on, so every tailnet device uses this
   nameserver instead of whatever network it is sitting on.

Then take the servers out of that dependency. On `node01` and inside the
workbench container:

```
sudo tailscale set --accept-dns=false
```

Servers keep explicit nameservers of their own, so a dead Pi cannot blind the
cluster or its alerting.

Verify from a phone on mobile data with Tailscale connected (no exit node
selected): `http://pi.hole/admin` loads. From a tailnet Linux box:

```bash
dig @<the Pi's tailnet address> doubleclick.net +short
```

Expected `0.0.0.0`. Then select the Pi as exit node on the phone and confirm a
what-is-my-IP site shows the home connection.

## 8. Wi-Fi on a mesh: what had to change

The Pi joins a TP-Link Deco mesh over Wi-Fi. Three behaviours of the 3B+ radio
on that mesh cost most of the build evening, and three settings fixed them.
Each is a `nmcli` property on the connection profile, applied once and
persistent:

```
sudo nmcli connection modify "<SSID>" wifi.powersave 2
sudo nmcli connection modify "<SSID>" wifi.band bg
sudo nmcli connection modify "<SSID>" connection.autoconnect-retries 0
sudo nmcli device reconnect wlan0
```

- **Power save off** (`2`). With it on, the Pi went silent for stretches and
  dropped its association.
- **2.4 GHz only** (`bg`). The mesh steers clients between bands and units; the
  3B+ driver handled the 5 GHz steering badly and dropped within minutes of
  joining near the main unit. Locked to 2.4 GHz: signal 100, ~1 % loss, 20 ms.
  The band caps throughput, which DNS does not notice.
- **Retry forever** (`0`). The default gives up after a few attempts, which on
  a headless box means a reboot.

And the cloud-init guard, so the profile survives every boot
(`hosts/exitnode/99-disable-network-config.cfg`):

```
sudo install -m 0644 99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
```

**Operating rule that remains:** every time the mesh applies a settings change
(any save in its app, including the DNS field above), it kicks all clients.
Phones rejoin; the 3B+ can keep a *zombie* association — `nmcli` says
`connected`, the address is still there, and the gateway does not answer ARP.
After any router settings save, ping the Pi; if it is gone, at its console:

```
sudo nmcli device reconnect wlan0
```

A reboot does the same. A ping-the-gateway watchdog was drafted and not
installed: in steady state there are no kicks.

Diagnostics that were useful:

```
nmcli device status
nmcli device wifi list
vcgencmd get_throttled
ping -c 3 192.168.68.1
```

`get_throttled` returning `0x0` rules out the power supply, which is the
first suspect for any Pi that misbehaves.

---

## Verification checklist

- On the Pi: `dig @127.0.0.1 doubleclick.net +short` → `0.0.0.0`.
- On the workstation: `resolvectl status` shows `192.168.68.65`.
- On a phone over mobile data with Tailscale on: `http://pi.hole/admin` loads.
- `sudo tailscale status` on the Pi lists the exit node and subnet route as
  advertised; the console shows them approved.
- `systemctl status log2ram` → active.
- `ssh` with a key works; forced password is refused.

## Rebuild

Blank card → sections 1 to 8, in that order, with section 6 genuinely last.
Nothing is restored. The router's DHCP reservation keeps the address, so no
client notices. In the Tailscale console, delete the old `exitnode` machine
**before** running `tailscale up`, otherwise the new one registers as
`exitnode-1` with a new tailnet address and the DNS override keeps pointing at
the dead one. Allowlist entries are the only hand-made state; they are
recreated from the query log as things break.

## Known limits

- **Single resolver.** A dead Pi is a house without names until the router's
  DNS field is reverted — see the disaster-recovery runbook, Scenario F.
- **Exit-node throughput.** Measured at roughly 5 Mbit/s from a phone: a
  2.4 GHz Wi-Fi link shared with the rest of the house, a mesh behind a second
  NAT (so Tailscale likely relays), and a 3B+ CPU that tops out in the tens of
  Mbit/s for WireGuard in userspace. Adequate for DNS, SSH and a management
  console; not a VPN for video.
- **DNS-level blocking has gaps.** First-party ad paths (an ad served from the
  publisher's own domain) and cosmetic elements are invisible to DNS. A
  browser extension handles those per device.
- **SD card.** log2ram removes the steady log churn; the card still wears.
  Treat the Pi as rebuildable rather than durable — hence this page.
