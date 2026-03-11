#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4 tabstop=4:
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4; -*-

# --- TUIWALL METADATA ---
# Name: DVD
# Author: Mug
# Description: Bouncing DVD text
# Category: Misc
# ------------------------

import curses
import time
import random

def main(stdscr):
    # Initial Setup
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    stdscr.nodelay(True)
    
    # Initialize colors (using -1 for transparency)
    for i in range(1, 8):
        curses.init_pair(i, i, -1)

    sh, sw = stdscr.getmaxyx()
    text = "DVD"
    offset_top = 2
    
    # Ensure starting position is within the strict new bounds
    y = random.randint(offset_top, sh - 1)
    x = random.randint(0, sw - len(text) - 1)
    dy, dx = 1, 1
    current_color = random.randint(1, 7)

    while True:
        stdscr.erase()
        sh, sw = stdscr.getmaxyx()

        # 1. Header (Static at the top)
        now = time.strftime("%H:%M:%S")
        date = time.strftime("%a %b %d")
        try:
            # We use sw-1 to ensure the header doesn't trigger a wrap either
            stdscr.addstr(0, 0, f"  tuiwall  {now}".ljust(sw-4)[:sw-4], curses.A_BOLD)
            stdscr.addstr(1, 0, f"  {date}".ljust(sw-4)[:sw-4])
        except curses.error:
            pass

        # 2. Movement
        y += dy
        x += dx

        # 3. Collision Logic with "Thin" Margins
        # Vertical Bounce
        if y <= offset_top:
            y = offset_top
            dy *= -1
            current_color = random.randint(1, 7)
        elif y >= sh - 1:
            y = sh - 1
            dy *= -1
            current_color = random.randint(1, 7)

        # Horizontal Bounce
        # We subtract an extra 1 from sw to avoid the "wrap-around" column
        if x <= 0:
            x = 0
            dx *= -1
            current_color = random.randint(1, 7)
        elif x >= sw - len(text) - 4:
            x = sw - len(text) - 4
            dx *= -1
            current_color = random.randint(1, 7)

        # 4. Render
        try:
            stdscr.addstr(y, x, text, curses.color_pair(current_color) | curses.A_BOLD)
        except curses.error:
            # This catch-all prevents crashes during rapid window resizing
            pass

        stdscr.refresh()
        time.sleep(0.07)

        if stdscr.getch() != -1:
            break

if __name__ == "__main__":
    curses.wrapper(main)
