"""The pixel fox, alive on the LED panel: the same face the web page draws (KP's fox-avatar.js), so
it breathes, blinks, glances around, nods while listening, sweeps its visor while searching, shows
"..." while thinking, a "found it!" beat, a flinch when cut off, and talks with a head bob, in the
emotion the answer calls for.

The frame logic is a port of FoxAvatar._frame in avatar/fox-avatar/pixel_fox/web/fox-avatar.js and
draws from the same atlas (fox/web/atlas.json + atlas.png, copied from that folder): change the
behaviour there and here together.

    fox = FoxLive(face.pixels).start()      # face = face_bridge.Face(...), connected
    fox.set_state("listening") / ("searching") / ("thinking") / ("idle") / ("sorry") / ("error")
    fox.found("thinking")                   # short "got it!" beat
    fox.speak(cues, start=time.monotonic()) # cues [{start, end, mouth}] in seconds from `start`
    fox.end_speech()                        # the answer is over: back to idle
    fox.interrupt()                         # the user cut in

    python fox_live.py --preview out.gif    # ~15 s of every state, no panel needed
    python fox_live.py --panel              # the same on the panel
    python fox_live.py --tune               # pick the panel's colour settings by eye
"""
import argparse
import json
import math
import os
import random
import re
import threading
import time

from PIL import Image

from fox_sprite import headset_outline

HERE = os.path.dirname(os.path.abspath(__file__))
ATLAS = os.path.join(HERE, "fox", "web")
TICK = 1000 / 12                           # ms: animation drawn "on twos", as on the web
XMOUTH = ["rest", "A", "E", "O", "M_B_P", "F_V", "L_N"]   # Athena's X-Mouth frame numbers -> the fox's mouths


def rand(a, b):
    return a + random.random() * (b - a)


def cues_from_points(points, tail=0.15):
    """[(seconds, mouth)] -> [{start, end, mouth}] (as _fromPoints on the web)."""
    pts = sorted(points)
    return [{"start": t, "end": pts[i + 1][0] if i + 1 < len(pts) else t + tail, "mouth": m}
            for i, (t, m) in enumerate(pts)]


def cues_from_xmouth(points, seconds):
    """Athena's X-Mouth [(seconds, frame 0-6)] for a sentence `seconds` long -> fox cues."""
    pts = [(t, XMOUTH[f]) for t, f in points if 0 <= f < len(XMOUTH)]
    return cues_from_points(pts + [(seconds, "rest")])


