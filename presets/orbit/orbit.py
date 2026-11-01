#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4 tabstop=4:
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4; -*-

# --- TUIWALL METADATA ---
# Name: Low Orbit
# Author: Mug
# Description: The view from a space station: sunrises, city lights, lightning and aurora
# Category: Ambiance
# ------------------------

# Drawn with half-block characters and 24-bit color, so each cell holds two
# square pixels.

import math
import os
import random
import select
import sys
import termios
import time
import tty

FPS = 15
ORBIT_MINUTES = 4.0   # one trip around the planet: day, sunset, night, sunrise
SPEED = 1.0           # how fast the ground slides past

# The planet surface is a texture that wraps horizontally. Toward the horizon it's
# squeezed hard in depth but only gently in width, like footage from orbit.
TW, TH = 768, 128
U_SCALE, V_SCALE = 0.8, 6.4
MIPS = 5
SEA = 0.535

WHITE = (255, 255, 255)
TWILIGHT_BANDS = [  # height above the horizon (px), color
    (0.0, (255, 92, 36)),
    (0.9, (255, 176, 74)),
    (1.8, (196, 208, 250)),
    (2.8, (60, 96, 214)),
    (4.5, (0, 0, 0)),
]


def mix(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def scale(a, f):
    return (a[0] * f, a[1] * f, a[2] * f)


def add(a, b, f=1.0):
    return (a[0] + b[0] * f, a[1] + b[1] * f, a[2] + b[2] * f)


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def smooth(e0, e1, v):
    v = clamp01((v - e0) / (e1 - e0))
    return v * v * (3 - 2 * v)


_rng = random.Random(23)
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


def octave(cell, rng):
    """A layer of value noise over the texture that wraps horizontally."""
    cx = TW // cell
    grid = [[rng.random() for _ in range(cx)] for _ in range(TH // cell + 2)]
    i0s, i1s, wts = [], [], []
    for x in range(TW):
        f = x / cell
        i = int(f)
        w = f - i
        i0s.append(i % cx)
        i1s.append((i + 1) % cx)
        wts.append(w * w * (3 - 2 * w))
    out = []
    for y in range(TH):
        f = y / cell
        j = int(f)
        wy = f - j
        wy = wy * wy * (3 - 2 * wy)
        g0, g1 = grid[j], grid[j + 1]
        row = []
        for i0, i1, wx in zip(i0s, i1s, wts):
            top = g0[i0] + (g0[i1] - g0[i0]) * wx
            row.append(top + (g1[i0] + (g1[i1] - g1[i0]) * wx - top) * wy)
        out.append(row)
    return out


def fbm(cells, rng):
    total = [[0.0] * TW for _ in range(TH)]
    amp, norm = 1.0, 0.0
    for cell in cells:
        layer = octave(cell, rng)
        for trow, lrow in zip(total, layer):
            for x in range(TW):
                trow[x] += lrow[x] * amp
        norm += amp
        amp *= 0.5
    return [[v / norm for v in row] for row in total]


def mipmaps(tex, avg):
    """Horizontal mip levels, so distant ground averages instead of flickering."""
    levels = [tex]
    for _ in range(MIPS - 1):
        prev = levels[-1]
        levels.append([[avg(row[i], row[i + 1]) for i in range(0, len(row), 2)] for row in prev])
    return levels


def build_planet():
    rng = random.Random(5)
    elev = fbm((128, 64, 32, 16, 8), rng)
    moist = fbm((128, 32), rng)
    cloud = fbm((64, 32, 16, 8), rng)
    city = octave(2, rng)
    region = octave(32, rng)

    day, night, clouds = [], [], []
    for y in range(TH):
        drow, nrow, crow = [], [], []
        for x in range(TW):
            e, m = elev[y][x], moist[y][x]
            if e < SEA:
                drow.append(mix((6, 28, 80), (28, 96, 152), smooth(SEA - 0.1, SEA, e) ** 2))
                nrow.append((2, 4, 10))
            else:
                land = mix((182, 154, 104), (56, 100, 50), smooth(0.42, 0.6, m))
                land = mix(land, (120, 108, 96), smooth(SEA + 0.12, SEA + 0.17, e))
                land = mix(land, (232, 234, 242), smooth(SEA + 0.18, SEA + 0.21, e))
                drow.append(land)
                # Towns cluster in populated, lowland regions
                lights = (smooth(0.7, 0.9, city[y][x]) * smooth(0.45, 0.65, region[y][x])
                          * smooth(0.3, 0.5, m) * (1 - smooth(SEA + 0.08, SEA + 0.13, e)))
                nrow.append(mix((6, 7, 10), (255, 178, 96), lights))
            crow.append(smooth(0.52, 0.7, cloud[y][x]) * 0.92)
        day.append(drow)
        night.append(nrow)
        clouds.append(crow)

    def avg_col(a, b):
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)

    return (mipmaps(day, avg_col), mipmaps(night, avg_col),
            mipmaps(clouds, lambda a, b: (a + b) * 0.5))


class Orbit:
    def __init__(self, w, ph, planet):
        self.w, self.ph = w, ph
        self.day, self.night, self.clouds = planet
        cx = w / 2.0

        # The horizon is a huge circle: highest in the middle, curving away at the sides
        self.top = ph * 0.42
        drop = ph * 0.3
        r = max(w * 0.6, (w / 2.0) ** 2 / (2 * drop))
        self.limb = limb = [self.top + r - math.sqrt(max(0.0, r * r - (x + 0.5 - cx) ** 2)) for x in range(w)]
        d0 = ph - self.top   # depth of the bottom-center pixel: the nearest ground

        # Everything that depends only on a pixel's position is worked out once here
        self.sky = []
        self.ground = []
        for y in range(ph):
            yc = y + 0.5
            for x in range(w):
                hgt = limb[x] - yc
                if hgt > -1:
                    h = max(0.0, hgt)
                    band = (0.0, 0.0, 0.0)
                    for (h0, c0), (h1, c1) in zip(TWILIGHT_BANDS, TWILIGHT_BANDS[1:]):
                        if h < h1:
                            band = mix(c0, c1, (h - h0) / (h1 - h0))
                            break
                    air = 0.5 * math.exp(-((h - 1.3) / 0.6) ** 2)
                    dark = math.exp(-h * 0.8)
                    night = (40 * air + 10 * dark, 170 * air + 20 * dark, 100 * air + 50 * dark)
                    aur = smooth(0.3, 1.0, h) * math.exp(-max(0.0, h - 1.0) / 3.0) if h < 9 else 0.0
                    aur_col = mix((60, 255, 150), (180, 80, 255), clamp01((h - 1.5) / 4))
                    self.sky.append((x, y, math.exp(-h), band, night, aur, aur_col))
                d = yc - limb[x]
                cover = clamp01(d + 0.5)
                if cover > 0:
                    zs = d0 / max(d, 0.35)
                    span = zs ** 0.6 * U_SCALE
                    level = 0 if span < 2 else min(MIPS - 1, int(math.log2(span)))
                    iv = min(TH - 1, int(zs * V_SCALE))
                    self.ground.append((x, y, cover, level, iv, (x - cx) * span,
                                        math.exp(-d * 0.5) * 0.9, TW >> level))

        rng = random.Random(w * 7919 + ph)
        self.stars = []
        for _ in range(int(w * self.top / 12)):
            x = rng.randrange(w)
            y = rng.uniform(0, limb[x] - 1.5)
            if y >= 0:
                self.stars.append((x, int(y), rng.uniform(0.25, 1.0)))

        self.cam = 0.0
        self.flashes = []
        self.satellite = None

    def render(self, t, phase, dt):
        w, ph, limb = self.w, self.ph, self.limb
        self.cam += 10.0 * SPEED * dt

        # Sunlight. s > 0 is day; the terminator sweeps across the screen as s
        # crosses zero, arriving from the right because that's where we're headed.
        s = math.cos(math.tau * phase) + 0.2
        rising = math.sin(math.tau * phase) < 0
        lit, tw = [], []
        for x in range(w):
            sc = s - (x / w - 0.5) * 0.35
            lit.append(smooth(-0.1, 0.1, sc))
            tw.append(math.exp(-(sc / 0.16) ** 2))

        # Aurora on some nights: curtains with a bright lower edge and ragged rays
        aurora = smooth(0.25, 0.6, noise(t / 70.0, 2.2))
        curtain = None
        if aurora > 0.02:
            curtain = [aurora * smooth(0.4, 0.7, noise(x * 0.035 + t * 0.04, 3.3))
                       * (0.35 + 0.65 * noise(x * 0.45, t * 0.6)) * 1.25
                       for x in range(w)]

        # Space, stars and the glow of the atmosphere above the horizon
        fb = [[(1.0, 2.0, 6.0)] * w for _ in range(ph)]
        star_vis = clamp01(0.15 + 0.85 * (1 - s) / 1.2)
        for x, y, b in self.stars:
            fb[y][x] = add(fb[y][x], WHITE, star_vis * b * (1 - lit[x] * 0.85))

        for x, y, day_g, band, night, aur, aur_col in self.sky:
            lt, tt = lit[x], tw[x]
            dk = 1 - lt
            dg = day_g * lt
            r, g, b = fb[y][x]
            r += 90 * dg + band[0] * tt + night[0] * dk
            g += 150 * dg + band[1] * tt + night[1] * dk
            b += 255 * dg + band[2] * tt + night[2] * dk
            if curtain is not None and aur:
                a = curtain[x] * dk * aur
                r += aur_col[0] * a
                g += aur_col[1] * a
                b += aur_col[2] * a
            fb[y][x] = (r, g, b)

        # The sun pops up over the horizon at sunrise and sinks at sunset
        sun = None
        if -0.08 < s < 0.7:
            sx = w * (0.74 if rising else 0.26)
            sy = limb[min(w - 1, int(sx))] - s * ph * 1.4
            sun = (sx, sy, 1 - smooth(0.0, 0.6, s))
            self.glow(fb, sx, sy, max(5.0, ph * 0.5), (255, 214, 160), 0.9 * sun[2], above=True)
            self.disk(fb, sx, sy, max(1.0, ph * 0.1), (255, 250, 236))

        # The planet surface, in perspective
        cols = []
        for x in range(w):
            lt, tt = lit[x], tw[x]
            cols.append((lt, 0.55 + 0.45 * lt, tt * 0.3,
                         add(mix((22, 26, 38), (236, 240, 248), lt), (255, 150, 90), tt * 0.35),
                         add(mix((8, 14, 30), (140, 180, 240), lt), (255, 140, 80), tt * 0.5)))
        day, night, clouds = self.day, self.night, self.clouds
        cam = self.cam
        cloud_cam = cam + int(t * 1.5) % TW
        for x, y, cover, level, iv, base, haze, period in self.ground:
            lt, dim, warm, cc, atm = cols[x]
            lu = (int(base + cam) >> level) % period
            nr, ng, nb = night[level][iv][lu]
            dr, dg, db = day[level][iv][lu]
            if warm > 0.01:
                dr += (255 - dr) * warm
                dg += (150 - dg) * warm
                db += (90 - db) * warm
            r = nr + (dr * dim - nr) * lt
            g = ng + (dg * dim - ng) * lt
            b = nb + (db * dim - nb) * lt
            a = clouds[level][iv][(int(base + cloud_cam) >> level) % period]
            r += (cc[0] - r) * a
            g += (cc[1] - g) * a
            b += (cc[2] - b) * a
            r += (atm[0] - r) * haze
            g += (atm[1] - g) * haze
            b += (atm[2] - b) * haze
            fb[y][x] = (r, g, b) if cover >= 1 else mix(fb[y][x], (r, g, b), cover)

        # Lightning flickers inside clouds on the night side
        if random.random() < dt * 0.35 * w / 100.0:
            x = random.randrange(w)
            if lit[x] < 0.2:
                y = random.uniform(limb[x] + 1.5, ph - 0.5)
                if y < ph:
                    self.flashes.append([x, y, 0.0])
        alive = []
        for fl in self.flashes:
            fl[2] += dt
            age = fl[2]
            if age < 0.32:
                alive.append(fl)
                on = 1.0 if age < 0.06 or 0.12 < age < 0.22 else 0.25
                self.glow(fb, fl[0] + 0.5, fl[1], 2.6, (200, 214, 255), 0.85 * on)
        self.flashes = alive

        # A satellite drifts by now and then
        if self.satellite is None and random.random() < dt / 45.0:
            left = random.random() < 0.5
            self.satellite = [-2.0 if left else w + 2.0, random.uniform(0.5, self.top * 0.6), 6.0 if left else -6.0]
        if self.satellite is not None:
            sat = self.satellite
            sat[0] += sat[2] * dt
            ix, iy = int(sat[0]), int(sat[1])
            if not -3 <= sat[0] <= w + 3:
                self.satellite = None
            elif 0 <= ix < w and iy < limb[ix] - 1:
                blink = (255, 70, 60) if int(t * 1.5) % 3 == 0 else (230, 236, 255)
                fb[iy][ix] = mix(fb[iy][ix], blink, 0.85 * (0.3 + 0.7 * (1 - lit[ix])))

        # Glare from a low sun washes over everything
        if sun is not None and sun[2] > 0.05:
            sx, sy, k = sun
            self.glow(fb, sx, sy, max(8.0, ph * 0.9), (255, 200, 150), 0.35 * k)
            for x in range(w):
                streak = k * 0.55 * math.exp(-abs(x + 0.5 - sx) / (w * 0.12))
                y = int(limb[x])
                if 0 <= y < ph and streak > 0.02:
                    fb[y][x] = add(fb[y][x], (255, 220, 180), streak)

        return fb

    def glow(self, fb, cx, cy, radius, color, amount, above=False):
        if amount <= 0.01:
            return
        r2 = radius * radius
        for y in range(max(0, int(cy - radius)), min(self.ph, int(cy + radius) + 1)):
            row = fb[y]
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - radius)), min(self.w, int(cx + radius) + 1)):
                if above and y + 0.5 > self.limb[x]:
                    continue
                dx = x + 0.5 - cx
                g = amount * math.exp(-3.0 * (dx * dx + dy * dy) / r2)
                if g > 0.01:
                    row[x] = add(row[x], color, g)

    def disk(self, fb, cx, cy, r, color):
        for y in range(max(0, int(cy - r - 1)), min(self.ph, int(cy + r) + 2)):
            row = fb[y]
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - r - 1)), min(self.w, int(cx + r) + 2)):
                if y + 0.5 > self.limb[x]:
                    continue
                a = clamp01(r + 0.5 - math.hypot(x + 0.5 - cx, dy))
                if a > 0:
                    row[x] = mix(row[x], color, a)


