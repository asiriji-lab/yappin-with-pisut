"""The chat page's talking face, on the iDotMatrix pixel display.

The Athena page (http://localhost:3040) lip-syncs its face sprite to the voice; when this bridge
is running it also sends each sentence's mouth timing here, and the bridge shows the same frames
on the display over Bluetooth, on the same schedule.

    D:\\athena-face-venv\\Scripts\\python.exe face_bridge.py              # display at DISPLAY_ADDRESS
    D:\\athena-face-venv\\Scripts\\python.exe face_bridge.py --display search
    D:\\athena-face-venv\\Scripts\\python.exe face_bridge.py --test     # each mouth for 0.5 s, then quit

The page talks to http://127.0.0.1:3050:
  GET  /health                       {"display": true|false}
  POST /mouth {"cues": [[s, f], ...]} show frame f (0-6) s seconds from now; replaces what's queued
  POST /mouth {"flap": true|false}   the browser's voice gives no timing: flap until false
  POST /mouth {"stop": true}         mouth shut now
  POST /frame <3072 bytes>           show this 32x32 RGB frame now (the fox avatar page, avatar/,
                                     mirrors its whole canvas this way: mouth, face, blinks, nods)

A still frame takes ~20 ms over Bluetooth (DIY mode on), so only the newest frame is ever sent:
a frame due while another is still on its way replaces the waiting one, and nothing backs up.
"""
import argparse
import asyncio
import json
import logging
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image as PILImage
from PIL import ImageEnhance
from idotmatrix import Common, ConnectionManager, Image

HERE = os.path.dirname(os.path.abspath(__file__))
DISPLAY_ADDRESS = "7C:C5:ED:E9:D9:30"     # IDM-E9D930
PORT = 3050
FLAP = (1, 4, 3, 1, 2, 5, 1, 4)           # mouth frames for the browser's voice, 120 ms each
log = logging.getLogger("face")
# LEDs are linear, screen colours are gamma-encoded: sent as they are, the fox's oranges, cream and
# greys come out far too bright on the panel, so everything looks pale and washed out (16 Nov).
SATURATION = 1.2                           # more colour first (1.4 + gamma 2.2 looked too red, 16 Nov)...
GAMMA = 1.4                                # ...then darken the mid tones the way a screen does
FLOOR = 12                                 # a lit pixel never drops below this (dark outlines stay on)


def panel_colours(img, saturation=SATURATION, gamma=GAMMA, floor=FLOOR):
    """A 32x32 RGB frame as it should be sent to the LED panel to look like it does on a screen."""
    if saturation != 1:
        img = ImageEnhance.Color(img).enhance(saturation)
    a = np.asarray(img, dtype=np.float32)
    lit = a.max(axis=2) > 0
    out = 255 * (a / 255) ** gamma
    peak = out.max(axis=2)
    low = lit & (peak < floor)
    out[low] *= (floor / np.maximum(peak[low], 1e-3))[:, None]
    return PILImage.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


