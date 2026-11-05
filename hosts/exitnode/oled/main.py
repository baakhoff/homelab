# main.py — MicroPython firmware for the Pico driving four 128x32 OLEDs.
#
# The Pico only draws. Whatever is on the other end of the USB cable writes
# one line per update to the serial port, and every decision about what to
# show stays on that side, so changing a screen never means re-flashing this:
#
#   2|n1 23% 61% 48C|n2 11% 54% 45C    screen 2, up to four lines of text
#   1!|ALERT|node02 down                trailing ! inverts the screen
#   3*|DNS 12k|blk 18%                  trailing * is double-size text, two lines
#   1!*|DOWN                            the flags combine
#   C|40                                contrast for every screen, 0-255
#   R|1                                 every screen turned 180 degrees; R|0 back
#
# A screen with no update for STALE_MS says so. A host that has died must not
# leave its last healthy-looking numbers up for days.
#
# All four modules answer at 0x3C and cannot be re-addressed, so each sits on
# a bus of its own: the RP2040's two hardware I2C controllers, and two
# bit-banged ones on any free pins.

import sys
import time
import select
import framebuf
from machine import Pin, I2C, SoftI2C
import ssd1306

W, H = 128, 32
ADDR = 0x3C
STALE_MS = 60_000
SHIFT_MS = 5 * 60_000  # burn-in: nudge everything sideways this often
RECONNECT_MS = 10_000
SHIFTS = (0, 1, 2, 1)


def buses():
    # SoftI2C's timeout bounds how long a missing display can stall the loop:
    # with nothing attached the clock line floats, and the default waits
    # 50 ms per bit for a device to release it.
    return [
        I2C(0, sda=Pin(0), scl=Pin(1), freq=400_000),
        I2C(1, sda=Pin(2), scl=Pin(3), freq=400_000),
        SoftI2C(sda=Pin(4), scl=Pin(5), freq=400_000, timeout=2_000),
        SoftI2C(sda=Pin(6), scl=Pin(7), freq=400_000, timeout=2_000),
    ]


# The built-in font is 8x8. Double-size text is drawn into this strip first
# and copied out at 2x, eight characters to a line.
_strip = framebuf.FrameBuffer(bytearray(64), 64, 8, framebuf.MONO_HLSB)


def big_text(fb, s, x, y):
    s = s[:8]
    _strip.fill(0)
    _strip.text(s, 0, 0, 1)
    for ty in range(8):
        for tx in range(len(s) * 8):
            if _strip.pixel(tx, ty):
                fb.fill_rect(x + 2 * tx, y + 2 * ty, 2, 2, 1)


class Screen:
    def __init__(self, n, bus):
        self.n = n
        self.bus = bus
        self.oled = None
        self.flipped = False
        self.lines = []
        self.invert = False
        self.big = False
        self.seen = None  # ticks_ms of the last update; None until the first
        self.stale = False
        self.dirty = True

    def connect(self, state):
        try:
            if ADDR not in self.bus.scan():
                return
            self.oled = ssd1306.SSD1306_I2C(W, H, self.bus, ADDR)
            self.flipped = False  # init puts it upright
            self.dirty = True
        except OSError:
            self.oled = None
            return
        self.apply(state)

    def apply(self, state):
        # Display-wide settings, sent again whenever a display is (re)connected:
        # its own init resets them.
        if self.oled is None:
            return
        try:
            self.oled.contrast(state["contrast"])
            # Turning 180 degrees is mirroring both ways: column order
            # (segment remap, 0xA0/0xA1) and row scan direction (0xC0/0xC8).
            # The driver's init sets 0xA1 and 0xC8, the upright orientation.
            self.oled.write_cmd(0xA0 if state["flip"] else 0xA1)
            self.oled.write_cmd(0xC0 if state["flip"] else 0xC8)
            # Column order applies as pixels are written, so what is already
            # on the glass only comes out right after a redraw.
            if self.flipped != state["flip"]:
                self.flipped = state["flip"]
                self.dirty = True
        except OSError:
            self.oled = None

    def update(self, lines, invert, big, now):
        self.lines = lines[:2] if big else lines[:4]
        self.invert = invert
        self.big = big
        self.seen = now
        self.dirty = True

    def check_stale(self, now):
        stale = self.seen is not None and time.ticks_diff(now, self.seen) > STALE_MS
        if stale != self.stale:
            self.stale = stale
            self.dirty = True

    def draw(self, shift):
        if self.oled is None or not self.dirty:
            return
        fb = self.oled
        try:
            fb.fill(0)
            if self.seen is None:
                # Boot state, which doubles as the wiring check: each screen
                # names itself until the host first writes to it.
                fb.invert(0)
                big_text(fb, "%d" % self.n, shift, 8)
                fb.text("waiting", 32 + shift, 12, 1)
            elif self.stale:
                fb.invert(0)
                fb.text("%d  no data" % self.n, shift, 12, 1)
            else:
                fb.invert(1 if self.invert else 0)
                rows = len(self.lines) or 1
                step = H // rows
                glyph = 16 if self.big else 8
                for i, line in enumerate(self.lines):
                    y = i * step + (step - glyph) // 2
                    if self.big:
                        big_text(fb, line, shift, y)
                    else:
                        fb.text(line[:16], shift, y, 1)
            fb.show()
            self.dirty = False
        except OSError:
            # Unplugged or a loose wire. Drop it and let the reconnect pass
            # pick it up again, rather than taking the other three down too.
            self.oled = None


def handle(line, screens, state, now):
    head, _, rest = line.partition("|")
    if head in ("C", "R"):
        if head == "C":
            state["contrast"] = max(0, min(255, int(rest)))
        else:
            state["flip"] = rest.strip() == "1"
        for s in screens:
            s.apply(state)
        return
    invert = "!" in head
    big = "*" in head
    n = int(head.replace("!", "").replace("*", ""))
    if not 1 <= n <= len(screens):
        return
    screens[n - 1].update(rest.split("|") if rest else [], invert, big, now)


def main():
    state = {"contrast": 128, "flip": False}
    screens = [Screen(i + 1, b) for i, b in enumerate(buses())]
    for s in screens:
        s.connect(state)

    led = Pin("LED", Pin.OUT)
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    buf = ""
    shift_i = 0
    shift_at = time.ticks_ms()
    reconnect_at = shift_at

    while True:
        if poll.poll(100):
            while poll.poll(0):
                ch = sys.stdin.read(1)
                if ch == "\n":
                    line = buf.strip()
                    buf = ""
                    if not line:
                        continue
                    try:
                        handle(line, screens, state, time.ticks_ms())
                        led.toggle()
                    except (ValueError, IndexError):
                        pass  # a malformed line is dropped, never fatal
                elif len(buf) < 256:
                    buf += ch

        now = time.ticks_ms()
        if time.ticks_diff(now, shift_at) > SHIFT_MS:
            shift_at = now
            shift_i = (shift_i + 1) % len(SHIFTS)
            for s in screens:
                s.dirty = True
        if time.ticks_diff(now, reconnect_at) > RECONNECT_MS:
            reconnect_at = now
            for s in screens:
                if s.oled is None:
                    s.connect(state)

        for s in screens:
            s.check_stale(now)
            s.draw(SHIFTS[shift_i])


main()