def _q(c):
    # Steps of 4 are invisible, but let cells whose color barely moved skip a redraw
    r, g, b = c
    return (0 if r < 0 else 252 if r > 252 else int(r) & 0xFC,
            0 if g < 0 else 252 if g > 252 else int(g) & 0xFC,
            0 if b < 0 else 252 if b > 252 else int(b) & 0xFC)


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


def header_text(w):
    return (("  tuiwall  " + time.strftime("%H:%M:%S")).ljust(w)[:w],
            ("  " + time.strftime("%a %b %d")).ljust(w)[:w])


def run(fd):
    out = sys.stdout
    orbit = prev = size = header = None

    # Show the clock right away; building the planet takes a moment
    w, h = term_size()
    out.write("\x1b[0m\x1b[2J\x1b[1;1H\x1b[1m%s\x1b[0m\x1b[2;1H%s" % header_text(w))
    out.flush()
    planet = build_planet()

    last = time.time()
    while True:
        now = time.time()
        dt = min(0.25, now - last)
        last = now
        buf = []

        w, h = term_size()
        if (w, h) != size:
            size = (w, h)
            orbit = Orbit(w, (h - 2) * 2, planet) if h > 2 and w > 0 else None
            prev = header = None
            buf.append("\x1b[0m\x1b[2J")

        lines = header_text(w)
        if lines != header:
            header = lines
            buf.append("\x1b[0m\x1b[1;1H\x1b[1m%s\x1b[0m" % lines[0])
            if h > 1:
                buf.append("\x1b[2;1H%s" % lines[1])

        if orbit is not None:
            phase = (now / (ORBIT_MINUTES * 60.0)) % 1.0
            fb = orbit.render(now, phase, dt)
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
