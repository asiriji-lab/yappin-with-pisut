"""A character's viseme pictures (one per mouth shape, on white) -> a 32x32 sprite strip for the
pixel display.

    D:\\athena-face-venv\\Scripts\\python.exe viseme_sprite.py snoopy    # snoopy_visemes/ -> snoopy-sprite.png
    D:\\athena-face-venv\\Scripts\\python.exe viseme_sprite.py hearty    # hearty_visemes/ -> hearty-sprite.png
      also <name>-sprite@8x.png, <name>-sprite-preview.gif, <name>-sprite-talking.gif

The pictures are drawn separately, so the head isn't the same size or in the same place in each (the
eyes move up to ~20 px, 2-3 LED pixels: the face would shake while talking). So every picture is
scaled and slid until its head sits on M_B_P's, then the two are faded together: M_B_P's eyes, skull
and ear on top, the picture's snout, nose, jaw and neck below. The fade runs over the plain band
between the eyes and the nose, so there is no seam.

The collar (Snoopy's) or scarf (Hearty's) is M_B_P's in every frame, so the neck stays put. Where a
picture's collar sat lower than M_B_P's (the jaw dropped), the head is lifted instead, by whole LED
rows so it moves as one block, and the neck stretches down to meet the collar: the head bobs on the
neck, not floats.

Frame order: the first 7 are the order voice.py's MOUTH already sends (so a strip is a drop-in for
face-sprite.png); 7-9 are the extra shapes, for when the server learns them.
  0 rest  1 A (ah)  2 E (ee)  3 O (oh)  4 M_B_P  5 F_V  6 L_N  7 T_S  8 U_Q  9 W_R

hearty.jpeg (the 3x3 sheet) is cut into hearty_visemes/ by `viseme_sprite.py hearty --sheet hearty.jpeg`.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = ["M_B_P", "A", "E", "O", "M_B_P", "F_V", "L_N", "T_S", "U_Q", "W_R"]
BASE = "M_B_P"
SIZE = 32
KEY = (255, 0, 255)
OFF = (0, 0, 0)              # black is "off" on the panel

# Where things are, in each character's base picture (M_B_P), as (start, end) rows or columns:
#   fade  base head above, the picture's snout below, faded in between (eyes end .. nose starts)
#   keep  right of keep_cols the base stays (ear, headset) down to keep_rows
#   top   the region that must line up: rows < top[0], x < top[1]
#   lips  below the nose: thin lip lines here are kept dark, not averaged away
CHARACTERS = {
    "snoopy": dict(fade=(80, 98), keep_cols=(150, 168), keep_rows=(180, 200), top=(80, 160), lips=(137, 190)),
    "hearty": dict(fade=(86, 100), keep_cols=(160, 175), keep_rows=(140, 160), top=(86, 160), lips=(128, 175)),
}

# hearty.jpeg: the panels' insides (x and y ranges) and which mouth each one is, row by row
SHEET_X = [(55, 316), (383, 644), (708, 969)]
SHEET_Y = [(55, 319), (383, 648), (719, 982)]
SHEET_NAMES = [["A", "O", "E"], ["W_R", "T_S", "L_N"], ["U_Q", "M_B_P", "F_V"]]


def cut_sheet(sheet, folder):
    im = Image.open(sheet).convert("RGB")
    os.makedirs(folder, exist_ok=True)
    for (y0, y1), row in zip(SHEET_Y, SHEET_NAMES):
        for (x0, x1), name in zip(SHEET_X, row):
            im.crop((x0, y0, x1, y1)).save(os.path.join(folder, name + ".png"))


def load(name, folder):
    """RGB array, and a mask of the white background (white reachable from the border)."""
    im = Image.open(os.path.join(folder, name + ".png")).convert("RGB")
    w, h = im.size
    filled = im.copy()
    edge = [(x, y) for x in range(0, w, 4) for y in (0, h - 1)] + [(x, y) for y in range(0, h, 4) for x in (0, w - 1)]
    for p in edge:
        px = filled.getpixel(p)
        if px != KEY and min(px) > 225:
            ImageDraw.floodfill(filled, p, KEY, thresh=40)
    bg = np.all(np.asarray(filled) == KEY, axis=2)
    return np.asarray(im).astype(np.int16), bg


def place(img, alpha, scale, dx, dy):
    """The picture scaled about the top-left corner, then moved by (dx, dy)."""
    rgba = Image.fromarray(np.dstack([img, alpha * 255]).astype(np.uint8), "RGBA")
    data = (1 / scale, 0, -dx / scale, 0, 1 / scale, -dy / scale)
    out = np.asarray(rgba.transform(rgba.size, Image.AFFINE, data, Image.BILINEAR, fillcolor=(255, 255, 255, 0)))
    return out[:, :, :3].astype(float), out[:, :, 3] / 255


def align(img, alpha, base_img, base_alpha, top):
    """(scale, dx, dy) that best lays the picture's skull and eyes on the base's."""
    def lum(im, a):
        return np.where(a > 0.5, im.mean(2), 255)[:top[0], :top[1]]
    ref = lum(base_img, base_alpha)

    def err(sc, dx, dy):
        return np.abs(lum(*place(img, alpha, sc, dx, dy)) - ref).mean()
    best = min((err(sc, dx, dy), sc, dx, dy) for sc in np.arange(0.88, 1.13, 0.03)
               for dx in range(-24, 25, 4) for dy in range(-24, 25, 4))
    for step_s, step_t in ((0.01, 2), (0.005, 1)):     # then finer
        _, sc0, dx0, dy0 = best
        best = min([best] + [(err(sc, dx, dy), sc, dx, dy) for sc in (sc0 - step_s, sc0, sc0 + step_s)
                             for dx in (dx0 - step_t, dx0, dx0 + step_t) for dy in (dy0 - step_t, dy0, dy0 + step_t)])
    return best[1:]


def smoothstep(v, lo, hi):
    t = np.clip((v - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def snout_weight(shape, ch):
    """How much of the picture (vs the base) shows at each pixel: 0 on the eyes, skull and ear, 1 on the snout."""
    y, x = np.mgrid[:shape[0], :shape[1]]
    keep = smoothstep(x, *ch["keep_cols"]) * (1 - smoothstep(y, *ch["keep_rows"]))
    return smoothstep(y, *ch["fade"]) * (1 - keep)


def collar_rows(img, alpha):
    """First and last row of the collar: the lowest band of red (the tongue is higher up)."""
    red = (img[:, :, 0] > 150) & (img[:, :, 1] < 90) & (img[:, :, 2] < 110) & (alpha > 0.5)
    rows = np.nonzero(red[:, 70:180].sum(1) > 15)[0]
    band = np.split(rows, np.nonzero(np.diff(rows) > 3)[0] + 1)[-1]
    return int(band[0]), int(band[-1])


def shrink(a, box):
    """A full-size array (one channel, 0..1 or 0..255) -> its 32x32 cell averages."""
    big = Image.fromarray(np.clip(a, 0, 255).astype(np.float32), "F")
    return np.asarray(big.crop(box).resize((SIZE, SIZE), Image.BOX))


# ---------- colours: Snoopy's hand-set rules, or any character's own palette ----------

WHITE = (250, 250, 250)
SHADE = (170, 172, 200)      # Snoopy's lavender shading
EAR = (60, 62, 78)           # Snoopy's black ear, lifted to a dim grey (black would vanish)
RED = (215, 40, 45)
PINK = (240, 110, 120)


def snoopy_led(img, alpha, box, lips, ear):
    rgba = np.dstack([np.clip(img, 0, 255), alpha * 255]).astype(np.uint8)
    small = np.asarray(Image.fromarray(rgba, "RGBA").crop(box).resize((SIZE, SIZE), Image.BOX)).astype(int)
    ink = shrink(((img.mean(2) < 90) & (alpha > 0.5)) * 255.0, box) / 255   # share of black in each cell
    ear_small, lips_small = shrink(ear * 255.0, box) > 100, shrink(lips * 255.0, box) > 100
    r, g, b, a = (small[:, :, i] for i in range(4))
    lum, sat = small[:, :, :3].mean(2), small[:, :, :3].max(2) - small[:, :, :3].min(2)
    out = np.zeros((SIZE, SIZE, 3), int)
    red = (sat > 70) & (r > 110)                  # collar, tongue: only clearly red pixels, not grey edges
    out[red] = RED
    out[red & (g > 80)] = PINK
    grey = ~red
    out[grey & (lum >= 110)] = SHADE              # outlines (black + white averaged) go off, not pink
    out[grey & (lum >= 215)] = WHITE
    out[grey & lips_small & (ink >= 0.18)] = OFF  # a 3 px lip line split over two 8 px cells would average away
    out[a < 128] = OFF
    out[ear_small & (out.sum(2) == 0) & (a >= 128)] = EAR
    return np.dstack([out, np.where(a >= 128, 255, 0)]).astype(np.uint8)


def ink_of(img, alpha):
    return (img.max(2) < 50) & (alpha > 0.5)      # the black outline; the headset's greys are 60+


def make_palette(pictures, n=12):
    """The character's own colours: the main ones of every picture, outlines and background left out."""
    px = np.concatenate([img[(alpha > 0.5) & ~ink_of(img, alpha)] for img, alpha in pictures])
    strip = Image.fromarray(np.clip(px, 0, 255).astype(np.uint8)[None])
    q = strip.quantize(n, method=Image.Quantize.MEDIANCUT)
    return np.array(q.getpalette()[:n * 3]).reshape(n, 3)