class FoxLive:
    def __init__(self, send, atlas_dir=ATLAS, lead=0.04, clock=time.monotonic):
        with open(os.path.join(atlas_dir, "atlas.json"), encoding="utf-8") as f:
            self.A = json.load(f)
        self.S = S = self.A["size"]
        sheet = Image.open(os.path.join(atlas_dir, self.A["image"])).convert("RGBA")
        self.layers = {name: sheet.crop((x, y, x + S, y + S)) for name, (x, y) in self.A["layers"].items()}
        self.rules = [(re.compile(p, re.I), e) for p, e in self.A.get("emotion_rules", [])]
        self.send, self.lead, self.clock = send, lead, clock
        self.lock = threading.RLock()
        now = self._now()
        self.state, self.emotion, self.mouth, self.eyes = "idle", "neutral", "rest", "neutral"
        self._since = now
        self._next_blink = now + rand(1500, 3500)
        self._blink_at = -1e9
        self._next_glance = now + rand(5000, 9000)
        self._glance = None
        self._bob_until = self._last_bob = 0
        self._speech = None
        self._found = None
        self._interrupt_at = -1e9
        self._running = False

    def _now(self):
        return self.clock() * 1000

    # ---------------------------------------------------------------- public API
    def set_state(self, state, emotion=None):
        with self.lock:
            if self.state == "speaking" and state != "speaking":
                self._speech = None
            self.state = state
            if emotion:
                self.set_emotion(emotion)
            if state in ("sorry", "error"):
                self.emotion = state
            elif state == "idle" and not emotion and self.emotion in ("sorry", "error"):
                self.emotion = "neutral"
            self._since = self._now()

    def set_emotion(self, emotion):
        with self.lock:
            self.emotion = emotion if emotion in self.A["emotions"] else "neutral"

    def pick_emotion(self, text):
        for pattern, emotion in self.rules:
            if pattern.search(text or ""):
                return emotion
        return "neutral"

    def found(self, then="thinking", ms=700):
        """A short "found it!" beat (surprised eyes, smile, "!"), then `then`."""
        with self.lock:
            self._found = {"until": self._now() + ms, "then": then}

    def speak(self, cues, start):
        """Lip-sync one sentence: cues [{start, end, mouth}] in seconds from `start` (on self.clock)."""
        with self.lock:
            if self.state != "speaking" or self._speech is None:
                self._found = None
                self._speech = {"cues": []}
                self.state = "speaking"
                self._since = self._now()
            sp = self._speech["cues"]
            sp.extend({"start": c["start"] + start, "end": c["end"] + start, "mouth": c["mouth"]} for c in cues)
            sp.sort(key=lambda c: c["start"])

    def end_speech(self, then="idle"):
        with self.lock:
            if self.state == "speaking":
                self._speech = None
            self.set_state(then)

    def interrupt(self):
        with self.lock:
            self._interrupt_at = self._now()
            self._speech = None
            self.set_state("listening", emotion="neutral")

    def start(self, fps=30):
        """Render on a thread; each changed frame goes to send(rgb bytes). The animation steps at 12 fps,
        rendering faster only catches mouth changes sooner; unchanged frames aren't sent."""
        self._running = True

        def run():
            last = None
            while self._running:
                rgb = self.frame().tobytes()
                if rgb != last:
                    try:
                        self.send(rgb)
                        last = rgb
                    except Exception:            # noqa: BLE001 - the panel may drop out; keep animating
                        pass
                time.sleep(1 / fps)
        threading.Thread(target=run, daemon=True, name="fox").start()
        return self

    def stop(self):
        self._running = False

    # ---------------------------------------------------------------- drawing (port of _frame)
    @staticmethod
    def _cue_at(cues, t):
        lo, hi = 0, len(cues) - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            c = cues[mid]
            if t < c["start"]:
                hi = mid - 1
            elif t >= c["end"]:
                lo = mid + 1
            else:
                return c["mouth"]
        return None

    def frame(self):
        """The current 32x32 frame, RGB on black (transparent = LED off)."""
        with self.lock:
            return self._frame(self._now())

    def _frame(self, now):
        E = self.A["emotions"]
        tick = math.floor(now / TICK)
        since = now - self._since
        emo = self.emotion
        eyes = mouth = None
        extras, dy, blink_set = [], 0, emo

        if self.state == "speaking":
            sp = self._speech
            if not sp:
                self.state, mouth, eyes = "idle", "rest", E[emo]["eyes"]
            else:
                mouth = self._cue_at(sp["cues"], now / 1000 + self.lead) or "rest"
                eyes, extras = E[emo]["eyes"], list(E[emo]["extras"])
                # a small head bob on the first open vowel after a pause or every ~1 s
                if mouth != self.mouth and mouth in ("A", "O", "E") and now - self._last_bob > 1100:
                    self._bob_until, self._last_bob = now + 2 * TICK, now
                dy = 1 if now < self._bob_until else 0
        elif self.state == "listening":
            emo = blink_set = "neutral"
            eyes, mouth = "neutral", "rest"
            p = since % 3600                     # nod every 3.6 s
            if 1800 < p < 1800 + 7 * TICK:
                dy = [1, 1, 2, 2, 2, 1, 1][min(6, math.floor((p - 1800) / TICK))]
                eyes = "neutral_half"
        elif self.state == "searching":
            emo = blink_set = "neutral"
            eyes, mouth = "look_down", "hmm"
            k = tick % 10
            extras = ["scan" + str(k + 1 if k < 6 else 11 - k)]      # 1..6..2 ping-pong
        elif self.state == "thinking":
            emo = blink_set = "thinking"
            eyes, mouth = "thinking", "hmm"
            n = math.floor(since / (4 * TICK)) % 4
            if n:
                extras = ["dots" + str(n)]
        elif self.state == "error":
            emo = blink_set = "error"
            eyes, mouth = "dizzy", "wavy"
            if since % 3000 < 8 * TICK:
                extras = ["static" + str(tick % 2 + 1)]
        else:                                    # idle, sorry
            if self.state == "sorry":
                emo = blink_set = "sorry"
            eyes, mouth, extras = E[emo]["eyes"], E[emo]["idle"], list(E[emo]["extras"])
            dy = math.floor(since / 700) % 2     # breathing
            if emo == "neutral":                 # glance around now and then
                if not self._glance and now > self._next_glance:
                    self._glance = {"eyes": random.choice(["look_left", "look_right"]), "until": now + 900}
                if self._glance:
                    if now < self._glance["until"]:
                        eyes = self._glance["eyes"]
                    else:
                        self._glance, self._next_glance = None, now + rand(6000, 11000)

        # "found it!" beat and the interrupt flinch override everything briefly
        if self._found:
            if now < self._found["until"]:
                eyes, mouth, extras, dy, blink_set = "surprised", "smile", ["exclaim"], 0, None
            else:
                then, self._found = self._found["then"], None
                self.set_state(then)
        if now - self._interrupt_at < 3 * TICK:
            eyes, mouth, dy, blink_set = "surprised", "M_B_P", 0, None

        # blink: half, closed, half (1 tick each)
        if now >= self._next_blink:
            self._blink_at, self._next_blink = now, now + rand(2200, 5200)
        b = math.floor((now - self._blink_at) / TICK)
        bs = blink_set and E[blink_set]
        if bs and bs.get("closed") and 0 <= b < 3 and eyes in (bs["eyes"], "neutral"):
            eyes = bs["closed"] if b == 1 else (bs.get("half") or bs["closed"])

        self.mouth, self.eyes = mouth, eyes
        S = self.S
        img = Image.new("RGBA", (S, S))
        for name in ["base"] + ["extras/" + x for x in extras] + ["mouths/" + mouth, "eyes/" + eyes]:
            layer = self.layers.get(name)
            if layer is None:
                continue
            if dy:
                shifted = Image.new("RGBA", (S, S))
                shifted.paste(layer.crop((0, 0, S, S - dy)), (0, dy))
                layer = shifted
            img = Image.alpha_composite(img, layer)
        out = Image.new("RGB", (S, S))
        out.paste(img, (0, 0), img)
        return headset_outline(out)          # on the whole frame: which outline pixels touch fur


