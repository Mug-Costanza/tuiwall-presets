#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4 tabstop=4:
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4; -*-

# --- TUIWALL METADATA ---
# Name: Night Drive
# Author: Mug
# Description: Cruising down the highway; the sky and the traffic follow your local time
# Category: Ambiance
# ------------------------

# Drawn with half-block characters and 24-bit color, so each cell holds two
# square pixels, in real perspective: distances are in meters.

import math
import os
import random
import select
import sys
import termios
import time
import tty

FPS = 15
SPEED = 1.0          # 1.0 is about 100 km/h
CYCLE_MINUTES = 0    # 0 follows the real clock; e.g. 6 plays a whole day every 6 minutes
FIXED_HOUR = None    # e.g. 23 for a permanent night drive

# hour, sky top, sky at the horizon, daylight (0-1)
KEYFRAMES = [
    (0.0,  (4, 6, 18),     (30, 24, 52),    0.0),
    (4.8,  (6, 8, 24),     (40, 32, 64),    0.02),
    (6.0,  (40, 46, 108),  (232, 140, 120), 0.35),
    (7.3,  (82, 132, 205), (250, 208, 178), 0.75),
    (12.5, (62, 128, 218), (176, 214, 246), 1.0),
    (16.8, (78, 118, 198), (244, 206, 162), 0.85),
    (18.4, (66, 66, 148),  (255, 150, 92),  0.6),
    (19.4, (36, 30, 90),   (228, 98, 108),  0.3),
    (20.4, (14, 15, 50),   (84, 52, 100),   0.08),
    (21.6, (4, 6, 18),     (30, 24, 52),    0.0),
    (24.0, (4, 6, 18),     (30, 24, 52),    0.0),
]

# Road layout, as distance across the road in meters (positive is to the right)
CAM_X = 1.6                 # we drive in the left of our two lanes
LAMP_X, LAMP_ARM = -1.0, 1.6
LAMP_H, LAMP_SPACING = 9.0, 50.0
LINES = [  # x, half width, albedo, dashed (paint is drawn wider than life so it reads)
    (-8.7, 0.16, (0.95, 0.95, 0.95), False),
    (-5.2, 0.14, (0.95, 0.95, 0.95), True),
    (-1.6, 0.13, (0.95, 0.72, 0.16), False),
    (-0.4, 0.13, (0.95, 0.72, 0.16), False),
    (3.2, 0.14, (0.95, 0.95, 0.95), True),
    (6.8, 0.16, (0.95, 0.95, 0.95), False),
    (8.6, 0.16, (0.58, 0.6, 0.64), False),   # guardrail
]
CAR_COLORS = [(0.75, 0.75, 0.78), (0.9, 0.9, 0.9), (0.08, 0.08, 0.1), (0.55, 0.08, 0.08),
              (0.1, 0.2, 0.5), (0.35, 0.36, 0.4), (0.15, 0.3, 0.2)]

WHITE = (255, 255, 255)
SODIUM = (255, 172, 84)
TAIL = (255, 36, 28)
HEAD = (255, 246, 222)


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


_rng = random.Random(31)
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
    return _VAL[(_PERM[(i + salt * 31) & 255] + (i >> 8) + salt) & 255]


def heading(dist):
    """Direction of the road at a point along it, in radians. Bounded, so the
    skyline and moon never wander off for good."""
    return 0.6 * math.sin(dist / 600.0) + 0.3 * math.sin(dist / 300.0 + 1.3)


def curvature(dist):
    return 0.001 * math.cos(dist / 600.0) + 0.001 * math.cos(dist / 300.0 + 1.3)


def dash_cover(z0, z1, period, on):
    """Fraction of [z0, z1] covered by dashes `on` meters long every `period` meters."""
    if z1 - z0 >= period * 4:
        return on / period

    def covered(z):
        k, r = divmod(z, period)
        return k * on + min(r, on)

    return (covered(z1) - covered(z0)) / max(1e-6, z1 - z0)