def palette_led(img, alpha, box, lips, palette):
    """Each LED: off where the cell is mostly outline, else the palette colour nearest the cell's
    fill (outline left out of the average, so it doesn't muddy the fur)."""
    ink = ink_of(img, alpha)
    fill = (alpha > 0.5) & ~ink
    share = shrink(fill * 1.0, box)
    mean = np.dstack([shrink(img[:, :, i] * fill, box) for i in range(3)]) / np.maximum(share, 1e-6)[:, :, None]
    near = np.abs(mean[:, :, None, :] - palette[None, None]).sum(3).argmin(2)
    out = palette[near]
    a, ink_share, lips_small = shrink(alpha, box), shrink(ink * 1.0, box), shrink(lips * 1.0, box) > 0.4
    dark = (a < 0.5) | (ink_share >= 0.5) | (lips_small & (ink_share >= 0.2)) | (share < 0.15)
    out[dark] = OFF
    return np.dstack([out, np.where(a >= 0.5, 255, 0)]).astype(np.uint8)


# ---------- building ----------

def on_neck(head, collar, lift):
    """The head lifted `lift` rows, its neck stretched back down, the fixed collar on top."""
    cols = np.nonzero(collar[:, :, 3].any(0))[0]
    out = np.zeros_like(head)
    out[:SIZE - lift] = head[lift:]
    if lift:
        neck = head[:, cols]
        bottom = np.nonzero(neck[:, :, 3].any(1))[0].max()      # the neck's last row, before lifting
        for r in range(bottom - lift + 1, bottom + 1):
            out[r, cols] = np.where(out[r, cols, 3:] > 0, out[r, cols], out[bottom - lift, cols])
    out[collar[:, :, 3] > 0] = collar[collar[:, :, 3] > 0]
    return Image.fromarray(out[:, :, :3], "RGB")


