#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4 tabstop=4:
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4; -*-

# --- TUIWALL METADATA ---
# Name: Koi Pond
# Author: Mug
# Description: Koi gliding under lily pads; light, weather and season follow your clock
# Category: Ambiance
# ------------------------

# Drawn with half-block characters and 24-bit color, so each cell holds two
# square pixels, seen from above.

import math
import os
import random
import select
import sys
import termios
import time
import tty

FPS = 15
CYCLE_MINUTES = 0    # 0 follows the real clock; e.g. 6 plays a whole day every 6 minutes
FIXED_HOUR = None    # e.g. 13 for permanent midday
SEASON = None        # "spring", "summer", "autumn" or "winter"; None follows the calendar

# hour, deep water, shallow water, caustic light, daylight (0-1)
KEYFRAMES = [
    (0.0,  (4, 12, 24),   (8, 26, 42),    (60, 80, 120),   0.0),
    (5.0,  (6, 14, 28),   (10, 30, 48),   (70, 90, 130),   0.02),
    (6.5,  (20, 40, 62),  (48, 74, 92),   (230, 176, 150), 0.4),
    (9.0,  (12, 60, 72),  (30, 102, 106), (150, 226, 206), 0.85),
    (13.0, (10, 64, 78),  (28, 110, 114), (160, 236, 216), 1.0),
    (17.0, (14, 58, 70),  (36, 98, 100),  (240, 222, 164), 0.85),
    (18.8, (22, 40, 60),  (62, 72, 88),   (255, 172, 112), 0.5),
    (20.0, (8, 18, 36),   (18, 34, 54),   (96, 96, 146),   0.12),
    (21.5, (4, 12, 24),   (8, 26, 42),    (60, 80, 120),   0.0),
    (24.0, (4, 12, 24),   (8, 26, 42),    (60, 80, 120),   0.0),
]

WHITE = (255, 255, 255)
LEAF_COLORS = {
    "spring": [(255, 188, 208), (250, 214, 226), (255, 170, 196)],
    "autumn": [(214, 88, 40), (232, 140, 44), (178, 52, 40), (240, 190, 64)],
}
LEAF_SHAPES = [((0, 0), (1, 0)), ((0, 0), (1, 1)), ((0, 0), (0, 1)), ((1, 0), (0, 1)), ((0, 0), (1, 0), (0, 1))]


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
            return [mix(x, y, f) if isinstance(x, tuple) else x + (y - x) * f for x, y in zip(a, b)]
    return list(KEYFRAMES[0][1:])


def current_hour(now):
    if FIXED_HOUR is not None:
        return FIXED_HOUR % 24
    if CYCLE_MINUTES:
        return (now / 60.0 / CYCLE_MINUTES * 24) % 24
    lt = time.localtime(now)
    return lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0