class Car:
    def __init__(self, x, z, v, oncoming, truck=False):
        self.x, self.z, self.v = x, z, v   # v is speed relative to us; positive pulls away
        self.oncoming = oncoming
        self.truck = truck
        self.color = random.choice(CAR_COLORS)
        self.width = 2.5 if truck else 1.8
        self.height = 3.8 if truck else random.uniform(1.35, 1.6)
        self.seed = random.random() * 100


class Drive:
    def __init__(self, w, ph):
        self.w, self.ph = w, ph
        self.f = max(40.0, w * 0.45)                 # focal length, px
        self.yh = ph * 0.4                           # horizon
        self.cam_h = 14.0 * (ph - 0.5 - self.yh) / self.f  # bottom row shows ground 14 m ahead
        self.dist = 0.0
        self.cars = []
        rng = random.Random(w * 7919 + ph)
        self.stars = [(rng.randrange(w), rng.uniform(0, max(0.5, self.yh - 2.5)), rng.uniform(0.3, 1.0))
                      for _ in range(int(w * self.yh / 14))]
        # Start with traffic already on the road
        for _ in range(3):
            self.cars.append(Car(random.choice((-3.4, -7.0)), random.uniform(30, 260), -50.0, True))
        self.cars.append(Car(5.0, random.uniform(40, 200), -random.uniform(3, 9), False))
        self.cars.append(Car(CAM_X, random.uniform(50, 120), -1.0, False))

    # Projection

    def gy(self, z):
        return self.yh + self.f * self.cam_h / z

    def sx(self, x, z):
        bend = curvature(self.dist + z * 0.5) * z * z * 0.5
        return self.w / 2.0 + self.f * (x + bend - self.cam_x) / z

    def headlight(self, x, z):
        if z < 2:
            return 0.0
        spread = 2.2 + 0.12 * z
        return math.exp(-((x - self.cam_x) / spread) ** 2) / (1 + (z / 45.0) ** 2) * smooth(2, 8, z)

    def render(self, t, hour, dt, clock=None):
        w, ph, f, yh = self.w, self.ph, self.f, self.yh
        top, hor, light = palette(hour)
        night = clamp01(1 - light * 2.2)
        speed = 27.0 * SPEED
        self.dist += speed * dt
        dist = self.dist
        self.cam_x = CAM_X + 0.12 * math.sin(t * 0.25)
        head = heading(dist)

        # Weather: showers come and go, and the road stays wet a while after
        clock = t if clock is None else clock
        rain = smooth(0.6, 0.75, noise(clock / 150.0, 7.7))
        wet = max(rain, 0.35 * night)

        # Light falling on everything: sky light plus sodium lamps after dark
        amb = add(scale(mix(hor, (255, 255, 255), 0.5), 0.9 * light), (14, 16, 28), night)
        lamp_on = smooth(0.3, 0.7, night + 0.25)
        lamps = []
        first = LAMP_SPACING - dist % LAMP_SPACING
        z = first
        while z < 260:
            lamps.append(z)
            z += LAMP_SPACING
        fog_col = mix(hor, top, 0.15)

        # Sky
        fb = []
        for y in range(ph):
            if y < yh:
                fb.append([mix(top, hor, clamp01((y + 0.5) / yh) ** 1.6)] * w)
            else:
                fb.append([fog_col] * w)
        star_a = clamp01(1 - light * 3)
        if star_a > 0.01:
            for x, y, b in self.stars:
                yi = int(y)
                fb[yi][x] = add(fb[yi][x], WHITE, star_a * b * (0.7 + 0.3 * math.sin(t * 1.3 + x)))

        # The moon by night, a low sun ahead in the evening
        if night > 0.3:
            self.disk(fb, w / 2.0 + f * (0.35 - head), yh * 0.35, max(0.9, ph * 0.09),
                      (236, 232, 214), night, glow=(110, 120, 160))
        sun_e = (19.3 - hour) / 2.2
        if 0 < hour < 24 and -0.1 < sun_e < 1:
            self.disk(fb, w / 2.0 + f * (-0.2 - head), yh - 0.5 - sun_e * (yh - 1), max(1.2, ph * 0.14),
                      mix((255, 120, 50), (255, 236, 200), clamp01(sun_e)), 1.0, glow=(255, 170, 110))

        # Mountains and a city skyline on the horizon
        mtn = scale(mix(top, hor, 0.55), 0.55 + 0.2 * light)
        city = scale(mix(top, hor, 0.3), 0.3 + 0.25 * light)
        shift = f * head
        for x in range(w):
            i = int(x + shift) + 100000
            m = (noise(i * 0.02, 5.0) * 0.7 + noise(i * 0.08, 9.0) * 0.3) * min(3.0, yh * 0.5)
            block = i // 4
            urban = smooth(0.35, 0.6, noise(i * 0.012, 1.0))
            bh = 0.0
            if hash01(block, 1) > 0.3:
                bh = (0.6 + hash01(block, 2) ** 2 * 3.4) * urban * min(1.0, yh / 7.0)
            for y in range(max(0, int(yh - max(m, bh)) - 1), min(ph, int(yh) + 1)):
                above = yh - (y + 0.5)
                if above < bh:
                    c = city
                    if night > 0.1 and hash01(i * 7 + y, 3) > 0.62:
                        c = mix(city, (255, 196, 120), night * (0.5 + 0.5 * hash01(i + y * 13, 4)))
                    if bh > 2.5 and above > bh - 1 and (i % 4 == 1) and int(t * 1.2 + block) % 2 == 0:
                        c = mix(c, (255, 40, 30), night)
                    fb[y][x] = c
                elif above < m:
                    fb[y][x] = mtn

        # The road surface, row by row
        hood_glow = 0.0
        for y in range(int(yh), ph):
            y0 = max(float(y), yh)
            if y + 1 <= yh:
                continue
            cover = y + 1 - y0
            zc = f * self.cam_h / ((y0 + y + 1) / 2 - yh)
            zfar = f * self.cam_h / (y0 - yh) if y0 > yh else 1e9
            znear = f * self.cam_h / (y + 1 - yh)
            m_per_px = zc / f
            x0 = self.cam_x - curvature(dist + zc * 0.5) * zc * zc * 0.5 - (w / 2.0) * m_per_px
            fog = 1 - math.exp(-zc / 280.0)
            dash = dash_cover(znear + dist, zfar + dist, 12.0, 4.5)

            # Base surface for each pixel across the row
            alb = []
            for x in range(w):
                X = x0 + (x + 0.5) * m_per_px
                if X < -9.2 or X > 9.0:
                    alb.append((0.16, 0.26, 0.12))       # verge
                elif -1.4 < X < -0.6:
                    alb.append((0.45, 0.45, 0.43))       # concrete median
                elif X > 6.9 or X < -8.8:
                    alb.append((0.27, 0.27, 0.28))       # shoulder
                else:
                    alb.append((0.21, 0.21, 0.23))       # asphalt
            for lx, hw, la, dashed in LINES:
                k = dash if dashed else 1.0
                cxp = (lx - x0) / m_per_px
                hwp = hw / m_per_px
                for x in range(max(0, int(cxp - hwp - 1)), min(w, int(cxp + hwp) + 2)):
                    c = clamp01(hwp + 0.5 - abs(x + 0.5 - cxp)) * k
                    if c > 0:
                        alb[x] = mix(alb[x], la, c)

            # Light it: sky light, our headlights, pools under the lamps
            near = [lz for lz in lamps if abs(lz - zc) < 30] if lamp_on > 0.01 else []
            row = fb[y]
            for x in range(w):
                X = x0 + (x + 0.5) * m_per_px
                hb = self.headlight(X, zc) * night * 420
                lr, lg, lb = amb[0] + hb, amb[1] + hb * 0.94, amb[2] + hb * 0.85
                for lz in near:
                    dz2 = (zc - lz) ** 2 / 90.0
                    p = 0.0
                    for hx in (LAMP_X - LAMP_ARM, LAMP_X + LAMP_ARM):
                        p += math.exp(-((X - hx) ** 2 / 30.0 + dz2))
                    p *= lamp_on * 300
                    lr += SODIUM[0] / 255.0 * p
                    lg += SODIUM[1] / 255.0 * p
                    lb += SODIUM[2] / 255.0 * p
                a = alb[x]
                c = (a[0] * lr, a[1] * lg, a[2] * lb)
                if wet > 0.01:  # wet asphalt mirrors a little of the sky
                    c = mix(c, hor, wet * 0.12 * (1 - fog))
                c = mix(c, fog_col, fog)
                row[x] = c if cover >= 1 else mix(row[x], c, cover)

        # Things beside and over the road, far to near
        sprites = []
        for lz in lamps:
            sprites.append((lz, "lamp", None))
        z = 25.0 - dist % 25.0
        while z < 200:
            sprites.append((z, "post", None))
            z += 25.0
        gz = 700.0 - (dist + 300.0) % 700.0
        if gz < 260:
            sprites.append((gz, "gantry", int((dist + 300.0) // 700.0)))
        self.traffic(dt, speed, hour, light)
        for car in self.cars:
            sprites.append((car.z, "car", car))
        sprites.sort(key=lambda s: -s[0])

        glows = []
        for z, kind, obj in sprites:
            if z < 1.5:
                continue
            if kind == "lamp":
                self.draw_lamp(fb, z, amb, lamp_on, glows)
            elif kind == "post":
                x = self.sx(8.3, z)
                y = self.gy(z) - f * 0.9 / z
                lit = 0.25 + self.headlight(8.3, z) * 3.0 * night
                self.dot(fb, x, y, max(0.5, f * 0.12 / z), mix((180, 180, 180), (255, 190, 90), night), lit)
            elif kind == "gantry":
                self.draw_gantry(fb, z, obj, amb, night)
            else:
                self.draw_car(fb, obj, amb, night, glows)

        # Bloom around lights, and their streaky reflections on wet road
        for x, y, r, col, a, z in glows:
            self.glow(fb, x, y, r, col, a)
            if wet > 0.05:
                gy = self.gy(z)
                length = (gy - y) * 1.3 + 2
                for k in range(int(length)):
                    yy = int(gy + k)
                    if yy >= ph:
                        break
                    ix = int(x)
                    if 0 <= ix < w and yy >= yh:
                        fb[yy][ix] = add(fb[yy][ix], col, a * wet * 0.35 * (1 - k / length))

        # Rain catching the light
        if rain > 0.02:
            for _ in range(int(w * ph * rain / 90)):
                x, y = random.randrange(w), random.uniform(0, ph - 1)
                b = 0.1 + 0.25 * night
                for k in (0, 1):
                    yy, xx = int(y) + k, x - k
                    if 0 <= xx < w and yy < ph:
                        fb[yy][xx] = mix(fb[yy][xx], (190, 200, 220), b * rain * (1 - 0.4 * k))

        return fb

    def traffic(self, dt, speed, hour, light):
        busy = 0.6 + 0.6 * max(math.exp(-((hour - 8.0) / 1.5) ** 2), math.exp(-((hour - 17.5) / 2.0) ** 2),
                                 0.4 * light)
        for car in self.cars:
            if not car.oncoming and car.x < 3:
                # Cars in our lane keep a comfortable distance, then wander off
                want = 2.5 if car.seed > 60 else (-1.0 if car.z > 45 else 1.5)
                car.v += (want - car.v) * min(1.0, dt * 0.4)
            car.z += car.v * dt
        self.cars = [c for c in self.cars if 1.5 < c.z < 280]

        if random.random() < dt * 0.6 * busy:
            lane = random.choice((-3.4, -7.0))
            self.cars.append(Car(lane, 270.0, -(speed + random.uniform(20, 30)), True,
                                 truck=random.random() < 0.15))
        if random.random() < dt * 0.15 * busy:
            if all(c.z < 240 for c in self.cars if c.x == 5.0):
                self.cars.append(Car(5.0, 260.0, -random.uniform(3, 9), False, truck=random.random() < 0.3))
        if random.random() < dt * 0.05 and sum(1 for c in self.cars if c.x == CAM_X) < 2:
            if all(c.z < 200 for c in self.cars if c.x == CAM_X):
                self.cars.append(Car(CAM_X, 250.0, -2.0, False))

    # Drawing helpers

    def glow(self, fb, cx, cy, radius, color, amount):
        if amount <= 0.01:
            return
        r2 = radius * radius
        for y in range(max(0, int(cy - radius)), min(self.ph, int(cy + radius) + 1)):
            row = fb[y]
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - radius)), min(self.w, int(cx + radius) + 1)):
                dx = x + 0.5 - cx
                g = amount * math.exp(-3.0 * (dx * dx + dy * dy) / r2)
                if g > 0.01:
                    row[x] = add(row[x], color, g)

    def disk(self, fb, cx, cy, r, color, alpha, glow=None):
        if glow is not None:
            self.glow(fb, cx, cy, r * 5, glow, 0.35 * alpha)
        for y in range(max(0, int(cy - r - 1)), min(self.ph, int(cy + r) + 2)):
            if y >= self.yh:
                break
            row = fb[y]
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - r - 1)), min(self.w, int(cx + r) + 2)):
                a = clamp01(r + 0.5 - math.hypot(x + 0.5 - cx, dy)) * alpha
                if a > 0:
                    row[x] = mix(row[x], color, a)

    def dot(self, fb, cx, cy, r, color, alpha):
        if alpha <= 0.01:
            return
        for y in range(max(0, int(cy - r)), min(self.ph, int(cy + r) + 1)):
            for x in range(max(0, int(cx - r)), min(self.w, int(cx + r) + 1)):
                fb[y][x] = mix(fb[y][x], color, min(1.0, alpha))

    def rect(self, fb, x0, x1, y0, y1, color, alpha=1.0):
        """Anti-aliased filled rectangle in screen pixels."""
        for y in range(max(0, int(y0)), min(self.ph, int(y1) + 1)):
            cy = min(y + 1, y1) - max(y, y0)
            if cy <= 0:
                continue
            row = fb[y]
            for x in range(max(0, int(x0)), min(self.w, int(x1) + 1)):
                cx = min(x + 1, x1) - max(x, x0)
                if cx > 0:
                    a = min(1.0, cx * cy * alpha)
                    row[x] = color if a >= 1 else mix(row[x], color, a)

    def lit(self, albedo, amb, extra=0.0):
        return (albedo[0] * (amb[0] + extra), albedo[1] * (amb[1] + extra), albedo[2] * (amb[2] + extra))

    def draw_lamp(self, fb, z, amb, lamp_on, glows):
        f = self.f
        base = self.gy(z)
        top = base - f * LAMP_H / z
        x = self.sx(LAMP_X, z)
        half = max(0.3, f * 0.12 / z)
        pole = self.lit((0.35, 0.36, 0.38), amb, 30 * lamp_on)
        self.rect(fb, x - half, x + half, top, base, pole)
        for side in (-1, 1):
            hx = self.sx(LAMP_X + side * LAMP_ARM, z)
            self.rect(fb, min(x, hx), max(x, hx), top, top + max(0.4, f * 0.15 / z), pole)
            if lamp_on > 0.01:
                r = max(0.5, f * 0.3 / z)
                self.rect(fb, hx - r, hx + r, top, top + r * 0.8, SODIUM, lamp_on)
                glows.append((hx, top + 0.3, min(5.0, max(1.2, f * 1.5 / z)), SODIUM,
                              0.5 * lamp_on * min(1.0, max(0.15, 35.0 / z)), z))

    def draw_gantry(self, fb, z, index, amb, night):
        f = self.f
        base = self.gy(z)
        y_at = lambda h: base - f * h / z
        steel = self.lit((0.4, 0.42, 0.45), amb)
        for px in (-1.3, 9.0):
            x = self.sx(px, z)
            half = max(0.3, f * 0.15 / z)
            self.rect(fb, x - half, x + half, y_at(6.8), base, steel)
        self.rect(fb, self.sx(-1.3, z), self.sx(9.0, z), y_at(6.8), y_at(6.4), steel)
        sign = add(self.lit((0.04, 0.32, 0.14), amb), (8, 70, 30), night)
        text = mix(self.lit((0.9, 0.9, 0.9), amb), (230, 236, 230), night)
        for k, (sx0, sx1) in enumerate(((0.2, 3.0), (3.6, 6.4))):
            x0, x1 = self.sx(sx0, z), self.sx(sx1, z)
            y0, y1 = y_at(6.2), y_at(4.6)
            self.rect(fb, x0, x1, y0, y1, sign)
            if y1 - y0 >= 3 and x1 - x0 >= 6:
                # A few rows of "lettering"
                for yy in range(int(y0) + 1, int(y1) - 0):
                    if (yy - int(y0)) % 2 == 0:
                        continue
                    for xx in range(int(x0) + 1, int(x1) - 1):
                        if hash01(xx - int(x0) + k * 37 + index * 11, yy - int(y0)) > 0.45 and 0 <= xx < self.w and 0 <= yy < self.ph:
                            fb[yy][xx] = mix(fb[yy][xx], text, 0.85)

    def draw_car(self, fb, car, amb, night, glows):
        f, z = self.f, car.z
        base = self.gy(z)
        top = base - f * car.height / z
        x0, x1 = self.sx(car.x - car.width / 2, z), self.sx(car.x + car.width / 2, z)
        if x1 < 0 or x0 > self.w or top > self.ph:
            return
        lit_by_us = 0.0 if car.oncoming else self.headlight(car.x, z) * night * 220
        body = self.lit(car.color, amb, lit_by_us)
        glass = self.lit((0.06, 0.07, 0.09), amb, lit_by_us * 0.3)
        dark = self.lit((0.04, 0.04, 0.05), amb)
        hgt = base - top
        y_at = lambda u: base - hgt * u
        self.rect(fb, x0, x1, y_at(0.12), base, dark)
        if car.truck:
            self.rect(fb, x0, x1, top, y_at(0.12), body)
        else:
            self.rect(fb, x0, x1, y_at(0.55), y_at(0.12), body)
            inset = (x1 - x0) * 0.08
            self.rect(fb, x0 + inset, x1 - inset, y_at(0.92), y_at(0.55), glass)
            self.rect(fb, x0 + inset, x1 - inset, top, y_at(0.92), body)

        # Lights: taillights on cars ahead, headlights on oncoming traffic
        wpx = x1 - x0
        if car.oncoming:
            col, u0, u1, k = HEAD, 0.28, 0.42, 0.5 + 0.5 * night
        else:
            braking = noise(car.seed + self.dist * 0.01, 2.0) > 0.72
            col, u0, u1, k = TAIL, 0.36, 0.5, 0.4 + 0.6 * night + (0.3 if braking else 0.0)
        ly0, ly1 = y_at(u1 if not car.truck else 0.3), y_at(u0 if not car.truck else 0.18)
        for a, b in ((0.04, 0.22), (0.78, 0.96)):
            lx0, lx1 = x0 + wpx * a, x0 + wpx * b
            self.rect(fb, lx0, lx1, ly0, ly1, mix(body, col, min(1.0, k)))
            if car.oncoming:
                r, a = min(6.0, max(1.8, f * 1.6 / z)), k * 0.7
            else:
                r, a = min(4.0, max(1.3, f * 0.9 / z)), k * 0.45
            glows.append(((lx0 + lx1) / 2, (ly0 + ly1) / 2, r, col, a, z))
        if car.truck and night > 0.2:
            for xx in (x0 + 0.3, x1 - 0.3):
                glows.append((xx, top + 0.3, min(3.0, max(1.0, f * 0.5 / z)), (255, 160, 40), 0.5 * night, z))


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
    drive = prev = size = header = None
    start = last = time.time()

    while True:
        now = time.time()
        dt = min(0.25, now - last)
        last = now
        buf = []

        w, h = term_size()
        if (w, h) != size:
            size = (w, h)
            drive = Drive(w, (h - 2) * 2) if h > 2 and w > 0 else None
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

        if drive is not None:
            fb = drive.render(now - start, current_hour(now), dt, now)
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
