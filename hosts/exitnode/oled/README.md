# OLED status screens

Four 0.91" 128×32 SSD1306 modules on a Raspberry Pi Pico in the rack, plugged
into the Pi by USB. The Pico only draws; the Pi decides everything, so changing
a screen never means re-flashing it.

| File | Goes to | Does |
|---|---|---|
| `main.py` | the Pico, as `main.py` | the firmware: reads lines from USB, draws them |
| `oled-status` | `/usr/local/bin/` on the Pi | collects the numbers and sends them every 5 seconds |
| `oled-status.service` | `/etc/systemd/system/` | runs it |
| `oled-status.conf.example` | — | template for `/etc/oled-status.conf`, which is **not** tracked |
| `oled-demo` | anywhere with Python 3 | sends made-up numbers, to check the screens without real data |

## The screens

| | Shows | Inverts when |
|---|---|---|
| 1 | `LAB OK` and nodes up, in large text; otherwise nodes up, the alert count and the first three firing alerts, critical first | a node is down, any alert other than Watchdog fires, or Prometheus cannot be reached |
| 2 | one row per node: CPU %, RAM %, hottest sensor | a node is down or at 85 °C |
| 3 | WAN latency, Pi-hole's queries and share blocked over 24 h, active clients | the internet or Pi-hole is down |
| 4 | hours since the last good backup, Ceph health, days to the first certificate expiry, open PRs | the backup is over 26 h old, Ceph reports an error, or a certificate is within 7 days |

The Pi is outside the cluster on purpose. When the lab goes down, screen 1
says `LAB UNREACHABLE` with the reason instead of going dark with it — a
screen in the cluster could not.

Contrast drops to `NIGHT_CONTRAST` overnight.

The Pico also needs `ssd1306.py` from
[micropython-lib](https://github.com/micropython/micropython-lib/tree/master/micropython/drivers/display/ssd1306).
Thonny's package manager could not install it under Python 3.14 — its bundled
pip 22 calls `pkgutil.ImpImporter`, gone since 3.12 — so copy the file over by
hand, or `mpremote mip install ssd1306`.

## Wiring

Every one of these modules answers at `0x3C` and has no jumper to change it,
so each needs a bus of its own: the RP2040's two hardware I2C controllers, and
two bit-banged `SoftI2C` buses.

| Screen | SDA | SCL | GND |
|---|---|---|---|
| 1 | pin 1 (GP0) | pin 2 (GP1) | pin 3 |
| 2 | pin 4 (GP2) | pin 5 (GP3) | pin 8 |
| 3 | pin 6 (GP4) | pin 7 (GP5) | pin 13 |
| 4 | pin 9 (GP6) | pin 10 (GP7) | pin 18 |

VCC on all four comes from **pin 36, 3V3 OUT**, the Pico's only 3.3 V output,
split on a breadboard rail. Four modules draw about 80 mA against the
regulator's 300. Pin 37 next to it is `3V3_EN`, an input that switches the
supply off; nothing connects there.

**A bus scan listing every address from `0x08` to `0x77` means a module has no
power.** An unpowered SSD1306 drags SDA and SCL low through its protection
diodes, and a low SDA is what an acknowledgement looks like, so every address
appears to answer. That is how a breadboard rail not connected to pin 36 first
showed up.

## Protocol

One line per update, ASCII only — the built-in font has no Cyrillic:

```
2|n1 23% 61% 48C|n2 11% 54% 45C    screen 2, up to four lines of 16 characters
1!|ALERT|node02 down                trailing ! inverts the screen
3*|DNS 12k|blk 18%                  trailing * is double size: two lines of 8
1!*|DOWN                            the flags combine
C|40                                contrast for every screen, 0-255
```

Malformed lines are dropped. Until a screen's first update it shows its own
number, which doubles as the wiring check. After 60 seconds without an update
it shows `no data` instead of its last values — a dead host must not leave
healthy-looking numbers up for days.

Every five minutes everything moves sideways by a pixel or two. OLEDs burn in,
and these show the same characters in the same place all day. Dimming at night
is the host's call, through `C|`.

A display that drops off the bus is retried every ten seconds without
disturbing the other three.

## Try it

1. Copy `main.py` to the Pico: in Thonny, **File → Save as → Raspberry Pi
   Pico**, named `main.py`. Or `mpremote cp main.py :main.py`.
2. Close Thonny, then unplug and replug the Pico. Each screen shows its number
   and `waiting`.
3. `./oled-demo` (or `./oled-demo /dev/ttyACM1` if the Pico landed elsewhere).
   Screen 1 inverts with a fake alert for ten seconds of every thirty, and the
   onboard LED flickers with each line received.

Thonny has to be closed while anything else talks to the Pico: it holds the
port, and connecting interrupts `main.py` to get a prompt.

## Install on the Pi

Prometheus is reached through `prometheus-api.lab.baakhoff.com`, a second
Ingress that takes a password instead of the Pocket ID login and opens only the
query endpoint — `clusters/lab/monitoring/prometheus-api-ingress.yaml` says
why it is a password and not an IP allow-list. Its htpasswd line is
`clusters/lab/monitoring/prometheus-api-auth.sops.yaml`.

From a checkout of this directory on the Pi:

```
sudo install -m 0755 oled-status /usr/local/bin/oled-status
sudo install -m 0644 oled-status.service /etc/systemd/system/oled-status.service
sudo install -m 0600 oled-status.conf.example /etc/oled-status.conf
```

Fill in `/etc/oled-status.conf` — the Prometheus password, a Pi-hole app
password, `WAN_HOST` — then:

```
sudo systemctl daemon-reload
sudo systemctl enable --now oled-status
journalctl -u oled-status -f
```

The journal stays quiet when everything works. Each source logs once when it
fails and once when it recovers, never every cycle.