def build(name, folder):
    ch = CHARACTERS[name]
    base_img, base_bg = load(BASE, folder)
    base_img, base_alpha = base_img.astype(float), (~base_bg).astype(float)
    # the collar: M_B_P's, with its outline; the same in every frame
    top, _ = collar_rows(base_img, base_alpha)
    red = (base_img[:, :, 0] > 150) & (base_img[:, :, 1] < 90) & (base_alpha > 0.5)
    red[:top - 2] = False
    xs = np.nonzero(red.any(0))[0]
    collar_cols = slice(xs.min() - 6, xs.max() + 7)
    collar_a = np.zeros_like(base_alpha)
    collar_a[top - 3:, collar_cols] = base_alpha[top - 3:, collar_cols]
    w = snout_weight(base_bg.shape, ch)
    heads, drops = {}, {}
    for pic in dict.fromkeys(FRAMES):
        img, bg = load(pic, folder)
        img, alpha = img.astype(float), (~bg).astype(float)
        sc, dx, dy = align(img, alpha, base_img, base_alpha, ch["top"]) if pic != BASE else (1, 0, 0)
        img, alpha = place(img, alpha, sc, dx, dy)
        # fade premultiplied, so the white around a picture doesn't bleed into the other's outline
        a = w * alpha + (1 - w) * base_alpha
        rgb = (w * alpha)[:, :, None] * img + ((1 - w) * base_alpha)[:, :, None] * base_img
        rgb = rgb / np.maximum(a, 1e-6)[:, :, None]
        ctop, _ = collar_rows(rgb, a)
        a[ctop + 2:, collar_cols] = 0                # the head ends where its neck goes into the collar
        heads[pic], drops[pic] = (rgb, a), ctop - top
        print(f"  {pic:6} scaled {sc:.3f}, moved ({dx:+d}, {dy:+d}) px, collar {ctop - top:+d} px")
    ys, xs = np.nonzero(np.maximum.reduce([a for _, a in heads.values()] + [collar_a]) > 0.5)
    side = max(xs.max() - xs.min(), ys.max() - ys.min()) + 3
    cell = side / SIZE
    lifts = {n: max(0, round(d / cell)) for n, d in drops.items()}     # only up: a closed jaw doesn't sink the head
    y0 = ys.min() - max(lifts.values()) * cell                          # headroom for the highest lift
    cx, cy = (xs.min() + xs.max()) // 2, int(y0 + ys.max()) // 2
    box = (cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)
    lips = np.zeros(base_bg.shape, bool)
    lips[ch["lips"][0]:ch["lips"][1], :ch["keep_cols"][0]] = True
    if name == "snoopy":
        ear = np.zeros(base_bg.shape, bool)       # the dark part of the base right of the mouth
        ear[40:200, 185:] = (base_img.mean(2) < 80)[40:200, 185:] & ~base_bg[40:200, 185:]

        def led(img, alpha):
            return snoopy_led(img, alpha, box, lips, ear)
    else:
        palette = make_palette(list(heads.values()))

        def led(img, alpha):
            return palette_led(img, alpha, box, lips, palette)
    collar = led(base_img, collar_a)
    print("  head lifted (LED rows): " + ", ".join(f"{n} {lifts[n]}" for n in heads))
    return [on_neck(led(*heads[pic]), collar, lifts[pic]) for pic in FRAMES]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("character", choices=sorted(CHARACTERS))
    p.add_argument("--sheet", help="cut this 3x3 sheet into <character>_visemes/ first (hearty.jpeg)")
    args = p.parse_args()
    folder = os.path.join(HERE, f"{args.character}_visemes")
    if args.sheet:
        cut_sheet(args.sheet, folder)
    frames = build(args.character, folder)
    out = os.path.join(HERE, f"{args.character}-sprite.png")
    strip = Image.new("RGB", (SIZE * len(frames), SIZE))
    for i, f in enumerate(frames):
        strip.paste(f, (i * SIZE, 0))
    strip.save(out)
    stem = os.path.splitext(out)[0]
    strip.resize((strip.width * 8, strip.height * 8), Image.NEAREST).save(stem + "@8x.png")
    talk = [frames[i].resize((256, 256), Image.NEAREST) for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0)]
    talk[0].save(stem + "-preview.gif", save_all=True, append_images=talk[1:], duration=400, loop=0)
    fast = [frames[i].resize((256, 256), Image.NEAREST) for i in (0, 1, 6, 2, 4, 3, 1, 5, 7, 2, 0, 0)]
    fast[0].save(stem + "-talking.gif", save_all=True, append_images=fast[1:], duration=120, loop=0)
    print(f"{out}: {len(frames)} frames ({', '.join(FRAMES)})")


if __name__ == "__main__":
    main()
