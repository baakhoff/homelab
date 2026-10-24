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
| Address | `192.168.68.105`, a DHCP reservation on the Deco, the same mechanism as the nodes |
| Switch | port 6 |

**The reservation matched on the MAC with nothing done on the host.** TrueNAS
sends no DHCP client identifier, so it needs none of the `dhcp-identifier: mac`
workaround the Ubuntu nodes carry
([why they need it](../network.md#reservations-and-ubuntu)).

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

## Verification checklist

- The board boots pure UEFI into TrueNAS from the NVMe; FreeDOS no longer
  starts.
- `nas` holds `192.168.68.105` from the reservation, on `enp2s0`, cabled to
  switch port 6.
- The web UI answers on that address and the admin password works.
- With the PSU switched off for about a minute and on again, the machine starts
  by itself.
- The update profile reads General.
- A test alert from System → Alert Settings arrives in the Telegram chat.
- The physical console asks for a password.
- SMART on the WD Red: zero reallocated, pending and offline-uncorrectable
  sectors, zero CRC errors, an empty error log.
