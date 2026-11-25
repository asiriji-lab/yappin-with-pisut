"""The pixel fox (fox/png/<emotion>/, already 32x32) -> a sprite strip in the display's frame order.

    python fox_sprite.py                 # neutral -> fox-sprite.png
    python fox_sprite.py happy           # -> fox-happy-sprite.png
    python fox_sprite.py --all           # every emotion
      also <name>@8x.png and <name>-talking.gif to look at

No resizing: the faces are drawn at 32x32 and only the mouth changes between them, so they are
just put side by side. One colour is changed, the headset outline's near-black (30,27,27), see
headset_outline(): where it touches the fur it goes fully black (LED off), for the most contrast
between head and headset; where it only borders the background or the headset itself it becomes
the palette's dark grey (68,67,65), so the headset's outer edge stays lit (black = off on the panel).

Frame order: the first 7 are what the server's X-Mouth header sends, 7-9 are extra shapes.
  0 rest  1 A (ah)  2 E (ee)  3 O (oh)  4 M_B_P  5 F_V  6 L_N  7 T_S  8 U_Q  9 W_R
"""
import argparse
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(HERE, "fox", "png")
FRAMES = ["rest", "A", "E", "O", "M_B_P", "F_V", "L_N", "T_S", "U_Q", "W_R"]
EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "thinking"]
SIZE = 32
OUTLINE = (30, 27, 27)                       # the headset outline as drawn
OUTLINE_EDGE = (68, 67, 65)                  # ...against the background: dark grey, so it stays lit
OUTLINE_FUR = (0, 0, 0)                      # ...against the fur: off, the darkest the panel can do
HEADSET = {OUTLINE, OUTLINE_EDGE, (106, 106, 105), (140, 140, 139), (200, 200, 202)}   # the headset's greys


def headset_outline(img):
    """Recolour the headset outline in an RGB or RGBA image (see the module docstring)."""
    a = np.array(img)
    rgb, lit = a[:, :, :3], (a[:, :, 3] > 0 if a.shape[2] == 4 else a.max(2) > 0)
    outline = (rgb == OUTLINE).all(2) & lit
    if not outline.any():
        return img
    fur = lit & ~np.isin(rgb.astype(np.int32) @ [65536, 256, 1], [r * 65536 + g * 256 + b for r, g, b in HEADSET])
    p = np.pad(fur, 1)
    touches = p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    rgb[outline & touches] = OUTLINE_FUR
    rgb[outline & ~touches] = OUTLINE_EDGE
    return Image.fromarray(a, img.mode)


def face(emotion, mouth):
    return headset_outline(Image.open(os.path.join(PNG, emotion, f"fox_{emotion}_{mouth}.png")).convert("RGBA"))


def build(emotion):
    frames = [face(emotion, m) for m in FRAMES]
    strip = Image.new("RGBA", (SIZE * len(frames), SIZE), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        strip.paste(f, (i * SIZE, 0))
    name = "fox-sprite" if emotion == "neutral" else f"fox-{emotion}-sprite"
    out = os.path.join(HERE, name + ".png")
    strip.save(out)
    # previews on black, the way the panel shows them
    shown = Image.new("RGB", strip.size)
    shown.paste(strip, (0, 0), strip)
    shown.resize((shown.width * 8, shown.height * 8), Image.NEAREST).save(os.path.join(HERE, name + "@8x.png"))
    talk = [shown.crop((i * SIZE, 0, (i + 1) * SIZE, SIZE)).resize((256, 256), Image.NEAREST)
            for i in (0, 1, 6, 2, 4, 3, 1, 5, 7, 2, 0, 0)]
    talk[0].save(os.path.join(HERE, name + "-talking.gif"), save_all=True, append_images=talk[1:], duration=120, loop=0)
    print(f"{out}: {len(frames)} frames ({', '.join(FRAMES)})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("emotion", nargs="?", default="neutral", choices=EMOTIONS)
    p.add_argument("--all", action="store_true", help="build every emotion")
    args = p.parse_args()
    for e in (EMOTIONS if args.all else [args.emotion]):
        build(e)


if __name__ == "__main__":
    main()
