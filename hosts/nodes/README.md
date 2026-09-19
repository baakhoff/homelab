# Cluster node host files

The files placed by hand on `node02`, `node03` and `node04`, kept here so the
machines can be rebuilt from git. All three are configured identically, so they
share one directory rather than three copies of the same content.

How they got into service, and why each setting exists:
[node bring-up runbook](../../docs/runbooks/node-bring-up.md).

| File | Installs to | Does |
|---|---|---|
| `99-lab.yaml` | `/etc/netplan/` | DHCP on the onboard NIC, identified by MAC so the router's reservation matches, and `optional` so boot never waits on an unplugged cable |
| `99-disable-network-config.cfg` | `/etc/cloud/cloud.cfg.d/` | stops cloud-init reasserting its own network configuration — which, after an offline install, was none at all |
| `00-hardening.conf` | `/etc/ssh/sshd_config.d/` | keys-only SSH, no root login. Named `00-` so it wins sshd's first-match rule against the image's own `50-cloud-init.conf` |

`00-hardening.conf` is byte-identical to the Pi's copy in
[`hosts/exitnode/`](../exitnode/). It is duplicated rather than referenced so
that each host directory can rebuild its machine on its own.

## Install

From a checkout of this directory on the node:

```
sudo install -m 0644 99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
sudo install -m 0600 99-lab.yaml /etc/netplan/99-lab.yaml
sudo netplan generate
sudo reboot
```

`netplan generate` parses without applying, so a mistake surfaces while the
current session still works. Reboot rather than `netplan apply`: applying tears
down the interface the SSH session is riding on, and a reboot proves the
configuration persists at the same time.

Then push an SSH key with `ssh-copy-id` and confirm key login works **before**
installing `00-hardening.conf` — which is why it is a second step rather than
another line above. Closing password authentication on a machine you cannot yet
reach by key means fetching a keyboard.

```
sudo install -m 0644 00-hardening.conf /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t && sudo systemctl reload ssh
```

## Not files

Two changes on these machines live outside any file worth tracking.

**Swap is off.** `swapoff -a`, and the `/swap.img` line in `/etc/fstab` is
commented out with a `.bak` kept beside it. kubelet refuses to start with swap
enabled, and the reason is worth knowing rather than working around — see the
runbook.

**Firmware.** `Wake On LAN` enabled and `S5 Maximum Power Savings` unticked, so
the network card keeps power when the machine is off and the Pi can wake these
with a magic packet. Intel AMT is enabled but deliberately left unprovisioned.

**Tailscale.** All three are tailnet members with Tailscale SSH enabled, which is
how they are reached by name from the workstation and how step A3 of the
[disaster-recovery runbook](../../docs/runbooks/disaster-recovery.md) collects a
kubeconfig. The join was done by hand and the flags used were never written
down, so this paragraph records that it is true rather than how to reproduce it —
a gap of the same kind as the caveat below.

## Same caveat as `hosts/node01` and `hosts/exitnode`

Nothing detects drift between these files and the machines. If something is
changed on a node and not mirrored back here, the repo is quietly wrong.