def frames(sprite):
    """The sprite strip (7 frames of 32x32, transparent background) -> 7 PNG files on black."""
    strip = PILImage.open(sprite).convert("RGBA")
    folder = tempfile.mkdtemp(prefix="athena-mouth-")
    paths = []
    for i in range(strip.width // 32):
        cell = strip.crop((i * 32, 0, i * 32 + 32, 32))
        img = PILImage.new("RGB", (32, 32), (0, 0, 0))
        img.paste(cell, (0, 0), cell)
        paths.append(os.path.join(folder, f"{i}.png"))
        img.save(paths[-1])
    return paths


class Face:
    """The display on its own asyncio thread; show() / play() / flap() are safe from any thread."""

    def __init__(self, address, sprite, lead, saturation=SATURATION, gamma=GAMMA, brightness=None):
        self.address, self.paths, self.lead = address, frames(sprite) if sprite else [], lead
        self.saturation, self.gamma, self.brightness = saturation, gamma, brightness
        self.live_dir = tempfile.mkdtemp(prefix="athena-live-")
        self.ok = False
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="ble").start()
        self._want = self._shown = None
        self._wake = self._timers = self._flapper = None

    def call(self, fn, *args):
        self.loop.call_soon_threadsafe(fn, *args)

    def connect(self):
        try:
            self.ok = asyncio.run_coroutine_threadsafe(self._connect(), self.loop).result(40)
        except Exception as e:                     # noqa: BLE001 - carry on without it
            log.warning("display: %s", e)
        return self.ok

    async def _connect(self):
        conn = ConnectionManager()
        if self.address:
            await conn.connectByAddress(self.address)
        else:
            await conn.connectBySearch()
        if not (conn.client and conn.client.is_connected):
            return False
        await Image().setMode(1)                   # DIY mode: still frames show at once
        if self.brightness:
            await Common().setBrightness(max(5, min(100, int(self.brightness))))
        self._wake = asyncio.Event()
        self._timers = []
        asyncio.get_running_loop().create_task(self._sender())
        self._want = 0 if self.paths else None
        self._wake.set()
        return True

    async def _sender(self):
        """Send the newest wanted frame; frames wanted meanwhile just replace it."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            want = self._want
            if want is None or want == self._shown:
                continue
            if isinstance(want, bytes):            # a live frame: 32x32 RGB (fox_live.py, the fox page)
                img = PILImage.frombytes("RGB", (32, 32), want)
            else:
                img = PILImage.open(self.paths[want]).convert("RGB")
            path = os.path.join(self.live_dir, "live.png")
            panel_colours(img, self.saturation, self.gamma).save(path)
            try:
                if await Image().uploadUnprocessed(path):
                    self._shown = want
            except Exception as e:                 # noqa: BLE001 - the library reconnects on the next send
                log.warning("display didn't take frame %s: %s", want, e)
                await asyncio.sleep(0.3)

    # ---------- on the BLE loop ----------

    def _set(self, frame):
        self._want = frame
        self._wake.set()

    def _cancel(self):
        for h in self._timers:
            h.cancel()
        self._timers = []
        if self._flapper:
            self._flapper.cancel()
            self._flapper = None

    def _play(self, cues, append):
        if not append:
            self._cancel()
        now = self.loop.time()
        for delay, frame in cues:
            self._timers.append(self.loop.call_at(now + max(0.0, delay - self.lead), self._set, frame))

    def _flap(self, on):
        self._cancel()
        if not on:
            self._set(0)
            return

        async def run():
            k = 0
            while True:
                self._set(FLAP[k % len(FLAP)])
                k += 1
                await asyncio.sleep(0.12)
        self._flapper = self.loop.create_task(run())

    # ---------- from the web thread ----------

    def play(self, cues, append=True):
        self.call(self._play, [(float(s), int(f)) for s, f in cues if 0 <= int(f) < len(self.paths)], append)

    def flap(self, on):
        self.call(self._flap, bool(on))

    def stop(self):
        self.call(self._flap, False)

    def _pixels(self, rgb):
        self._cancel()                             # the page drives the panel itself now
        self._set(rgb)

    def pixels(self, rgb):
        """Show one 32x32 RGB frame (3072 bytes) now; only the newest waiting one is sent."""
        self.call(self._pixels, rgb)


def handler(face):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, body=b"{}"):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self._reply(204, b"")

        def do_GET(self):
            if self.path != "/health":
                return self._reply(404)
            self._reply(200, json.dumps({"display": face.ok}).encode())

        def do_POST(self):
            if self.path == "/frame":                # the fox page mirrors its 32x32 canvas here
                rgb = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if len(rgb) != 32 * 32 * 3:
                    return self._reply(400)
                if not face.ok:
                    return self._reply(503, b'{"display": false}')
                face.pixels(rgb)
                return self._reply(200)
            if self.path != "/mouth":
                return self._reply(404)
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self._reply(400)
            if not face.ok:
                return self._reply(503, b'{"display": false}')
            if data.get("stop"):
                face.stop()
            elif "flap" in data:
                face.flap(data["flap"])
            elif isinstance(data.get("cues"), list):
                face.play(data["cues"], append=data.get("append", True))
            self._reply(200)

        def log_message(self, *args):          # the page posts often; keep the console quiet
            pass
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--display", default=DISPLAY_ADDRESS, help="Bluetooth address, or 'search'")
    p.add_argument("--sprite", default=os.path.join(HERE, "face-sprite.png"), help="7 frames of 32x32, side by side")
    p.add_argument("--lead", type=float, default=0.03, help="send each frame this many seconds early (Bluetooth delay)")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--test", action="store_true", help="show each mouth for 0.5 s, then quit")
    p.add_argument("--saturation", type=float, default=SATURATION, help="colour boost for the LEDs (1 = as on screen)")
    p.add_argument("--gamma", type=float, default=GAMMA, help="mid-tone darkening for the LEDs (1 = none)")
    p.add_argument("--brightness", type=int, help="panel brightness, 5-100 %%")
    args = p.parse_args()
    # idotmatrix turns on DEBUG logging for everything when it's imported; back to warnings only
    logging.basicConfig(level=logging.WARNING, format="%(message)s", force=True)

    face = Face(None if args.display == "search" else args.display, args.sprite, args.lead,
                args.saturation, args.gamma, args.brightness)
    print("Connecting to the pixel display...")
    if not face.connect():
        print("  Display not found (is it on, and not connected to the phone app?)")
        return
    print("  connected")
    if args.test:
        face.play([(i * 0.5, f) for i, f in enumerate([0, 1, 2, 3, 4, 5, 6, 0])])
        time.sleep(4.5)
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(face))
    print(f"Face bridge on http://127.0.0.1:{args.port}. Open the Athena page and talk; Ctrl+C stops.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        face.stop()
        time.sleep(0.3)


if __name__ == "__main__":
    main()
