# exitnode host files

The files placed by hand on the Pi (`exitnode`), kept here so the machine can be
rebuilt from git. The build order and the reasons behind the first three are in
the [Pi runbook](../../docs/runbooks/pi-exitnode.md).

| File | Installs to | Does |
|---|---|---|
| `00-hardening.conf` | `/etc/ssh/sshd_config.d/` | keys-only SSH, no root login. Named `00-` so it wins sshd's first-match rule against the image's own `50-cloud-init.conf` |
| `99-tailscale.conf` | `/etc/sysctl.d/` | IPv4 and IPv6 forwarding — required for the exit-node and subnet-router roles |
| `99-disable-network-config.cfg` | `/etc/cloud/cloud.cfg.d/` | stops cloud-init from managing the network on every boot; it dropped the Wi-Fi profile once |
| `wake-nodes` | `/usr/local/bin/` | sends Wake-on-LAN magic packets to the lab's machines |
| `wake-nodes.conf.example` | — | template for `/etc/wake-nodes.conf`, which is **not** tracked |
| `apt-metrics`, `apt-metrics.service`, `apt-metrics.timer` | `/usr/local/sbin/`, `/etc/systemd/system/` | hourly, counts the security updates apt has and the Pi has not installed, and whether it waits for a reboot, for node-exporter; [the alerts](../../clusters/lab/monitoring/host-security-rules.yaml). Byte-identical to the nodes' copies |
| `prometheus-node-exporter.conf` | `/etc/systemd/system/prometheus-node-exporter.service.d/lab.conf` | node-exporter answers the three cluster nodes, where Prometheus's scrape comes from, and nobody else |
| `oled/` | the Pi and the Pico | the rack's OLED status screens — [its own README](oled/README.md) |

## Install

From a checkout of this directory on the Pi:

```
sudo install -m 0644 00-hardening.conf /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t && sudo systemctl reload ssh
sudo install -m 0644 99-tailscale.conf /etc/sysctl.d/99-tailscale.conf
sudo sysctl --system
sudo install -m 0644 99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
sudo apt install -y wakeonlan
sudo install -m 0755 wake-nodes /usr/local/bin/wake-nodes
sudo install -m 0644 wake-nodes.conf.example /etc/wake-nodes.conf
```

Then edit `/etc/wake-nodes.conf` and replace the placeholder MACs with the real
ones. They are deliberately absent from this repository — hardware addresses sit
on the never-publish list next to serials, the SSID and public addresses, because
they identify specific equipment and feed Wi-Fi geolocation databases.

## Security updates

Raspberry Pi OS does not install security updates by itself; with
unattended-upgrades it does, daily, from Debian's security archive. Then
node-exporter and the hourly check, which Prometheus scrapes
(`clusters/lab/monitoring/exitnode-scrape.yaml`):

```
sudo apt install -y unattended-upgrades needrestart
sudo dpkg-reconfigure -plow unattended-upgrades
sudo apt install -y --no-install-recommends prometheus-node-exporter
sudo install -d /etc/systemd/system/prometheus-node-exporter.service.d
sudo install -m 0644 prometheus-node-exporter.conf /etc/systemd/system/prometheus-node-exporter.service.d/lab.conf
sudo install -m 0755 apt-metrics /usr/local/sbin/apt-metrics
sudo install -m 0644 apt-metrics.service apt-metrics.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart prometheus-node-exporter
sudo systemctl enable --now apt-metrics.timer
sudo systemctl start apt-metrics.service
curl -s localhost:9100/metrics | grep -E '^(apt_|node_reboot|pihole_)'
```

`dpkg-reconfigure` asks one question: yes. It turns on the daily fetch of
the package lists as well as the upgrade. `--no-install-recommends` leaves
out the package's own collector scripts, which pull in smartmontools and
more for checks this does not need. The `curl` shows five numbers, the last Pi-hole's;
`apt_package_lists_timestamp_seconds` may be 0 until the first daily fetch,
or run `sudo apt update` and the service again.

Pi-hole is not from apt, so unattended-upgrades does not update it.
`apt-metrics` reads the versions Pi-hole's own daily check writes, and
`PiholeUpdatePending` says when a release has been out three days; then
read its notes and `sudo pihole -up`.

The same scrape watches how full `/` and `/var/log` are
(`clusters/lab/monitoring/exitnode-rules.yaml`). `/var/log` is log2ram's
128 MiB in RAM, and Pi-hole's query log shares it.

## Why waking lives on the Pi

A magic packet is a broadcast frame, and broadcasts do not cross routers. Whatever
sends it has to share a network segment with the machine being woken. The Pi is
the only always-on Linux box on the wired segment, and it is on the tailnet — so
it is also the only thing that can turn the lab on from outside the house:

```
ssh <user>@exitnode wake-nodes
```

Wake-on-LAN needs the target's firmware configured for it too. On the HP Elite
Mini 600 G9: `Wake On LAN` enabled, and `S5 Maximum Power Savings` **unticked** —
that second setting cuts power to the network card in S5 and makes waking fail
silently.

`sshd -t` before the reload: a typo in an sshd drop-in and a reload without the
check is how a headless box ends up needing a keyboard again.

## Not files: the Wi-Fi settings

**The Pi is on ethernet now** — these settings apply to the Wi-Fi profile that
is kept as the fallback path, with `connection.autoconnect no` so it does not
come up on its own. Runbook section 9 covers the move.

Three settings live in NetworkManager's connection profile rather than in a
file worth tracking. Applied once, persistent across reboots:

```
sudo nmcli connection modify "<SSID>" wifi.powersave 2
sudo nmcli connection modify "<SSID>" wifi.band bg
sudo nmcli connection modify "<SSID>" connection.autoconnect-retries 0
```

Power saving off, 2.4 GHz only, never stop retrying. The runbook's section 8
explains what each one fixed.

## Same caveat as `hosts/node01`

Nothing detects drift between these files and the machine. If something is
changed on the Pi and not mirrored back here, the repo is quietly wrong.
