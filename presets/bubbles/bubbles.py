#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4 tabstop=4:
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4; -*-

# --- TUIWALL METADATA ---
# Name: Bubbles
# Author: Mug
# Description: Rising colorful bubbles
# Category: Ambiance 
# ------------------------

# Category types: Animation , Dashboard , Ambiance , System , Productivity , Misc

import curses
import random
import time
import math

def main(stdscr):
    # Setup Colors
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    # Vibrant high-intensity colors
    curses.init_pair(1, curses.COLOR_CYAN, -1)    
    curses.init_pair(2, curses.COLOR_MAGENTA, -1) 
    curses.init_pair(3, curses.COLOR_GREEN, -1)   
    curses.init_pair(4, curses.COLOR_YELLOW, -1)  
    curses.init_pair(6, curses.COLOR_BLUE, -1)  
    
    stdscr.nodelay(True)
    stdscr.timeout(60)

    curses.nonl()

    # Bubble shape definition (3x3 grid)
    # We use strings for each row
    BIG_BUBBLE = [
        " ## ",
        "#  #",
        " ## "
    ]
    
    HUGE_BUBBLE = [
        "  ##### ",
        " #     # ",
        "#       #",
        "#       #",
        "#       #",
        " #     # ",   
        "  #####  "
]

    # bubbles: [y, x, speed, color, wobble_phase, type]
    bubbles = []

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        # 1. Spawn a big bubble
        if random.random() < 0.2 and len(bubbles) < 10:
            bx = random.randint(5, w - 10)
            by = float(h + 2) # Start slightly below screen
            speed = random.uniform(0.15, 0.4)
            color = random.randint(1, 5)
            wobble_phase = random.uniform(0, 6.28)
            b_type = random.choice(["big", "huge"])
            
            bubbles.append([by, bx, speed, color, wobble_phase, b_type])

        # 2. Update and Draw
        for b in bubbles[:]:
            b[0] -= b[2]      # Move up
            b[4] += 0.1       # Wobble progress
            
            cur_y = int(b[0])
            # Wider drift for bigger bubbles
            cur_x = int(b[1] + (math.sin(b[4]) * 5))
            
            # Select shape
            shape = BIG_BUBBLE if b[5] == "big" else HUGE_BUBBLE
            
            # Draw each row of the ASCII bubble
            for i, line in enumerate(shape):
                draw_y = cur_y + i
                if 2 <= draw_y < h: # Don't draw over header
                    try:
                        # Use Bold for vibrancy
                        stdscr.addstr(draw_y, cur_x, line, curses.color_pair(b[3]) | curses.A_BOLD)
                    except curses.error:
                        pass

            # Remove if it floats away
            if cur_y < -4:
                bubbles.remove(b)

            # Header
            now = time.strftime("%H:%M:%S")
            date = time.strftime("%a %b %d")
    
            try:
                stdscr.addstr(0, 0, ("  tuiwall  " + now).ljust(w)[:w], curses.A_BOLD)
                stdscr.addstr(1, 0, ("  " + date).ljust(w)[:w])
            except curses.error:
                pass

        stdscr.refresh()

        if stdscr.getch() != -1:
            break

if __name__ == "__main__":
    curses.wrapper(main)