def current_season(now):
    if SEASON:
        return SEASON
    month = time.localtime(now).tm_mon
    return ("winter", "spring", "summer", "autumn")[(month % 12) // 3]


_rng = random.Random(11)
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


def disk(fb, cx, cy, r, col, alpha=1.0):
    """Anti-aliased filled circle."""
    h, w = len(fb), len(fb[0])
    for y in range(max(0, int(cy - r - 1)), min(h, int(cy + r) + 2)):
        row = fb[y]
        dy = y + 0.5 - cy
        for x in range(max(0, int(cx - r - 1)), min(w, int(cx + r) + 2)):
            dx = x + 0.5 - cx
            a = r + 0.5 - math.sqrt(dx * dx + dy * dy)
            if a > 0:
                a = min(1.0, a) * alpha
                row[x] = col if a >= 1 else mix(row[x], col, a)


def stamp(mask, cx, cy, r):
    """Like disk(), but records coverage into a shadow mask."""
    h, w = len(mask), len(mask[0])
    for y in range(max(0, int(cy - r - 1)), min(h, int(cy + r) + 2)):
        row = mask[y]
        dy = y + 0.5 - cy
        for x in range(max(0, int(cx - r - 1)), min(w, int(cx + r) + 2)):
            dx = x + 0.5 - cx
            a = r + 0.5 - math.sqrt(dx * dx + dy * dy)
            if a > row[x]:
                row[x] = min(1.0, a)


def koi_colors(rng, n):
    kind = rng.choice(["kohaku", "kohaku", "sanke", "showa", "tancho", "ogon", "orange", "chagoi", "asagi"])
    white, red, black = (244, 240, 232), (232, 74, 38), (34, 30, 32)
    seed = rng.uniform(0, 200)
    cols = []
    for i in range(n):
        n1 = noise(i * 0.9 + seed, 3.3)
        n2 = noise(i * 1.7 + seed, 7.7)
        if kind == "kohaku":
            c = red if n1 > 0.45 and i > 0 else white
        elif kind == "sanke":
            c = black if n2 > 0.75 and i > 1 else red if n1 > 0.5 and i > 0 else white
        elif kind == "showa":
            c = white if n2 > 0.7 else red if n1 > 0.5 else black
        elif kind == "tancho":
            c = red if i == 1 else white
        elif kind == "ogon":
            c = mix((250, 196, 84), (255, 238, 168), n1 * 0.7)
        elif kind == "orange":
            c = mix((244, 118, 36), (255, 162, 64), n1 * 0.6)
        elif kind == "chagoi":
            c = mix((168, 110, 62), (204, 144, 82), n1)
        else:  # asagi: blue-grey back, orange toward the tail
            c = (118, 146, 178) if i < n - 2 else (228, 112, 60)
        cols.append(c)
    return cols


class Koi:
    N = 8
    PROFILE = (0.085, 0.11, 0.115, 0.105, 0.09, 0.07, 0.05, 0.035)

    def __init__(self, rng, w, ph):
        length = max(6.0, min(18.0, ph * 0.75)) * rng.uniform(0.85, 1.15)
        self.length = length
        self.seg = length / self.N
        self.radius = [length * k for k in self.PROFILE]
        self.colors = koi_colors(rng, self.N)
        self.depth = rng.uniform(0, 1)       # 0 = just under the surface
        self.seed = rng.uniform(0, 200)
        self.base_speed = rng.uniform(2.5, 5.5)
        self.speed = self.base_speed
        self.heading = rng.choice((0.0, math.pi)) + rng.uniform(-0.4, 0.4)
        x, y = rng.uniform(4, max(5, w - 4)), rng.uniform(ph * 0.3, ph * 0.7)
        dx, dy = math.cos(self.heading), math.sin(self.heading)
        self.pts = [(x - dx * self.seg * i, y - dy * self.seg * i) for i in range(self.N + 1)]

    def update(self, dt, t, w, ph, school):
        x, y = self.pts[0]
        dx, dy = math.cos(self.heading), math.sin(self.heading)

        # Steer away from the pond edges and from each other
        mx, my = 8.0, max(1.5, ph * 0.2)
        fx = (clamp01((mx - x) / mx) - clamp01((x - (w - mx)) / mx)) * 3
        fy = (clamp01((my - y) / my) - clamp01((y - (ph - my)) / my)) * 3
        for o in school:
            if o is not self:
                ox, oy = o.pts[0]
                ddx, ddy = x - ox, y - oy
                d2 = ddx * ddx + ddy * ddy
                if 0 < d2 < 30:
                    fx += ddx / d2 * 1.5
                    fy += ddy / d2 * 1.5
        want = math.atan2((dy + fy) * 0.6, dx + fx)
        diff = (want - self.heading + math.pi) % math.tau - math.pi
        wander = (noise(t * 0.25 + self.seed, 5.5) - 0.5) * 1.6
        self.heading += max(-1.6, min(1.6, diff * 2.0 + wander)) * dt

        # Koi drift slowly, then give a lazy push now and then
        target = self.base_speed * (0.5 + 0.9 * noise(t * 0.15 + self.seed, 1.1))
        self.speed += (target - self.speed) * min(1.0, dt * 1.5)
        x += math.cos(self.heading) * self.speed * dt
        y += math.sin(self.heading) * self.speed * dt
        self.pts[0] = (x, y)

        # The body follows the head like a rope, so turns bend it naturally
        for i in range(1, self.N + 1):
            px, py = self.pts[i - 1]
            qx, qy = self.pts[i]
            ddx, ddy = qx - px, qy - py
            d = math.hypot(ddx, ddy) or 1.0
            self.pts[i] = (px + ddx / d * self.seg, py + ddy / d * self.seg)

    def body(self, t):
        """Spine points with a swimming wiggle that grows toward the tail."""
        out = []
        freq = 2.0 + self.speed * 0.9
        for i, (x, y) in enumerate(self.pts):
            j = min(i, self.N - 1)
            ax, ay = self.pts[j]
            bx, by = self.pts[j + 1]
            ddx, ddy = ax - bx, ay - by
            d = math.hypot(ddx, ddy) or 1.0
            px, py = -ddy / d, ddx / d
            off = math.sin(t * freq - i * 0.9 + self.seed) * 0.4 * (i / self.N) ** 1.5
            out.append((x + px * off, y + py * off, px, py, ddx / d, ddy / d))
        return out

    def shadow(self, mask, t, s):
        off = (1.0 + 0.9 * self.depth) * s
        for i, (x, y, _, _, _, _) in enumerate(self.body(t)[:self.N]):
            stamp(mask, x + off * 1.3, y + off, self.radius[i] * 1.1)

    def draw(self, fb, t, water, light):
        dim = 0.4 + 0.6 * light
        night = (40, 60, 110)

        def shade(c):
            c = mix(scale(c, dim), night, (1 - light) * 0.2)
            return mix(c, water, self.depth * 0.45)

        pts = self.body(t)
        # Tail fin: two lobes that flap
        tx, ty, px, py, fx, fy = pts[self.N]
        flap = math.sin(t * (2.0 + self.speed * 0.9) - self.N * 0.9 + self.seed) * 0.6
        tail = shade(mix(self.colors[-1], WHITE, 0.25))
        for side in (-1, 1):
            lx = tx - fx * self.seg * 1.2 + px * (side * 0.9 + flap)
            ly = ty - fy * self.seg * 1.2 + py * (side * 0.9 + flap)
            disk(fb, lx, ly, max(0.6, self.length * 0.06), tail, 0.75)
        # Pectoral fins
        hx, hy, px, py, _, _ = pts[1]
        fin = shade(mix(self.colors[1], WHITE, 0.4))
        for side in (-1, 1):
            disk(fb, hx + px * side * (self.radius[1] + 0.5), hy + py * side * (self.radius[1] + 0.5),
                 0.55, fin, 0.6)
        for i in range(self.N - 1, -1, -1):
            x, y = pts[i][0], pts[i][1]
            disk(fb, x, y, self.radius[i], shade(self.colors[i]))
        # A soft sheen along the back
        for i in range(self.N - 2):
            x, y = pts[i][0], pts[i][1]
            disk(fb, x, y, self.radius[i] * 0.4, shade(mix(self.colors[i], WHITE, 0.35)), 0.45)


class Pond:
    def __init__(self, w, ph):
        self.w, self.ph = w, ph
        self.s = ph / 16.0
        rng = random.Random(w * 7919 + ph)

        # Mottled pebbles on the bottom, darker toward the pond edges
        self.bottom = []
        for y in range(ph):
            edge = smooth(0, max(1.0, ph * 0.3), min(y + 0.5, ph - y - 0.5))
            self.bottom.append([(0.55 * noise(x * 0.12, y * 0.24) + 0.45 * noise(x * 0.55, y * 0.9 + 20))
                                * (0.45 + 0.55 * edge) for x in range(w)])

        self.koi = [Koi(rng, w, ph) for _ in range(max(3, min(16, w * ph // 300)))]

        self.pads = []
        count = max(2, w // 28)
        for k in range(count):
            r = max(1.2, ph * rng.uniform(0.1, 0.19))
            self.pads.append({
                "x": (k + rng.uniform(0.2, 0.8)) / count * w,
                "y": rng.uniform(r, max(r, ph - r)),
                "r": r,
                "notch": rng.uniform(0, math.tau),
                "spin": rng.uniform(-0.03, 0.03),
                "flower": rng.random() < 0.35,
                "seed": rng.uniform(0, 100),
            })

        self.leaves = []
        for _ in range(max(2, w // 22)):
            self.leaves.append([rng.uniform(0, w), rng.uniform(0, ph), rng.uniform(0, 5),
                                rng.uniform(-0.6, 0.6), rng.randrange(4), rng.uniform(0, 100)])

        self.flies = [[rng.uniform(0, 100), rng.uniform(0.5, 1.5), rng.uniform(0, math.tau)]
                      for _ in range(max(2, w // 26))]
        self.ripples = []
        self.flakes = []
        self.water = None
        self.water_t = 0.0

    def caustics(self, t, deep, shallow, caustic, light):
        w, ph = self.w, self.ph
        sin = math.sin
        camp = 0.18 + 0.5 * light
        cols = [1.2 * sin(x * 0.17 - t * 0.5) for x in range(w)]
        fb = []
        for y in range(ph):
            rowphase = 1.4 * sin(y * 0.45 + t * 0.7) + t * 0.4
            sy = y * 0.5 - t * 0.3
            bottom = self.bottom[y]
            row = []
            for x in range(w):
                f = bottom[x]
                c = 1.0 - abs(sin(x * 0.22 + rowphase) + sin(sy + cols[x])) * 0.5
                c = c * c
                c = c * c * c * camp * (0.5 + f)
                base_r = deep[0] + (shallow[0] - deep[0]) * f
                base_g = deep[1] + (shallow[1] - deep[1]) * f
                base_b = deep[2] + (shallow[2] - deep[2]) * f
                row.append((base_r + (caustic[0] - base_r) * c,
                            base_g + (caustic[1] - base_g) * c,
                            base_b + (caustic[2] - base_b) * c))
            fb.append(row)
        return fb

    def ripple(self, x, y, strength):
        self.ripples.append([x, y, 0.0, 2.4, strength])

    def render(self, t, hour, season, dt):
        w, ph, s = self.w, self.ph, self.s
        deep, shallow, caustic, light = palette(hour)

        # Water with drifting caustics. They move slowly, so refreshing them a few
        # times a second looks the same and keeps the output small.
        sin = math.sin
        if self.water is None or not 0 <= t - self.water_t < 0.2:
            self.water = self.caustics(t, deep, shallow, caustic, light)
            self.water_t = t
        fb = [list(row) for row in self.water]

        # Shadows of the koi and pads on the bottom
        mask = [[0.0] * w for _ in range(ph)]
        for k in self.koi:
            k.shadow(mask, t, s)
        pads = []
        for p in self.pads:
            px = p["x"] + math.sin(t * 0.07 + p["seed"]) * 0.8
            py = p["y"] + math.cos(t * 0.05 + p["seed"]) * 0.4
            pads.append((px, py, p))
            stamp(mask, px + 2.4 * s, py + 1.6 * s, p["r"])
        strength = 0.3 + 0.25 * light
        for y in range(ph):
            row, mrow = fb[y], mask[y]
            for x in range(w):
                m = mrow[x]
                if m > 0:
                    row[x] = scale(row[x], 1 - strength * m)

        # Koi, deepest first
        for k in self.koi:
            k.update(dt, t, w, ph, self.koi)
            if random.random() < dt * 0.02:
                hx, hy = k.pts[0]
                self.ripple(hx, hy, 0.6)
        for k in sorted(self.koi, key=lambda k: -k.depth):
            k.draw(fb, t, deep, light)

        # Moonlight on the surface
        moon = clamp01(1 - light * 2.5) * 0.5
        if moon > 0.01:
            cx, cy, rx, ry = w * 0.8, ph * 0.38, max(3.0, ph * 0.55), max(1.5, ph * 0.3)
            for y in range(max(0, int(cy - ry)), min(ph, int(cy + ry) + 1)):
                row = fb[y]
                for x in range(max(0, int(cx - rx)), min(w, int(cx + rx) + 1)):
                    e = ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2
                    if e < 1:
                        shimmer = 0.5 + 0.5 * sin(y * 2.1 + t * 1.6 + 2 * sin(x * 0.35 - t))
                        row[x] = mix(row[x], (206, 214, 238), (1 - e) ** 1.5 * moon * (0.35 + 0.65 * shimmer))

        # Rain showers come and go (snow in winter)
        shower = smooth(0.6, 0.8, noise(t / 90.0 + 3.7, 1.9))
        rate = (0.12 + 4.0 * shower) * w / 100.0
        n = rate * dt
        drops = int(n) + (1 if random.random() < n - int(n) else 0)
        for _ in range(drops):
            x, y = random.uniform(0, w), random.uniform(0, ph)
            if season == "winter":
                self.flakes.append([x, y, 0.0])
                self.ripple(x, y, 0.25)
            else:
                self.ripple(x, y, 0.5 + 0.3 * random.random())

        ring_col = mix(caustic, WHITE, 0.35)
        alive = []
        for rp in self.ripples:
            x0, y0, age, life, st = rp
            rp[2] = age = age + dt
            if age >= life:
                continue
            alive.append(rp)
            r = 0.6 + age * 3.2 * s
            a0 = st * (1 - age / life) ** 1.5 * (0.5 + 0.5 * light)
            for y in range(max(0, int(y0 - r - 2)), min(ph, int(y0 + r) + 3)):
                row = fb[y]
                for x in range(max(0, int(x0 - r - 2)), min(w, int(x0 + r) + 3)):
                    d = math.hypot(x + 0.5 - x0, y + 0.5 - y0)
                    v = max(0.0, 1 - abs(d - r) * 1.4) + 0.5 * max(0.0, 1 - abs(d - r * 0.55) * 1.6)
                    if v > 0:
                        row[x] = mix(row[x], ring_col, min(1.0, v * a0 * 0.6))
        self.ripples = alive

        # Sun glints
        if light > 0.3:
            step = int(t * 2.5)
            for k in range(w // 10):
                h1 = _VAL[(_PERM[(k * 7 + step) & 255] + k) & 255]
                h2 = _VAL[(_PERM[(k * 13 + step * 3) & 255] + 5) & 255]
                x, y = int(h1 * w), int(h2 * ph)
                a = math.sin(math.pi * ((t * 2.5) % 1.0)) * (light - 0.3) * 0.9
                fb[y][x] = mix(fb[y][x], WHITE, a)

        # Lily pads
        pad = mix((20, 40, 34), (62, 134, 64), 0.25 + 0.75 * light)
        rim = scale(pad, 0.62)
        shine = mix(pad, (150, 200, 120), 0.35 * light + 0.05)
        bloom = (255, 172, 206) if season != "autumn" else (250, 236, 240)
        for px, py, p in pads:
            r = p["r"]
            notch = p["notch"] + t * p["spin"]
            for y in range(max(0, int(py - r - 1)), min(ph, int(py + r) + 2)):
                row = fb[y]
                dy = y + 0.5 - py
                for x in range(max(0, int(px - r - 1)), min(w, int(px + r) + 2)):
                    dx = x + 0.5 - px
                    d = math.sqrt(dx * dx + dy * dy)
                    a = clamp01(r + 0.5 - d)
                    if a <= 0:
                        continue
                    if d > r * 0.2:
                        da = (math.atan2(dy, dx) - notch + math.pi) % math.tau - math.pi
                        if abs(da) < 0.38:
                            continue
                    c = rim if d > r - 0.9 else mix(pad, shine, clamp01((-dx - dy) / r * 0.6))
                    row[x] = mix(row[x], c, a)
            if p["flower"] and season in ("spring", "summer") and r >= 1.5:
                fx, fy = px - math.cos(notch) * r * 0.3, py - math.sin(notch) * r * 0.3
                disk(fb, fx, fy, max(0.7, r * 0.42), scale(bloom, 0.45 + 0.55 * light))
                disk(fb, fx, fy, 0.35, scale((255, 214, 90), 0.45 + 0.55 * light))

        # Petals in spring, leaves in autumn, drifting on the breeze
        if season in LEAF_COLORS:
            colors = LEAF_COLORS[season]
            wind = (noise(t / 80.0, 4.4) - 0.5) * 1.6
            wx, wy = math.cos(wind) * 0.9, math.sin(wind) * 0.35
            for lf in self.leaves:
                x, y, rot, spin, ci, seed = lf
                x += (wx + 0.3 * math.sin(t * 0.4 + seed)) * dt
                y += (wy + 0.2 * math.cos(t * 0.3 + seed)) * dt
                lf[0] = (x + 3) % (w + 6) - 3
                lf[1] = (y + 3) % (ph + 6) - 3
                lf[2] = rot + spin * dt
                col = scale(colors[ci % len(colors)], 0.35 + 0.65 * light)
                for ox, oy in LEAF_SHAPES[int(abs(lf[2])) % len(LEAF_SHAPES)]:
                    ix, iy = int(lf[0]) + ox, int(lf[1]) + oy
                    if 0 <= ix < w and 0 <= iy < ph:
                        fb[iy][ix] = mix(fb[iy][ix], col, 0.9)

        # Snowflakes melt where they land
        flakes = []
        for fl in self.flakes:
            fl[2] += dt
            if fl[2] < 2.0:
                flakes.append(fl)
                ix, iy = int(fl[0]), int(fl[1])
                if 0 <= ix < w and 0 <= iy < ph:
                    fb[iy][ix] = mix(fb[iy][ix], (236, 242, 255), 1 - fl[2] / 2.0)
        self.flakes = flakes

        # Fireflies hover over the water on warm nights
        glow = clamp01(1 - light * 3)
        if glow > 0.02 and season != "winter":
            for seed, sp, phase in self.flies:
                x = noise(t * 0.05 * sp + seed, 1.3) * (w + 20) - 10
                y = noise(t * 0.07 * sp + seed, 6.1) * ph
                g = glow * max(0.0, math.sin(t * 1.1 * sp + phase)) ** 2
                if g < 0.02:
                    continue
                for yy in range(max(0, int(y - 3)), min(ph, int(y + 3) + 1)):
                    row = fb[yy]
                    for xx in range(max(0, int(x - 3)), min(w, int(x + 3) + 1)):
                        d2 = (xx + 0.5 - x) ** 2 + (yy + 0.5 - y) ** 2
                        row[xx] = mix(row[xx], (190, 240, 110), g * 0.5 * math.exp(-d2 / 2.5))
                if 0 <= int(x) < w and 0 <= int(y) < ph:
                    fb[int(y)][int(x)] = mix(fb[int(y)][int(x)], (236, 255, 170), g)

        return fb


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


def run(fd):
    out = sys.stdout
    pond = prev = size = header = None
    start = last = time.time()

    while True:
        now = time.time()
        dt = min(0.25, now - last)
        last = now
        buf = []

        w, h = term_size()
        if (w, h) != size:
            size = (w, h)
            pond = Pond(w, (h - 2) * 2) if h > 2 and w > 0 else None
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

        if pond is not None:
            fb = pond.render(now - start, current_hour(now), current_season(now), dt)
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
