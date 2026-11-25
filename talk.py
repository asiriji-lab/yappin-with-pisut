"""Talk to Athena with a key, no browser: hold Right Ctrl, speak, let go. Athena answers out loud
on this computer, and the iDotMatrix display shows the live pixel fox (fox_live.py: the web page's
fox, breathing, blinking, listening, searching, thinking) lip-syncing to her voice.

The work happens on the GPU server (the voice-mode chat server, onyx/web/run-local-qwen.sh):
  your recording -> /api/stt (Whisper) -> /api/ask voice mode (search + qwen, short spoken answer)
  -> each sentence -> /api/tts (Kokoro: the audio, plus X-Mouth: which mouth frame when)
This program records, plays the audio, and shows the mouth frames on the display at the same times.

    D:\\athena-face-venv\\Scripts\\python.exe talk.py
    D:\\athena-face-venv\\Scripts\\python.exe talk.py --display off      # sound only
    D:\\athena-face-venv\\Scripts\\python.exe talk.py --type             # type questions instead

It uses the server on this computer, http://127.0.0.1:3040 (run-voice-local.ps1, or VS Code's port
forward). With --vm, if that doesn't answer, it opens its own SSH tunnel to the GPU box on port 3041.
Press the key while Athena talks to cut her off and ask something else.
"""
import argparse
import concurrent.futures
import io
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import wave

import httpx

from face_bridge import DISPLAY_ADDRESS, GAMMA, SATURATION, Face
from fox_live import FoxLive, cues_from_xmouth

HERE = os.path.dirname(os.path.abspath(__file__))
GPU = "student1@172.19.36.25"
KEY = os.path.join(os.path.expanduser("~"), ".ssh", "athena_gpu_ed25519")
RATE = 16000
FILLER = "Let me check."
# Memory (25 Nov): Athena gets the last MEMORY_TURNS questions and answers, so "what about ECE?" and
# "hello again" follow on from the conversation. Kept only while this program runs, and dropped after
# MEMORY_IDLE_S seconds with no question (the next visitor at the booth starts fresh).
MEMORY_TURNS = int(os.environ.get("HISTORY_TURNS") or 3)
MEMORY_IDLE_S = float(os.environ.get("MEMORY_IDLE_S") or 180)
# "Can you say that again?" on its own: say the last answer again, word for word, with no search
# (a search for those words finds nothing, so Athena would say she couldn't find it). The same rule
# as the fox kiosk (CMKL-Athena avatar/server/answer.py).
REPEAT = re.compile(
    r"^\s*(((can|could|would) you\s+)?(please\s+)?(say|repeat)\s+(that|it|this)(\s+(again|one more time))?"
    r"|(please\s+)?repeat( that| it)?|say (that|it) again|again|one more time|pardon( me)?|come again"
    r"|what did you (just )?say|i didn'?t (hear|catch) (that|you|it)|ขอ(ฟัง)?อีกที\S*|พูดอีกที\S*)"
    r"(\s*,?\s*please)?[\s?.!,]*$", re.I)


# ---------- the server ----------

