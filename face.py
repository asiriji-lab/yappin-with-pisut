"""32x32 cartoon face for the pixel display: a closed mouth (idle) and a talking loop (GIF)."""
from PIL import Image, ImageDraw

SIZE = 32
BG = (0, 0, 0)
SKIN = (255, 196, 140)
EYE = (30, 30, 30)
LIP = (200, 40, 60)
INSIDE = (90, 0, 20)
TEETH = (255, 255, 255)
TALK_SEQ = (1, 2, 3, 2, 1, 0, 2, 3, 1, 0)   # how open the mouth is, frame by frame


def frame(openness: int, skin=SKIN):
    """openness 0 = closed, 1..3 = increasingly open."""
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(img)
    d.ellipse((1, 1, 30, 30), fill=skin)
    d.rectangle((9, 10, 11, 13), fill=EYE)
    d.rectangle((20, 10, 22, 13), fill=EYE)
    if openness == 0:
        d.rectangle((10, 21, 21, 22), fill=LIP)
    else:
        top, bottom = 22 - openness, 22 + openness + 1
        d.rectangle((10, top - 1, 21, bottom + 1), fill=LIP)
        d.rectangle((11, top, 20, bottom), fill=INSIDE)
        d.rectangle((12, top, 19, top), fill=TEETH)
    return img


def save_idle(path):
    frame(0).save(path)


def save_talking(path, ms=120):
    seq = [frame(n) for n in TALK_SEQ]
    seq[0].save(path, save_all=True, append_images=seq[1:], duration=ms, loop=0, disposal=2)
