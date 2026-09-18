# Bringing the three mini PCs into service

How `node02`, `node03` and `node04` went from three boxes with an operating
system on them to three machines on the network, hardened and burnt in. Written
after the fact, in the order that worked, with the detours folded in as rules.

They were installed offline weeks earlier, from a USB stick, with no network at
any point. That single fact caused everything in section 1.

Addressing and the switch: [the network](../network.md).

---

## 1. They were on the network and not on the network

Symptoms, all at once:

- The switch showed link at 1000M on all three ports.
- `ping` answered on three addresses the router had leased.
- `ssh` to those addresses **timed out**.
- Nothing named `node02`/`node03`/`node04` appeared in the router's client
  list — instead three entries carried Windows-style names left over from the
  machines' previous life.

Each observation was consistent with two different explanations, and no
further remote test separated them. The answer came from one line at a console:

```
ip -br a
```

```
lo     UNKNOWN  127.0.0.1/8
eno1   DOWN
```

**`DOWN` is the administrative state** — nobody had asked the kernel to enable
the interface. Subiquity, told "continue without network" during an offline
install, had written a netplan with no ethernet stanza at all. No DHCP request
had ever left any of the three machines. The cable, the switch and the link
were fine the whole time; Ubuntu simply was not participating.

The addresses that answered `ping` belonged to **Intel AMT**. The management
engine has its own IP stack and takes a DHCP lease whenever the machine has
mains power, whether or not an operating system is running — and it registers
whatever hostname its configuration carries, which on ex-corporate machines is
a name from an install that no longer exists.

Two rules worth keeping from this:

- **`Connection refused` and `Connection timed out` mean different things.** A
  refusal is a reply: something received the packet and said no. A timeout is
  silence — dropped by a firewall, or by a minimal stack that does not
  implement that port. Linux would have refused; the ME dropped.
- **A router's client list is not an inventory.** It is assembled from whatever
  each device volunteers, cached, and never re-verified. The machine's own
  `hostname` and `ip -br link` are the authority.

### Scaffold first, configure second

Typing YAML at a console three times invites typos. Give each machine a
temporary address by hand, then do the real work over SSH where you can paste:

```
sudo ip link set eno1 up
sudo ip addr add 192.168.68.11/22 dev eno1
sudo ip route add default via 192.168.68.1
```

Taken from the static block below the DHCP pool, so a throwaway cannot collide
with a real lease. Nothing here survives a reboot — `ip` changes the running
kernel, not the declared configuration — which is exactly what a scaffold
should do.

On a machine with two NICs, bring both up and look: the cabled one shows `UP`,
the empty one `NO-CARRIER`. That also identifies which name belongs to which
port.

### The permanent configuration

Per machine, over SSH. Files are in [`hosts/nodes/`](../../hosts/nodes/).

```
printf 'network:\n  config: disabled\n' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
sudo netplan set --origin-hint 99-lab ethernets.eno1.dhcp4=true
sudo netplan set --origin-hint 99-lab ethernets.eno1.optional=true
sudo netplan set --origin-hint 99-lab ethernets.eno1.dhcp-identifier=mac
sudo netplan generate
```

Each key earns its place:

- **`dhcp4: true`** — the thing that was missing.
- **`optional: true`** — boot does not block on
  `systemd-networkd-wait-online` when a cable is out. Without it a headless box
  waits for a network that is not coming and you are back at the monitor.
- **`dhcp-identifier: mac`** — `systemd-networkd` otherwise identifies itself
  with an identifier derived from `/etc/machine-id`, and a router matching on
  client-ID ignores a MAC reservation entirely. The symptom is a reservation
  that silently does nothing.

`netplan set` rather than an editor: it writes valid YAML for you, and the
one-line `network: {config: disabled}` form is awkward on a non-US console
keyboard. `netplan generate` parses without applying, so a mistake surfaces
while SSH still works.

Then **reboot rather than `netplan apply`.** Applying tears down the interface
the SSH session is riding on and can strand a half-configured node. A reboot
has the same effect, cannot strand itself, and proves the configuration
persists — which is the whole point.

### Reserve before you reboot

Create the DHCP reservations *before* the reboot that applies the new config.
Done in that order the machine's first persistent address is its final one.
Done the other way it takes a pool address first and needs a second reboot,
because a reservation only takes effect when the client next asks.

This matters beyond tidiness: k3s writes the node's address into etcd's member
list and into the certificates it generates, and Ceph later writes monitor
addresses of its own. Every address a machine holds before that is scaffolding,
and scaffolding that accidentally becomes permanent is how infrastructure
acquires facts nobody chose.

## 2. Keys, then close the door

```
ssh-copy-id <user>@<node>
```

Then the same drop-in the Pi uses, from [`hosts/nodes/`](../../hosts/nodes/):

