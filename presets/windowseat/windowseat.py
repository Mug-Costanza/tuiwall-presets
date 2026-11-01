#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4 tabstop=4:
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4; -*-

# --- TUIWALL METADATA ---
# Name: Window Seat
# Author: Mug
# Description: Lo-fi train ride along a lake, under a sky that follows your local time
# Category: Ambiance
# ------------------------

# Drawn with half-block characters and 24-bit color, so each cell holds two
# square pixels. If the sky looks banded, tell tmux your terminal supports RGB:
#   set -as terminal-features ",xterm-256color:RGB"

import math
import os
import random
import select
import sys
import termios
import time
import tty

FPS = 15
SPEED = 1.0          # train speed multiplier
CYCLE_MINUTES = 0    # 0 follows the real clock; e.g. 6 plays a whole day every 6 minutes
FIXED_HOUR = None    # e.g. 19.5 for a permanent sunset

# hour, sky top, sky at the horizon, daylight (0-1). The land colors are derived
# from the sky so each layer always reads darker than the one behind it.
KEYFRAMES = [
    (0.0,  (6, 8, 24),     (34, 32, 76),    0.0),
    (4.8,  (8, 10, 30),    (44, 36, 84),    0.02),
    (6.0,  (40, 46, 108),  (232, 140, 120), 0.35),
    (7.3,  (82, 132, 205), (250, 208, 178), 0.75),
    (12.5, (62, 128, 218), (176, 214, 246), 1.0),
    (16.8, (78, 118, 198), (244, 206, 162), 0.85),
    (18.4, (66, 66, 148),  (255, 150, 92),  0.6),
    (19.4, (36, 30, 90),   (228, 98, 108),  0.3),
    (20.4, (16, 17, 54),   (84, 58, 120),   0.1),
    (21.6, (6, 8, 24),     (34, 32, 76),    0.0),
    (24.0, (6, 8, 24),     (34, 32, 76),    0.0),
]

WHITE = (255, 255, 255)
POLE_SPACING = 96


