# OLED status screens

Four 0.91" 128×32 SSD1306 modules on a Raspberry Pi Pico, which takes what to
show over USB serial. The Pico only draws; the host on the other end of the
cable decides everything, so changing a screen never means re-flashing it.

| File | Goes to | Does |
|---|---|---|
| `main.py` | the Pico, as `main.py` | the firmware: reads lines from USB, draws them |
| `oled-demo` | anywhere with Python 3 | sends made-up numbers, to check the screens without real data |

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
