# exitnode host files

The three files placed by hand on the Pi (`exitnode`) during its build, kept
here so the machine can be rebuilt from git. The build order and the reasons
behind each file are in the [Pi runbook](../../docs/runbooks/pi-exitnode.md).

| File | Installs to | Does |
|---|---|---|
| `00-hardening.conf` | `/etc/ssh/sshd_config.d/` | keys-only SSH, no root login. Named `00-` so it wins sshd's first-match rule against the image's own `50-cloud-init.conf` |
| `99-tailscale.conf` | `/etc/sysctl.d/` | IPv4 and IPv6 forwarding — required for the exit-node and subnet-router roles |
| `99-disable-network-config.cfg` | `/etc/cloud/cloud.cfg.d/` | stops cloud-init from managing the network on every boot; it dropped the Wi-Fi profile once |

## Install

From a checkout of this directory on the Pi:

```
sudo install -m 0644 00-hardening.conf /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t && sudo systemctl reload ssh
sudo install -m 0644 99-tailscale.conf /etc/sysctl.d/99-tailscale.conf
sudo sysctl --system
sudo install -m 0644 99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
```

`sshd -t` before the reload: a typo in an sshd drop-in and a reload without the
check is how a headless box ends up needing a keyboard again.

## Not files: the Wi-Fi settings

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