def mix(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def scale(a, f):
    return (a[0] * f, a[1] * f, a[2] * f)


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def smooth(e0, e1, v):
    v = clamp01((v - e0) / (e1 - e0))
    return v * v * (3 - 2 * v)


def palette(hour):
    for (h0, *a), (h1, *b) in zip(KEYFRAMES, KEYFRAMES[1:]):
        if h0 <= hour <= h1:
            f = smooth(0, 1, (hour - h0) / (h1 - h0))
            top, hor, light = [mix(x, y, f) if isinstance(x, tuple) else x + (y - x) * f
                               for x, y in zip(a, b)]
            break
    else:
        top, hor, light = KEYFRAMES[0][1:]
    far = mix(scale(mix(top, hor, 0.45), 0.42 + 0.2 * light), hor, 0.08)
    near = mix(scale(far, 0.55), (30, 60, 45), 0.35 * light)
    ground = scale(near, 0.55)
    return top, hor, far, near, ground, light


def current_hour(now):
    if FIXED_HOUR is not None:
        return FIXED_HOUR % 24
    if CYCLE_MINUTES:
        return (now / 60.0 / CYCLE_MINUTES * 24) % 24
    lt = time.localtime(now)
    return lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0


def moon_phase(now):
    # 0 = new, 0.5 = full; counted from the new moon of 2000-01-06 18:14 UTC
    return ((now - 947182440) / 86400.0 / 29.530588853) % 1.0


_rng = random.Random(7)
_PERM = list(range(256))
_rng.shuffle(_PERM)
_VAL = [_rng.random() for _ in range(256)]


def noise(x, y):
    """Smooth value noise in [0, 1]."""
    ix = math.floor(x)
    iy = math.floor(y)
    fx = x - ix
    fy = y - iy
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    p0 = _PERM[ix & 255]
    p1 = _PERM[(ix + 1) & 255]
    a = _VAL[(p0 + iy) & 255]
    b = _VAL[(p1 + iy) & 255]
    c = _VAL[(p0 + iy + 1) & 255]
    d = _VAL[(p1 + iy + 1) & 255]
    top = a + (b - a) * fx
    return top + (c + (d - c) * fx - top) * fy


def hash01(i, salt=0):
    return _VAL[(_PERM[(i + salt * 31) & 255] + (i >> 8)) & 255]


class Scene:
    """Renders the view as a framebuffer of RGB pixels, two per terminal cell."""

    def __init__(self, w, ph):
        self.w = w
        self.ph = ph
        self.ground_h = max(1, round(ph * 0.12))
        self.water_h = max(1, round(ph * 0.28))
        self.horizon = max(1, ph - self.ground_h - self.water_h)

        rng = random.Random(w * 7919 + ph)
        self.stars = []
        for _ in range(w * self.horizon // 18):
            warm = rng.random() < 0.2
            self.stars.append((
                rng.randrange(w),
                rng.randrange(max(1, self.horizon - 1)),
                rng.uniform(0.3, 1.0),          # brightness
                rng.uniform(0.5, 2.5),          # twinkle speed
                rng.uniform(0, math.tau),       # twinkle phase
                (255, 228, 200) if warm else (220, 228, 255),
            ))
        self.caches = {"far": {}, "near": {}, "shore": {}, "cloud": {}}
        self.shooting = None

    # Terrain profiles, in pixels above each layer's base, per world column

    def far_height(self, i):
        ridge = 1 - abs(2 * noise(i * 0.09, 8.3) - 1)
        detail = 1 - abs(2 * noise(i * 0.23, 5.6) - 1)
        mass = noise(i * 0.02, 1.7)
        shape = clamp01(0.55 * ridge ** 3 + 0.12 * detail + 0.45 * mass)
        return (0.08 + 0.72 * shape) * self.horizon

    def near_height(self, i):
        hills = noise(i * 0.04, 4.2)
        trees = noise(i * 0.45, 9.1) * 0.6 + noise(i * 1.1, 2.4) * 0.4
        return (0.03 + 0.12 * hills) * self.horizon + trees * min(1.2, self.horizon * 0.12)

    def shore_height(self, i):
        h = self.ground_h * 0.75 + noise(i * 0.2, 2.9) * self.ground_h * 0.6
        if hash01(i, 3) < 0.1:  # reeds
            h += 0.8 + hash01(i, 5) * max(0.8, self.ph * 0.12)
        return h

    def _heights(self, name, fn, i0):
        cache = self.caches[name]
        out = []
        for i in range(i0, i0 + self.w + 2):
            v = cache.get(i)
            if v is None:
                v = cache[i] = fn(i)
            out.append(v)
        if len(cache) > self.w * 4:
            for k in [k for k in cache if k < i0]:
                del cache[k]
        return out

    def _land(self, fb, name, fn, off, base, color, mist=None, mist_amt=0.0):
        """Fill a scrolling silhouette whose top edge is anti-aliased."""
        i0 = math.floor(off)
        f = off - i0
        heights = self._heights(name, fn, i0)
        for x in range(self.w):
            h = heights[x] + (heights[x + 1] - heights[x]) * f
            top = max(0.0, base - h)
            for y in range(int(top), base):
                c = color
                if mist_amt:
                    m = (y + 0.5 - top) / (base - top)  # 0 at the ridge, 1 at the base
                    c = mix(color, mist, mist_amt * m * m)
                cov = y + 1 - top
                fb[y][x] = c if cov >= 1 else mix(fb[y][x], c, cov)

    def _glow(self, fb, cx, cy, radius, color, amount):
        if amount <= 0.01:
            return
        r2 = radius * radius
        for y in range(max(0, int(cy - radius)), min(self.horizon, int(cy + radius) + 1)):
            row = fb[y]
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - radius)), min(self.w, int(cx + radius) + 1)):
                dx = x + 0.5 - cx
                g = amount * math.exp(-3.0 * (dx * dx + dy * dy) / r2)
                if g > 0.01:
                    row[x] = mix(row[x], color, g)

    def _disk(self, fb, cx, cy, r, color, alpha, phase=None):
        if alpha <= 0.01:
            return
        for y in range(max(0, int(cy - r - 1)), min(self.horizon, int(cy + r) + 2)):
            row = fb[y]
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - r - 1)), min(self.w, int(cx + r) + 2)):
                dx = x + 0.5 - cx
                a = clamp01(r + 0.5 - math.hypot(dx, dy)) * alpha
                if a <= 0:
                    continue
                c = color
                if phase is not None:
                    ny = clamp01(abs(dy) / r)
                    limb = math.sqrt(1 - ny * ny)
                    k = math.cos(math.tau * phase)
                    edge = (dx / r - limb * k) if phase < 0.5 else (-limb * k - dx / r)
                    c = mix(scale(color, 0.16), color, clamp01(edge * r + 0.5))
                row[x] = mix(row[x], c, a)

    def render(self, t, hour, dist, dt, phase):
        w, ph, hz = self.w, self.ph, self.horizon
        top, hor, far, near, ground, light = palette(hour)

        fb = []
        for y in range(ph):
            if y < hz:
                fb.append([mix(top, hor, ((y + 0.5) / hz) ** 1.7)] * w)
            else:
                fb.append([ground] * w)

        # Sun and moon cross the sky over the day
        def place(e, p):
            lift = math.sqrt(e) if e > 0 else e
            return w * (0.1 + 0.8 * p), (hz - 0.5) - max(-1.0, lift) * max(0.0, hz - 2.0)

        sun_e = math.sin(math.pi * (hour - 6.3) / 13.0)
        sun_x, sun_y = place(sun_e, (hour - 6.3) / 13.0)
        sun_a = clamp01(sun_e * 3 + 0.15)
        sun_col = mix((255, 120, 60), (255, 244, 214), clamp01(sun_e * 2.5))

        moon_p = ((hour - 18.8) % 24) / 12.4
        moon_e = math.sin(math.pi * moon_p)
        moon_x, moon_y = place(moon_e, moon_p)
        moon_a = clamp01(moon_e * 5) * clamp01(1.3 - light * 1.6) if moon_p < 1 else 0.0
        moon_col = (242, 238, 218)

        self._glow(fb, sun_x, sun_y, max(2.0, ph * 0.14) * (5 + 7 * (1 - clamp01(sun_e))),
                   sun_col, 0.55 * clamp01(sun_e * 4 + 0.5))
        self._glow(fb, moon_x, moon_y, max(2.0, ph * 0.13) * 6, (120, 130, 175), 0.35 * moon_a)

        # Stars, and the odd shooting star
        star_a = clamp01(1 - light * 3.2)
        if star_a > 0.01:
            for sx, sy, b, sp, sph, col in self.stars:
                a = star_a * b * (0.6 + 0.4 * math.sin(t * sp + sph))
                fb[sy][sx] = mix(fb[sy][sx], col, a)

        if self.shooting is None and star_a > 0.4 and random.random() < dt / 30.0:
            self.shooting = [random.uniform(w * 0.1, w * 0.9), random.uniform(0, hz * 0.35),
                             random.choice((-1, 1)) * random.uniform(35, 55), random.uniform(8, 14), 0.0]
        if self.shooting is not None:
            s = self.shooting
            s[4] += dt
            if s[4] > 0.9:
                self.shooting = None
            else:
                fade = math.sin(math.pi * s[4] / 0.9) * star_a
                hx, hy = s[0] + s[2] * s[4], s[1] + s[3] * s[4]
                for k in range(8):
                    ix, iy = int(hx - s[2] * 0.018 * k), int(hy - s[3] * 0.018 * k)
                    if 0 <= iy < hz and 0 <= ix < w:
                        fb[iy][ix] = mix(fb[iy][ix], WHITE, fade * (1 - k / 8.0))

        self._disk(fb, sun_x, sun_y, max(0.9, ph * 0.14), sun_col, sun_a)
        self._disk(fb, moon_x, moon_y, max(0.9, ph * 0.13), moon_col, moon_a, phase)

        # Clouds drift on their own, a little faster as the train moves
        cloud_col = mix(hor, WHITE, 0.12 + 0.5 * light)
        band = [clamp01(1.2 - 2.0 * (y + 0.5) / hz) for y in range(hz)]
        thr = 0.6 - 0.06 * math.sin(t / 500.0)
        i0 = int(t * 0.4 + dist * 0.015)
        cache = self.caches["cloud"]
        for x in range(w):
            i = i0 + x
            col = cache.get(i)
            if col is None:
                col = cache[i] = [noise(i * 0.075, y / hz * 3.0 + 40) * 0.65
                                  + noise(i * 0.18, y / hz * 6.0 + 90) * 0.35 for y in range(hz)]
            for y in range(hz):
                if col[y] > thr and band[y] > 0:
                    fb[y][x] = mix(fb[y][x], cloud_col, smooth(thr, thr + 0.2, col[y]) * 0.75 * band[y])
        if len(cache) > w * 4:
            for k in [k for k in cache if k < i0]:
                del cache[k]

        # Far mountains and near hills, slower the further away they are
        self._land(fb, "far", self.far_height, dist * 0.06, hz, far, hor, 0.2)
        near_off = dist * 0.25
        self._land(fb, "near", self.near_height, near_off, hz, near, far, 0.25)

        # Windows in the hills light up as it gets dark
        lights = []
        glow = clamp01(1 - light * 2.2)
        if glow > 0.02:
            heights = self.caches["near"]
            for i in range(math.floor(near_off), math.floor(near_off) + w + 1):
                if hash01(i, 11) > 0.07:
                    continue
                h = heights.get(i, 0)
                x = int(round(i - near_off))
                if h < 1.6 or not 0 <= x < w:
                    continue
                y = min(hz - 1, int(hz - h + 1 + hash01(i, 13) * (h - 1.6)))
                col = (255, 196, 120) if hash01(i, 17) < 0.8 else (170, 215, 255)
                a = glow * (0.7 + 0.3 * math.sin(t * (0.5 + hash01(i, 19)) + i))
                fb[y][x] = mix(fb[y][x], col, a)
                lights.append((x, col, a))

        # The lake: a rippling, darkened reflection of everything above it
        tint = mix(top, (4, 10, 22), 0.5)
        ripple_col = mix(hor, WHITE, 0.25)
        stretch = max(1.0, hz * 0.8 / self.water_h)
        if sun_a >= moon_a:
            body_x, body_col, body_a = sun_x, sun_col, sun_a
        else:
            body_x, body_col, body_a = moon_x, moon_col, moon_a
        for wy in range(self.water_h):
            src = fb[max(0, hz - 1 - int((wy + 0.5) * stretch))]
            row = fb[hz + wy]
            amp = 0.5 + 1.2 * wy / self.water_h
            spread = 1.5 + wy * 1.2
            for x in range(w):
                sx = x + int(round(math.sin(t * 1.2 + wy * 2.3 + x * 0.19) * amp))
                sx = 0 if sx < 0 else w - 1 if sx >= w else sx
                c = mix(src[sx], tint, 0.38)
                s = math.sin(x * 0.31 + t * 1.4 + wy * 1.9) * math.sin(x * 0.083 - t * 0.45 + wy * 3.7)
                if s > 0.55:
                    c = mix(c, ripple_col, (s - 0.55) * 0.9)
                if body_a > 0.02:
                    d = (x - body_x) / spread
                    if d * d < 9:
                        sparkle = ((math.sin(x * 2.3 + t * 7 + wy * 5.1) + 1) / 2) ** 3
                        c = mix(c, body_col, min(1.0, 0.8 * body_a * math.exp(-d * d) * (0.35 + 0.65 * sparkle)))
                row[x] = c
            for lx, col, a in lights:
                x = lx + int(round(math.sin(t * 1.7 + wy * 2.1 + lx) * amp * 0.6))
                if 0 <= x < w:
                    row[x] = mix(row[x], col, a * 0.55 * (1 - wy / (self.water_h + 1.0)))

        # The near shore rushes past
        self._land(fb, "shore", self.shore_height, dist, ph, ground)

        # Telegraph poles and their sagging wires (too cramped on tiny headers)
        if ph < 8:
            return fb
        pole_col = mix(scale(ground, 0.75), (26, 20, 18), 0.4)
        pole_off = dist * 1.25
        y_top = ph * 0.06
        attach = (y_top + 0.7,)
        sag = max(1.0, ph * 0.24)
        k0 = math.floor(pole_off / POLE_SPACING)
        for k in range(k0, k0 + w // POLE_SPACING + 3):
            px = k * POLE_SPACING - pole_off
            for a in attach:
                for x in range(max(0, math.ceil(px)), min(w, int(px + POLE_SPACING) + 1)):
                    u = (x - px) / POLE_SPACING
                    wy = a + sag * 4 * u * (1 - u)
                    y0 = int(wy)
                    f = wy - y0
                    if y0 < ph:
                        fb[y0][x] = mix(fb[y0][x], pole_col, 0.35 * (1 - f))
                    if y0 + 1 < ph:
                        fb[y0 + 1][x] = mix(fb[y0 + 1][x], pole_col, 0.35 * f)
            arm_y = min(ph - 1, int(y_top))
            for x in range(max(0, int(px - 2)), min(w, int(px + 3) + 1)):
                cov = clamp01(min(x + 1, px + 2.5) - max(x, px - 1.5))
                if cov > 0:
                    fb[arm_y][x] = mix(fb[arm_y][x], pole_col, cov)
            for x in (math.floor(px), math.floor(px) + 1):
                cov = clamp01(min(x + 1, px + 1) - max(x, px))
                if cov > 0 and 0 <= x < w:
                    for y in range(arm_y, ph):
                        fb[y][x] = mix(fb[y][x], pole_col, cov)

        return fb


def _q(c):
    r, g, b = c
    return (0 if r < 0 else 255 if r > 255 else int(r),
            0 if g < 0 else 255 if g > 255 else int(g),
            0 if b < 0 else 255 if b > 255 else int(b))


def to_cells(fb):
    """Pair pixel rows into cells: (top color, bottom color)."""
    cells = []
    for y in range(0, len(fb) - 1, 2):
        a, b = fb[y], fb[y + 1]
        cells.append([(_q(a[x]), _q(b[x])) for x in range(len(a))])
    return cells


def draw_cells(cells, prev, row0):
    """Emit only the cells that changed since the previous frame."""
    out = []
    fg = bg = None
    for r, row in enumerate(cells):
        old = prev[r] if prev is not None else None
        cursor = -1
        for x, cell in enumerate(row):
            if old is not None and old[x] == cell:
                continue
            if cursor != x:
                out.append("\x1b[%d;%dH" % (row0 + r + 1, x + 1))
            t, b = cell
            if t == b:
                if b != bg:
                    out.append("\x1b[48;2;%d;%d;%dm" % b)
                    bg = b
                out.append(" ")
            else:
                if t != fg and b != bg:
                    out.append("\x1b[38;2;%d;%d;%d;48;2;%d;%d;%dm" % (t + b))
                elif t != fg:
                    out.append("\x1b[38;2;%d;%d;%dm" % t)
                elif b != bg:
                    out.append("\x1b[48;2;%d;%d;%dm" % b)
                fg, bg = t, b
                out.append("▀")
            cursor = x + 1
    return "".join(out)


def term_size():
    try:
        s = os.get_terminal_size(sys.stdout.fileno())
        return s.columns, s.lines
    except OSError:
        return 80, 10


def run(fd):
    out = sys.stdout
    scene = prev = size = header = None
    start = last = time.time()
    dist = 0.0

    while True:
        now = time.time()
        dt = min(0.25, now - last)
        last = now
        buf = []

        w, h = term_size()
        if (w, h) != size:
            size = (w, h)
            scene = Scene(w, (h - 2) * 2) if h > 2 and w > 0 else None
            prev = header = None
            buf.append("\x1b[0m\x1b[2J")

        # Header
        lines = (("  tuiwall  " + time.strftime("%H:%M:%S")).ljust(w)[:w],
                 ("  " + time.strftime("%a %b %d")).ljust(w)[:w])
        if lines != header:
            header = lines
            buf.append("\x1b[0m\x1b[1;1H\x1b[1m%s\x1b[0m" % lines[0])
            if h > 1:
                buf.append("\x1b[2;1H%s" % lines[1])

        if scene is not None:
            dist += 30.0 * SPEED * (0.85 + 0.15 * math.sin((now - start) / 45.0)) * dt
            fb = scene.render(now - start, current_hour(now), dist, dt, moon_phase(now))
            cells = to_cells(fb)
            buf.append(draw_cells(cells, prev, 2))
            prev = cells

        if buf:
            # Synchronized output: the terminal shows the frame only once it's complete
            out.write("\x1b[?2026h" + "".join(buf) + "\x1b[?2026l")
            out.flush()

        # Exit on keypress
        wait = max(0.0, 1.0 / FPS - (time.time() - now))
        if fd is not None:
            if select.select([fd], [], [], wait)[0]:
                os.read(fd, 64)
                return
        else:
            time.sleep(wait)


def main():
    fd = sys.stdin.fileno() if sys.stdin.isatty() else None
    saved = None
    if fd is not None:
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    # Alternate screen, hidden cursor, no autowrap (so the last column never scrolls)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?7l")
    try:
        run(fd)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        if saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


if __name__ == "__main__":
    main()