def server_url(tunnel_port=3041, vm=False):
    """The chat server's address: this computer's (or a VS Code forward); with --vm, a tunnel of our own."""
    for url in ("http://127.0.0.1:3040", f"http://127.0.0.1:{tunnel_port}"):
        try:
            if httpx.get(url + "/api/health", timeout=2).status_code == 200:
                return url, None
        except httpx.HTTPError:
            pass
    if not vm:
        sys.exit("No Athena server on this computer yet (port 3040). Start it in another window and wait for 'Ready': "
                 "powershell -ExecutionPolicy Bypass -File run-voice-local.ps1")
    print("Opening an SSH tunnel to the GPU server...")
    proc = subprocess.Popen(["ssh", "-N", "-i", KEY, "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                             "-L", f"{tunnel_port}:127.0.0.1:3040", GPU],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{tunnel_port}"
    for _ in range(40):
        time.sleep(0.5)
        if proc.poll() is not None:
            sys.exit("SSH tunnel failed (VPN on?): " + proc.stderr.read().decode(errors="replace").strip())
        try:
            if httpx.get(url + "/api/health", timeout=2).status_code == 200:
                return url, proc
        except httpx.HTTPError:
            pass
    proc.terminate()
    sys.exit("The chat server on the GPU box didn't answer. Is run-local-qwen.sh running there?")


def wav_bytes(pcm, rate):
    import numpy as np
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def read_wav(data):
    import numpy as np
    with wave.open(io.BytesIO(data)) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float32") / 32768
    return pcm, rate


def parse_mouth(header):
    cues = []
    for part in (header or "").split(","):
        try:
            t, f = part.split(":")
            cues.append((float(t), int(f)))
        except ValueError:
            pass
    return cues


# ---------- the voice: plays sentences in order, the display's mouth in step ----------

class Mouth:
    def __init__(self, client, url, face, fox=None):
        self.client, self.url, self.face, self.fox = client, url, face, fox
        self.after = "idle"                                        # the fox's state once the answer is said
        self.pool = concurrent.futures.ThreadPoolExecutor(4)      # sentences are made while others play
        self.q = queue.Queue()
        self.gen = 0
        self.idle = threading.Event()
        self.idle.set()
        threading.Thread(target=self._run, daemon=True, name="voice").start()

    def _tts(self, text):
        if text == FILLER and getattr(self, "_filler", None):
            return self._filler
        r = self.client.post(self.url + "/api/tts", json={"text": text}, timeout=60)
        r.raise_for_status()
        pcm, rate = read_wav(r.content)
        out = pcm, rate, parse_mouth(r.headers.get("X-Mouth"))
        if text == FILLER:
            self._filler = out
        return out

    def say(self, text):
        self.idle.clear()
        self.q.put((self.gen, self.pool.submit(self._tts, text)))

    def end(self, after="idle"):
        self.after = after
        self.q.put((self.gen, None))

    def stop(self):
        """Cut off: what's playing stops, what's queued is dropped."""
        import sounddevice as sd
        self.gen += 1
        sd.stop()
        if self.face and not self.fox:                             # the live fox handles its own face
            self.face.stop()
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.idle.set()

    def _run(self):
        import sounddevice as sd
        while True:
            gen, job = self.q.get()
            if gen != self.gen:
                continue
            if job is None:
                if self.q.empty():
                    self.idle.set()
                    if self.fox:
                        self.fox.end_speech(self.after)
                continue
            try:
                pcm, rate, cues = job.result()
            except Exception as e:                     # noqa: BLE001 - one sentence lost, not the answer
                print(f"  (couldn't say a sentence: {e})")
                continue
            if gen != self.gen:
                continue
            if self.fox:
                self.fox.speak(cues_from_xmouth(cues, len(pcm) / rate), start=time.monotonic())
            elif self.face:
                self.face.play(cues + [(len(pcm) / rate, 0)], append=False)
            sd.play(pcm, rate)
            sd.wait()
            if self.fox and self.q.empty() and gen == self.gen:
                self.fox.set_state("thinking")         # the next sentence isn't ready yet: "..."
            time.sleep(0.15)                           # a breath between sentences


# ---------- asking ----------

def ask(client, url, question, history, mouth):
    """Stream Athena's spoken answer; each sentence goes to the voice as soon as it's ready.
    -> (the written answer, seconds to the first sentence, the sentences said)"""
    t0 = time.perf_counter()
    first, answer, failed, said = None, "", False, []
    fox = mouth.fox
    mouth.say(FILLER)
    print("Athena: ", end="", flush=True)
    try:
        with client.stream("POST", url + "/api/ask", timeout=120,
                           json={"question": question, "program": "all", "history": history[-MEMORY_TURNS:],
                                 "voice": True}) as r:
            if r.status_code != 200:
                r.read()
                try:
                    msg = r.json().get("detail")
                except ValueError:
                    msg = None
                raise RuntimeError(msg or f"HTTP {r.status_code}")
            for line in r.iter_lines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev["t"] == "say":
                    if first is None:
                        first = time.perf_counter() - t0
                        if fox:                            # the face is picked from the first sentence
                            fox.set_emotion(fox.pick_emotion(ev["text"]))
                            if fox.state in ("searching", "thinking"):
                                fox.found("thinking", 500)
                    mouth.say(ev["text"])
                    said.append(ev["text"])
                elif ev["t"] == "delta":
                    answer += ev["text"]
                    print(ev["text"], end="", flush=True)
                elif ev["t"] == "error":
                    mouth.say(ev["text"])
                    print(ev["text"], end="")
    except (httpx.HTTPError, RuntimeError) as e:
        mouth.say("I can't reach the Athena server right now.")
        print(f"(can't reach the server: {e})", end="")
        failed = True
    mouth.end("error" if failed else "idle")
    print()
    return answer, first, ([] if failed else said)


def repeat(said, mouth):
    """Say the last answer's sentences again (no search, no LLM)."""
    fox = mouth.fox
    if fox and fox.state in ("searching", "thinking"):
        fox.found("thinking", 300)
    print("Athena (again): " + " ".join(said))
    for s in said:
        mouth.say(s)
    mouth.end("idle")


def record(key, on_press):
    """Wait for the key, record while it's held; float32 mono at 16 kHz."""
    import keyboard
    import numpy as np
    import sounddevice as sd
    keyboard.wait(key)
    on_press()
    chunks = []
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                        callback=lambda data, *_: chunks.append(data.copy())):
        print("  listening...", end="", flush=True)
        while keyboard.is_pressed(key):
            time.sleep(0.02)
    print("\r" + " " * 20 + "\r", end="")
    return np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, "float32")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--key", default="right ctrl", help="push-to-talk key (default: right ctrl)")
    p.add_argument("--display", default=DISPLAY_ADDRESS, help="Bluetooth address, 'search', or 'off'")
    p.add_argument("--lead", type=float, default=0.03, help="show each mouth frame this many seconds early")
    p.add_argument("--sprite", help="instead of the live fox: mouth frames, 32x32 each side by side "
                                     "(snoopy-sprite.png: the Snoopy pictures; fox-sprite.png: the old still fox)")
    p.add_argument("--saturation", type=float, default=SATURATION, help="colour boost for the LEDs (1 = as on screen)")
    p.add_argument("--gamma", type=float, default=GAMMA, help="mid-tone darkening for the LEDs (1 = none)")
    p.add_argument("--brightness", type=int, help="panel brightness, 5-100 %%")
    p.add_argument("--vm", action="store_true", help="use the GPU box over an SSH tunnel if this computer has no server")
    p.add_argument("--type", action="store_true", help="type questions instead of speaking")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # the Thai console code page can't print everything
    logging.basicConfig(level=logging.WARNING, format="%(message)s", force=True)

    url, tunnel = server_url(vm=args.vm)
    client = httpx.Client(timeout=60)
    face = fox = None
    if args.display != "off":
        face = Face(None if args.display == "search" else args.display, args.sprite, args.lead,
                    args.saturation, args.gamma, args.brightness)
        print("Connecting to the pixel display...")
        if face.connect():
            print("  connected")
            if not args.sprite:                    # the live fox: breathes, blinks, listens, thinks, talks
                fox = FoxLive(face.pixels, lead=0.04 + args.lead).start()
        else:
            print("  Display not found (on? phone app disconnected? face_bridge.py not running?). Sound only.")
            face = None
    mouth = Mouth(client, url, face, fox)

    def pressed():                                 # the key went down: cut Athena off, start listening
        if fox:
            if fox.state == "speaking":
                fox.interrupt()
            else:
                fox.set_state("listening", emotion="neutral")
        mouth.stop()
    # make "Let me check." now, so the first question's instant acknowledgement isn't waiting on Kokoro
    threading.Thread(target=lambda: mouth._tts(FILLER), daemon=True, name="filler-warmup").start()
    print(f"Athena at {url}.", "Type a question (empty line quits)" if args.type
          else f"Hold {args.key.title()} and talk; let go when you're done (Ctrl+C quits).")
    history, last_said, last_ask = [], [], 0.0     # this conversation, in memory only
    try:
        while True:
            if args.type:
                question = input("\nYou: ").strip()
                if not question:
                    break
                mouth.stop()
                if fox:
                    fox.set_state("searching")
                stt = 0.0
            else:
                audio = record(args.key, pressed)     # pressing the key cuts Athena off
                if len(audio) < RATE * 0.3:
                    if fox:
                        fox.set_state("idle")
                    continue
                if fox:
                    fox.set_state("searching")
                t = time.perf_counter()
                try:
                    r = client.post(url + "/api/stt", content=wav_bytes(audio, RATE),
                                    headers={"Content-Type": "audio/wav"})
                    question = r.json().get("text", "") if r.status_code == 200 else ""
                except httpx.HTTPError as e:
                    print(f"  (speech to text failed: {e})")
                    if fox:
                        fox.set_state("error")
                    continue
                stt = time.perf_counter() - t
                if not question:
                    print("  (didn't catch that)")
                    if fox:
                        fox.set_state("idle", emotion="confused")
                    continue
                print(f"\nYou: {question}")
            if time.monotonic() - last_ask > MEMORY_IDLE_S:    # quiet for a while: probably a new visitor
                history, last_said = [], []
            last_ask = time.monotonic()
            if last_said and REPEAT.match(question):
                repeat(last_said, mouth)
                continue
            answer, first, said = ask(client, url, question, history, mouth)
            if said and MEMORY_TURNS > 0:
                history = (history + [{"q": question[:300], "a": answer[:600]}])[-MEMORY_TURNS:]
                last_said = said
            first_s = f"{first:.1f}" if first is not None else "-"
            print(f"  [speech->text {stt:.1f} s | first sentence {first_s} s]")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        mouth.stop()
        if fox:
            fox.stop()
        if tunnel:
            tunnel.terminate()


if __name__ == "__main__":
    main()
