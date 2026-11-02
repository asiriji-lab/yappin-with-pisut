"""Snoopy lip-sync sprite: 7 frames of native 32x32, one head, only the mouth changes.

Frames (the order app.js / voice.py / face_bridge.py expect):
  0 neutral  1 open (ah)  2 wide (ee)  3 rounded (oo, w)  4 closed (m b p)  5 teeth (f v)  6 tongue (l th d)
Brief: proportions from Beam's reference sheet: a big wide head filling the frame, a fat snout
nearly as tall as the skull, the ear *inside* the head's left edge, a big black nose on top of the
snout, a small mouth low on the snout, collar and a short neck. Peanuts-flat (white + 1px black
outline), 8-color budget, readable on a 32x32 LED matrix (black = off there).
Run: python build.py  -> preview.png, face-sprite.png (224x32 strip), face-sprite@8x.png
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "skills", "pixel-art-studio", "scripts"))
from pixelstudio import Sprite

INK = "#16161c"        # outline, eye, nose
WHITE = "#f6f6f2"
RED = "#d62630"        # collar
RED_D = "#8e1b2a"      # collar shadow, mouth inside
PINK = "#ea6a7e"       # tongue
GLINT = "#ffffff"
EAR = "#4a4d5c"        # near-black: on the LED matrix black is "off", and a black ear would vanish
PAL = [INK, WHITE, RED, RED_D, PINK, GLINT, EAR]

MX, MY = 19, 20        # the mouth's anchor: low on the snout, right of the jaw line

s = Sprite(32, 32, palette=PAL)


def head():
    s.ellipse(2, 3, 20, 25, WHITE)            # skull: the dome sits high on the left
    s.ellipse(9, 10, 30, 25, WHITE)           # snout: wide, tall, its top a step below the dome
    s.rect(12, 24, 18, 31, WHITE)             # short neck, off the bottom edge
    s.outline(INK)
    s.ellipse(3, 12, 10, 25, INK)             # ear: a long rounded bean
    s.ellipse(4, 13, 9, 24, EAR)
    s.rect(16, 8, 16, 10, INK)                # eye: a short slanted dash
    s.px(17, 8, INK)
    s.ellipse(25, 11, 29, 14, INK)            # nose: big oval at the snout's tip
    s.px(26, 12, GLINT)
    s.rect(12, 26, 18, 27, RED)               # collar
    s.rect(12, 27, 18, 27, RED_D)
    s.line(11, 26, 11, 27, INK)
    s.line(19, 26, 19, 27, INK)


def at(points, color):
    for x, y in points:
        s.px(MX + x, MY + y, color)


def box(x0, y0, x1, y1, color):
    s.rect(MX + x0, MY + y0, MX + x1, MY + y1, color)


MOUTHS = []


def mouth(fn):
    MOUTHS.append(fn)
    return fn


@mouth
def neutral():                       # a small closed smile
    at([(0, 0), (1, 1), (2, 1), (3, 1), (4, 0)], INK)


@mouth
def open_():                         # "ah": big dark mouth, tongue at the bottom
    s.ellipse(MX - 1, MY - 2, MX + 5, MY + 3, INK)
    s.ellipse(MX, MY - 1, MX + 4, MY + 2, RED_D)
    box(1, 1, 3, 2, PINK)


@mouth
def wide():                          # "ee": wide and flat, a row of top teeth
    box(-1, -1, 6, 2, INK)
    box(0, 0, 5, 0, GLINT)
    box(0, 1, 5, 1, RED_D)


@mouth
def rounded():                       # "oo": small round O
    s.circle(MX + 2, MY, 2, INK, fill=True)
    s.px(MX + 2, MY, RED_D)


@mouth
def closed():                        # "m b p": lips pressed flat
    box(-1, 0, 5, 0, INK)


@mouth
def teeth():                         # "f v": two front teeth biting a curved lower lip
    at([(-1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 0)], INK)
    box(0, -2, 4, 0, INK)
    box(1, -1, 3, 0, GLINT)
    at([(2, -1)], INK)


@mouth
def tongue():                        # "l th d": open, tongue hanging past the jaw
    s.ellipse(MX - 1, MY - 2, MX + 5, MY + 2, INK)
    s.ellipse(MX, MY - 1, MX + 4, MY + 1, RED_D)
    box(1, 1, 3, 4, PINK)
    box(0, 2, 0, 4, INK)
    box(4, 2, 4, 4, INK)
    box(1, 5, 3, 5, INK)


head()
for _ in MOUTHS[1:]:
    s.add_frame(copy=True)
for i, draw in enumerate(MOUTHS):
    s.use(frame=i + 1)
    draw()

here = os.path.dirname(os.path.abspath(__file__))
s.preview(os.path.join(here, "preview.png"), scale=10, cols=7)
s.save_silhouette(os.path.join(here, "silhouette.png"))
s.save_spritesheet(os.path.join(here, "face-sprite.png"), layout="horizontal", json_path=None)
s.save_spritesheet(os.path.join(here, "face-sprite@8x.png"), layout="horizontal", scale=8, json_path=None)
s.stats()