# -------------------------------------------------------------------- demo / tuning
def script(fox, t0):
    """Every state once, ~15 s: (time, action)."""
    talk = cues_from_points([(i * 0.11, m) for i, m in enumerate(
        ["A", "L_N", "E", "rest", "M_B_P", "O", "A", "F_V", "rest", "E", "T_S", "A",
         "O", "rest", "M_B_P", "E", "A", "rest", "O", "A", "L_N", "E", "rest", "A", "M_B_P", "O", "rest"])])
    return [
        (0.0, lambda: fox.set_state("idle")),
        (4.0, lambda: fox.set_state("listening")),
        (6.5, lambda: fox.set_state("searching")),
        (8.5, lambda: fox.found("thinking", 500)),
        (9.0, lambda: None),
        (10.5, lambda: (fox.set_emotion("happy"), fox.speak(talk, start=t0 + 10.5))),
        (13.6, lambda: fox.end_speech()),
        (15.5, lambda: None),
    ]


def preview(path, seconds=15.5, fps=12):
    t = [0.0]
    fox = FoxLive(lambda rgb: None, clock=lambda: t[0])
    steps = script(fox, 0.0)
    frames = []
    for i in range(int(seconds * fps)):
        t[0] = i / fps
        while steps and steps[0][0] <= t[0]:
            steps.pop(0)[1]()
        frames.append(fox.frame().resize((256, 256), Image.NEAREST))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=round(1000 / fps), loop=0)
    print(f"{path}: {len(frames)} frames, {seconds:.0f} s")


def connect(args):
    import logging
    from face_bridge import DISPLAY_ADDRESS, Face
    # idotmatrix turns on DEBUG logging for everything when it's imported; back to warnings only
    logging.basicConfig(level=logging.WARNING, format="%(message)s", force=True)
    face = Face(args.display or DISPLAY_ADDRESS, None, 0.0, brightness=args.brightness)
    print("Connecting to the pixel display...")
    if not face.connect():
        raise SystemExit("  Display not found (on? phone app disconnected? another program using it?)")
    print("  connected")
    return face


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preview", metavar="GIF", help="write ~15 s of every state to this GIF")
    p.add_argument("--panel", action="store_true", help="play every state on the panel")
    p.add_argument("--tune", action="store_true", help="cycle colour settings on the panel, 3 s each")
    p.add_argument("--display", help="Bluetooth address (default: the one in face_bridge.py)")
    p.add_argument("--brightness", type=int, help="panel brightness, 5-100 %%")
    args = p.parse_args()
    if args.preview:
        preview(args.preview)
    if args.panel:
        face = connect(args)
        fox = FoxLive(face.pixels).start()
        t0 = time.monotonic()
        for at, action in script(fox, t0):
            time.sleep(max(0.0, t0 + at - time.monotonic()))
            action()
        fox.stop()
    if args.tune:
        face = connect(args)
        fox = FoxLive(face.pixels).start()
        presets = [(1.0, 1.0), (1.1, 1.2), (1.2, 1.2), (1.2, 1.4), (1.3, 1.4), (1.2, 1.6), (1.3, 1.6), (1.4, 2.2)]
        print("Watch the panel; note the number that looks most like the screen.")
        for n, (sat, gam) in enumerate(presets, 1):
            face.saturation, face.gamma, face._shown = sat, gam, None
            print(f"  {n}: saturation {sat}, gamma {gam}" + ("   (as sent before: no correction)" if n == 1 else ""))
            time.sleep(3)
        fox.stop()
        print("Use it with: talk.py --saturation S --gamma G   (or tell Claude the number)")


if __name__ == "__main__":
    main()