```
sudo install -m 0644 00-hardening.conf /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t && sudo systemctl reload ssh
```

The `00-` prefix is load-bearing: sshd keeps the **first** value it reads for
each keyword and the `Include` line sits at the top of `sshd_config`, so a file
named `hardening.conf` would lose to the image's `50-cloud-init.conf`, which
turns password authentication back on.

`sshd -t` before the reload, always. Test in this order — key login first, then
the refusal:

```
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password <user>@<node>
```

Expected: `Permission denied (publickey)`. Never run the second test before the
first has passed.

## 3. Swap off

kubelet's `failSwapOn` defaults to true; it will not start on a node with swap
enabled. The deeper reason is that its resource model assumes memory is memory
— requests drive scheduling, limits drive enforcement, eviction thresholds are
computed against real RAM. With swap, a pod over its limit is paged out rather
than killed, and "the pod restarted" becomes "everything on this node is
mysteriously slow".

```
sudo swapoff -a
sudo sed -i.bak "/swap.img/s/^/#/" /etc/fstab
```

The swapfile itself is left in place — 4 GB of a 100 GB root, and the change
stays reversible. Verify **after a reboot**, which is what the fstab edit buys
over a bare `swapoff -a`:

```
swapon --show
```

Expected: no output at all.

## 4. First update

These had never seen a package mirror. Expect a large upgrade including a new
kernel, and reboot into it.

```
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

## 5. Burn-in

Used machines, still inside a manufacturer warranty window. Two things worth
knowing before depending on them.

### Storage

```
sudo smartctl -a /dev/nvme0n1
```

The fields that matter: `Media and Data Integrity Errors` and `Critical
Warning` must both be zero — those are uncorrectable losses the drive noticed
and could not fix, and a single-digit count on a used drive sends it back.
`Percentage Used` is the drive's own wear estimate, and `Data Units Written` is
in 512 KB units.

**`Power On Hours` is the field people misread.** Two years of continuous
power-on sounds alarming and means almost nothing for flash: NAND wears when
cells are erased and rewritten, not when they are powered. These drives read
17,000–19,000 hours with wear at 0–4%.

The QLC drive in one machine showed four times the wear of the TLC drives for
half the power-on time, which is QLC paying for density with endurance. Fine
for an operating system, and a concrete reason the Ceph OSD drives are
specified as TLC with DRAM.

### CPU and cooling

```
sudo systemd-run --unit=burnin stress-ng --cpu 12 --timeout 30m --metrics-brief
```

`systemd-run` rather than `nohup &`: it runs as a transient systemd unit, so a
dropped SSH session cannot kill it, the output lands in `journalctl -u burnin`,
and there is an exit status to query afterwards.

Thirty minutes, not two: thermal behaviour in a one-litre chassis takes minutes
to stabilise, and a short run measures the heatsink's thermal mass rather than
the cooling system. Watch it settle:

```
sensors | grep Package
```

Baseline measured on these three, stacked directly on top of one another with
no airflow — the worst configuration they will ever be in:

| | idle | sustained, all cores |
|---|---|---|
| package temperature | 34–39 °C | **69–76 °C** |

Against a high threshold of 80 °C and critical of 100 °C, flat for the last
fifteen minutes of the run, so that is a real plateau rather than a curve still
climbing. Re-measure once they are racked with air between them.

`stress-ng`'s bogo-ops figure is meaningless in absolute terms and perfectly
good for comparing identical machines. These landed within 3% of each other,
which is silicon variation, not a defect. A machine meaningfully behind the
others is worth a second look while the warranty still applies.

## 6. What the management engine gives you, and does not

Intel AMT is enabled in firmware on all three and **not provisioned**, so
nothing answers on port 16992. Enabled is not the same as usable.

Its MAC is the same as the operating system's, which means AMT is in shared-IP
mode: one address per machine, used by both, reachable whether the OS is
running or not. One DHCP reservation covers both.

Provisioning it is a deliberate, separate job, because the obvious route is a
trap. Setting a password in MEBx produces **Client Control Mode**, where KVM
requires user consent — a six-digit code displayed on the machine's own screen.
On a headless box in a rack that is useless. **Admin Control Mode**, which
removes the consent requirement, needs either a provisioning certificate or USB
key provisioning, and one physical visit per machine.

Until then, Wake-on-LAN covers turning them on, which is most of what is
actually needed. See [`hosts/exitnode/`](../../hosts/exitnode/).

## Verification checklist

- `ssh <user>@node0X hostname` answers on the reserved address, by key.
- Forced password authentication is refused.
- `swapon --show` prints nothing, after a reboot.
- `ip -br a` shows the interface UP with the reserved address and exactly one
  default route.
- The switch's port page shows the expected ports at 1000M.
- SMART shows zero media errors and zero critical warnings.
