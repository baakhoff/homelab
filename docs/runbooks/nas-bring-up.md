# Bringing the NAS into service

How `nas` went from parts on a bench to TrueNAS on the LAN. Written after the
fact, in the order that worked, with the detours folded in as rules.

It was installed offline, from a USB stick, at a bench with a monitor and a
keyboard, with no network at any point during the install. On the nodes that
same condition left every interface down; here it cost nothing — section 4.

Parts and specs: [hardware](../hardware.md#nas--nas). Why TrueNAS:
[ADR 0008](../decisions/0008-truenas-for-the-nas.md). Addressing and the
switch: [the network](../network.md).

---

## 1. Firmware

The case has no power button. The very first power-on, before the firmware
had any setting that could start the machine by itself, was done by shorting
the `PWRSW` pins on the board's front-panel header. From then on Restore AC
Power Loss, below, does that job.

The board is the original PRIME H310I-PLUS, not the R2.0, on BIOS 0803 of
2018-06-20. **It was deliberately not flashed.** The G5400 is supported from
the first BIOS, TrueNAS loads CPU microcode itself, and the change logs since
offer nothing this machine needs.

Settings made:

| Menu | Setting | Value |
|---|---|---|
| Advanced → APM Configuration | Restore AC Power Loss | Power On |
| Advanced → APM Configuration | ErP Ready | Disabled |
| Advanced → APM Configuration | Power On By PCI-E | Enabled |
| Advanced → PCH Storage Configuration | S.M.A.R.T. Self Test | On |
| Advanced → PCH Storage Configuration | Hot Plug | left Disabled |
| Boot | Fast Boot | Disabled |
| Boot | Wait For 'F1' If Error | Disabled |
| Boot | Launch CSM | Disabled |
| Boot | Secure Boot → OS Type | Other OS |

The ones with a story:

- **Restore AC Power Loss** is the power button this case does not have. How it
  behaves is section 5.
- **Power On By PCI-E** lets the onboard NIC, which sits on PCIe, power the
  machine on. **ErP Ready**, when enabled, switches every such wake option off,
  so it stays disabled.
- **There is no SATA mode to set.** The H310 has no RAID, so the controller is
  AHCI only and PCH Storage Configuration offers no mode option.
- **Wait For 'F1' If Error** off, because a machine with no keyboard or monitor
  would otherwise wait at a prompt nobody sees.
- **Launch CSM** off makes the board pure UEFI. Section 2 is why that came
  first.
- **Secure Boot OS Type: Other OS.** TrueNAS's documentation requires Secure
  Boot off; Other OS is this board's setting for that.

The Intel box cooler is on `CPU_FAN`, on Q-Fan's Silent profile, with the lower
limit kept at 200 RPM.

## 2. The NVMe arrived running FreeDOS

The boot drive came from the seller with FreeDOS on it, and the board booted it
in legacy mode — until Launch CSM was disabled.

**A used drive boots whatever its last owner left on it.** If the board starts
FreeDOS, CSM is still on. Turn it off before the installer runs, so the machine
is pure UEFI from its first install. The installer then takes the whole drive,
and nothing of FreeDOS survives.

## 3. The install, offline

1. **Unplug the WD Red first.** The installer offers every disk it can see as a
   destination. With the data disk unplugged, the only disk it can offer is the
   NVMe, so the wrong choice is not available. Plug it back in afterwards.
2. Boot the USB stick. Destination: `nvme0n1`, alone. TrueNAS takes the whole
   drive as its `boot-pool`.
3. Account: **Administrative user (`truenas_admin`)**.
4. Set the password — and know that **the installer types with a US keyboard
   layout**, whatever keyboard is plugged in. A password typed there is the US
   reading of the keys pressed. The first one set this way did not work
   afterwards. **Use a plain ASCII password at the installer.**

If it happens anyway, the console menu has **Change local administrator
password**. That is how the first password was replaced, at the machine, with
no reinstall. The menu asked for no password at that point; section 6 changes
that.

## 4. On the network with nothing configured

**TrueNAS runs DHCP on every NIC when none is configured.** It came up on the
LAN as soon as it was cabled, with no network setup at the console at all. The
trap that left the nodes' interfaces administratively down after their offline
Ubuntu install ([node bring-up, section 1](node-bring-up.md#1-they-were-on-the-network-and-not-on-the-network))
has no equivalent here.

| What | Value |
|---|---|
| NIC | onboard Realtek RTL8111H, in-kernel `r8169` driver — nothing to add; interface `enp2s0` |
| Address | `192.168.68.105`, now static in TrueNAS with the Deco reservation kept (below) |
| Switch | port 6 |

**The reservation matched on the MAC with nothing done on the host.** TrueNAS
sends no DHCP client identifier, so it needs none of the `dhcp-identifier: mac`
workaround the Ubuntu nodes carry
([why they need it](../network.md#reservations-and-ubuntu)).

### The address that expired: the board's clock was on local time

Two hours after it came up, the NAS vanished from the LAN: `ping` from the
workstation answered *Destination Host Unreachable*, the Deco dropped it from
its client list, and yet the fans ran and the switch port blinked. The Pi,
wired to the same switch, still found it by its IPv6 link-local address —
`ping -6 ff02::1%eth0`, then `ip neigh` matched against the NAS's MAC — so the
machine and its NIC were fine. Over SSH through the Pi as a jump host:

```
ssh -J <user>@192.168.68.65 "truenas_admin@fe80::<the NAS's link-local>%eth0"
```

`enp2s0` was up with only its link-local address, and `dhclient` was still
running. The journal said why: the lease was bound at boot with *renewal in
3241 seconds*, and minutes later every timestamp jumped two hours back.

**The firmware clock had been set to local time (UTC+2), and Linux reads it as
UTC.** TrueNAS booted two hours fast, took its lease, then chrony stepped the
clock back to the truth. `dhclient` had planned its renewal against the wrong
clock and was still waiting for it when the address — whose lifetime the kernel
counts down on its own — expired with the lease.

The clock is fixed for good: chrony runs with `rtcsync`, so the corrected UTC
time was written to the firmware clock, and `timedatectl` now shows *RTC time*
equal to *Universal time*. The rule for a rebuild: **set the firmware clock to
UTC before the first boot.**

### The address that expired again: a `dhclient` started under `sudo`

The first recovery was to kill the confused `dhclient` and start a new one from
the SSH session with `sudo dhclient ...`. It bound the address at once, and two
hours later the NAS was gone again, mid-copy. The journal showed the renewals
reaching the Deco and failing on the NAS:

```
dhclient[...]: DHCPACK of 192.168.68.105 from 192.168.68.1
dhclient[...]: execve (/sbin/dhclient-script, ...): Function not implemented
```

TrueNAS's `sudo` logs every program its command starts by intercepting `execve`.
Once the SSH session that ran `sudo` closed, nothing was left to answer for that
interception, and every later `execve` failed — so the renewed lease was never
applied, and the address expired exactly at the end of the first lease. **Never
start a long-lived daemon with `sudo` from a shell on TrueNAS.** The middleware
starts its own `dhclient` as a system process with `sudo midclt call
interface.sync`, after the stray one is killed.

### Static in TrueNAS, the reservation kept

DHCP had now cost two outages, and the NAS is what the cluster's storage will
depend on. Its address is static in TrueNAS (Network → Interfaces → `enp2s0`:
`192.168.68.105/22`, gateway `192.168.68.1`, nameservers `192.168.68.65` then
`192.168.68.1`, applied with *Test Changes* and saved within the rollback
window). The Deco keeps its reservation for the same address, which is what
stops the DHCP pool from ever handing it to another device; see
[the network](../network.md#addressing).

## 5. Power without a button

Restore AC Power Loss = Power On is what starts this machine without a button,
and how it behaves was measured rather than assumed:

- The box **starts by itself when power returns, but only after the power has
  been fully off for a while.** A ten-second cut did not count: power came back
  and the machine stayed off. A longer cut, then power back, starts it.

Two rules follow:

- **Restart, not Shut Down**, in TrueNAS. A restart comes back on its own; a
  shut-down machine stays off with no button to press.
- **After a Shut Down anyway:** switch the PSU off, wait about a minute, switch
  it on. The wait is what makes the board treat it as a power loss.

## 6. TrueNAS settings

| Setting | Value |
|---|---|
| Hostname | `nas` |
| Timezone | Europe/Belgrade |
| Usage collection | off |
| UI error reporting | off |
| Update profile | **General** |
| Console: Show Text Console without Password Prompt | **off** |
| Alert service | Telegram |
| SSH | on, start automatically; key only, the workstation's key on `truenas_admin` |
| Init script, Post Init | `ethtool -s enp2s0 wol g` |
| Local user | `baakh`, UID 1000, SMB access |

- **Update profile: General.** A fresh 25.10.7 install shows **Mission
  Critical**, a profile that is never offered General releases. Change it on
  every fresh install.
- **The console asks for a password.** With *Show Text Console without Password
  Prompt* on, anyone at the keyboard gets the console menu — the same menu that
  replaced the admin password in section 3. Turned off, the console asks for a
  password first. Turn it off only after the admin password has been proven by
  logging in to the web UI with it.
- **Telegram alerts.** System → Alert Settings, a Telegram alert service, with
  the bot token and chat id from the lab Alertmanager's `alertmanager-telegram`
  Secret ([`clusters/lab/monitoring/`](../../clusters/lab/monitoring/)). The
  NAS's alerts land in the same chat as the cluster's. A test alert from that
  page arrived.
- **SSH is key only by default.** TrueNAS writes `PasswordAuthentication no`
  and leaves password login off for `truenas_admin`; turning the service on and
  pasting the public key into the user (Credentials → Users, SSH Access) was all
  it took.
- **Wake-on-LAN needs a startup command.** TrueNAS has no WOL setting, and the
  `r8169` driver starts every boot with wake disabled, so a Post Init command
  arms it: `ethtool -s enp2s0 wol g`. The Pi wakes it as `wake-nodes nas`
  ([waking the lab](../network.md#waking-the-lab)).

## 7. The disk

The WD Red Plus is not new: about 22,300 power-on hours. Its SMART counters,
read with `smartctl`:

| Counter | Value |
|---|---|
| Reallocated sectors | 0 |
| Pending sectors | 0 |
| Offline uncorrectable | 0 |
| Interface CRC errors | 0 |
| SMART error log | empty |

The first three are the platters' own failures: sectors already remapped,
sectors waiting to be, and sectors that failed an offline scan. CRC errors are
transfer errors between the disk and the board, so a nonzero count points at
the SATA cable before the disk.

An extended self-test (`smartctl -t long`, 234 minutes) then read the whole
surface: *Completed without error*.

## 8. Storage

| Pool | Layout | Disk |
|---|---|---|
| `tank` | single-disk stripe | the WD Red Plus |

A single disk has no redundancy: ZFS still checksums every block, so it
detects damaged file data, but it can only repair metadata (kept twice by
default), not the files themselves. The Create Pool pages for Log, Spare,
Cache, Metadata and Dedup stay empty. Each needs disks this box does not have,
and a lone special (metadata) vdev would take the whole pool with it if it died.

| Dataset | Preset | Encryption | Record size | For |
|---|---|---|---|---|
| `tank/personal` | Multiprotocol | AES-256-GCM, key | default | family files |
| `tank/media` | Multiprotocol | none | 1M | large files that can be fetched again: films and series, for Plex |
| `tank/immich` | Generic | AES-256-GCM, its own key | 1M | Immich's photo library, quota 800 GiB |

- **The pool root is not encrypted; `personal` is.** TrueNAS's own docs advise
  against root encryption, and the G5400 has no AVX, so ZFS falls back to its
  slower AES-GCM code: media stays unencrypted and fast.
- **A key, not a passphrase.** TrueNAS keeps the key in its configuration on
  the boot SSD and unlocks the dataset at every boot, so a power cut needs no
  one at the keyboard. That protects disks that leave the box, not a stolen
  box. The key was exported (Datasets → the dataset → ZFS Encryption → Export
  Key) and is kept as text in the owner's password manager: without it the
  dataset cannot be opened on any other system.
- **Multiprotocol, not SMB.** The SMB preset makes a dataset case-insensitive
  with restricted ACLs, which Linux clients cannot work with; Multiprotocol
  serves Windows as well and keeps Linux access possible. It also makes an NFS
  share, though - see [the cluster's shares](#the-clusters-shares).
- **Generic for `immich`.** Plain POSIX permissions: Immich sets file modes
  as it files photos away, which an NFSv4 ACL can refuse. Its key was
  exported to the password manager as `personal`'s was.

Periodic snapshot tasks on `tank`, recursive:

| Task | Schedule | Kept | Naming schema |
|---|---|---|---|
| hourly | every hour | 2 days | `hourly-%Y-%m-%d_%H-%M` |
| daily | every day | 5 weeks | `daily-%Y-%m-%d_%H-%M` |

The schemas differ so the two tasks never claim each other's snapshots. An SMB
client cannot delete them, and Windows shows them as Previous Versions.

The configuration export (System → Advanced Settings → Manage Configuration →
Download File, with *Export Password Secret Seed*) is the backup of record for
everything above, the dataset key included. It is a secret: it lives in the
password manager, not in a download folder.

### The Windows share

| Share | Path | Purpose | Access |
|---|---|---|---|
| `personal` | `/mnt/tank/personal` | Default Share | the local user `baakh`, owner of the dataset |

From the Windows PC, in PowerShell:

```
net use P: \\nas.lab\personal /user:baakh /persistent:yes
robocopy "<source folder>" P:\ /E /COPY:DAT /DCOPY:DAT /R:2 /W:5 /MT:8 /XJ /NP /LOG:$env:USERPROFILE\nas-copy.log /TEE
```

`robocopy` keeps timestamps, retries, resumes when run again, and a second run
that copies nothing proves the first one finished. A log under `C:\` itself
fails with *Access is denied* for a normal user, and robocopy then refuses to
start at all: keep the log in the user's profile.

### The cluster's shares

Two datasets reach the cluster over NFSv4, mounted by the nodes through
csi-driver-nfs (`clusters/lab/csi-driver-nfs/`): the photo library and the
films.

| Local user | UID | GID | Owns |
|---|---|---|---|
| `immich` | 3000 | 3001 | `tank/immich`, mode 770 |
| `media` | 3001 | 3002 | `tank/media`, and its `films` and `series` folders |

Both have the password disabled, the `nologin` shell and no SMB access.
TrueNAS numbers new users from 3000, clear of 1000, which is `baakh` here and
the agent pods' user in the cluster. The pods that write run as these ids
(`clusters/lab/immich/`, `clusters/lab/plex/`).

The NFS service runs NFSv4 only, bound to `192.168.68.105`, started at boot.

| Share | Networks | Mapall user and group | Mounted by |
|---|---|---|---|
| `/mnt/tank/immich` | `192.168.68.102/32`, `.103/32`, `.104/32` | `immich` | Immich, read-write |
| `/mnt/tank/media` | the same three | `media` | Plex, read-only |

**Mapall** turns every request from a client into the share's own user, root
included (`all_squash`). NFS believes whatever user id a client sends, so
with Mapall there is only one it can be. The node addresses alone are no
fence: pod traffic leaves a node under that node's address, which is why
every open namespace in the cluster carries a `no-nas` NetworkPolicy
([Pods and the LAN](../network.md#pods-and-the-lan)). Maproot stays empty;
TrueNAS refuses both at once.

**The Multiprotocol preset makes an NFS share as well.** Creating `personal`
with it had added a share for `/mnt/tank/personal`, open to every address and
writable, beside the SMB one. It did nothing while the NFS service was off,
went live the evening the service was switched on for Immich, and was found
in `/etc/exports` and deleted the next morning. After creating a dataset with
that preset, look under Shares → Unix (NFS) Shares and delete what it made.

The library folders, over SSH:

```
sudo install -d -o media -g media /mnt/tank/media/films /mnt/tank/media/series
```

The check, also over SSH:

```
sudo cat /etc/exports
sudo ss -tn '( sport = :2049 )'
```

`exports` lists exactly the two shares, each for the three node addresses
with `all_squash`: `anonuid=3000,anongid=3001` on `immich`,
`anonuid=3001,anongid=3002` on `media`. `ss` shows connections from node
addresses and nothing else.

## Verification checklist

- The board boots pure UEFI into TrueNAS from the NVMe; FreeDOS no longer
  starts.
- `nas` holds `192.168.68.105` as a static address, on `enp2s0`, cabled to
  switch port 6.
- The web UI answers on that address and the admin password works.
- With the PSU switched off for about a minute and on again, the machine starts
  by itself.
- The update profile reads General.
- `timedatectl` shows *RTC time* equal to *Universal time*, and the clock synchronized.
- `ssh truenas_admin@nas.lab` logs in with the workstation's key and no password.
- A test alert from System → Alert Settings arrives in the Telegram chat.
- The physical console asks for a password.
- SMART on the WD Red: zero reallocated, pending and offline-uncorrectable
  sectors, zero CRC errors, an empty error log, and an extended self-test
  completed without error.
- `tank/personal` is encrypted and unlocked after a reboot without anyone
  typing a key; its exported key opens it.
- Both snapshot tasks appear under Data Protection and have taken snapshots.
- The Windows PC maps `\\nas.lab\personal` as `baakh`, and a second `robocopy`
  run copies nothing.
- `/etc/exports` holds the `immich` and `media` shares and nothing else, each
  for the three node addresses with `all_squash` to its own user.
- `tank/immich` is encrypted, unlocked after a reboot, and its exported key
  opens it.
