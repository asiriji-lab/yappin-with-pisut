"""Talk to Athena; the pixel display shows a mouth that moves while Athena answers out loud.

Hold Right Ctrl, speak, let go. Whisper (CPU) turns the speech into text, the local Athena chat
server (http://127.0.0.1:3040, started by CMKL-Athena/onyx/web/run-local-qwen.ps1) answers,
the Windows voice reads the answer, and the display switches between a closed and a talking mouth.

    D:\\athena-face-venv\\Scripts\\python.exe athena_face.py               # talk
    D:\\athena-face-venv\\Scripts\\python.exe athena_face.py --type        # type questions instead
    D:\\athena-face-venv\\Scripts\\python.exe athena_face.py --test-face   # just flip the mouth 3 times

Whisper runs on the CPU on purpose: the 6 GB GPU is full with qwen and the reranker, and anything
more pushes qwen into normal RAM (answers drop to ~3 words per second).
"""
import argparse
import json
import logging
import queue
import re
import threading
import time

import httpx

from display import Display

SERVER = "http://127.0.0.1:3040"
DISPLAY_ADDRESS = "7C:C5:ED:E9:D9:30"     # IDM-E9D930; --display search finds any iDotMatrix
WHISPER_DIR = r"D:\hf-cache\whisper"      # C: is nearly full
RATE = 16000
SPOKEN_SENTENCES = 5                      # answers can be long; the rest is printed, not read


# ---------- speech to text ----------

class Ears:
    def __init__(self, model):
        from faster_whisper import WhisperModel
        t = time.perf_counter()
        self.model = WhisperModel(model, device="cpu", compute_type="int8", download_root=WHISPER_DIR)
        print(f"Whisper {model} loaded in {time.perf_counter() - t:.1f} s")

    def record(self, key):
        """Wait for the key, record while it's held, return the audio (float32, 16 kHz)."""
        import keyboard
        import numpy as np
        import sounddevice as sd
        keyboard.wait(key)
        chunks = []
        with sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                            callback=lambda data, *_: chunks.append(data.copy())):
            print("  listening...", end="", flush=True)
            while keyboard.is_pressed(key):
                time.sleep(0.02)
        print("\r" + " " * 20 + "\r", end="")
        return np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, "float32")

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=True,
            initial_prompt="A student asks Athena, CMKL University's assistant, about the handbook.")
        return " ".join(s.text.strip() for s in segments).strip()


# ---------- text to speech ----------

class Voice:
    """Windows SAPI voice in its own thread (COM stays out of the Bluetooth thread)."""

    def __init__(self, display, voice="Zira", rate=1):
        self.display = display
        self.q = queue.Queue()
        self.idle = threading.Event()
        self.idle.set()
        threading.Thread(target=self._run, args=(voice, rate), daemon=True, name="voice").start()

    def say(self, sentence):
        self.idle.clear()
        self.q.put(sentence)

    def end(self):
        """No more sentences for this answer: close the mouth once everything is spoken."""
        self.q.put(None)

    def _run(self, voice_name, rate):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        sapi = comtypes.client.CreateObject("SAPI.SpVoice")
        voices = sapi.GetVoices()
        for i in range(voices.Count):
            if voice_name.lower() in voices.Item(i).GetDescription().lower():
                sapi.Voice = voices.Item(i)
        sapi.Rate = rate
        while True:
            item = self.q.get()
            if item is None:
                if self.q.empty():
                    self.display.talking(False)
                    self.idle.set()
                continue
            self.display.talking(True)
            sapi.Speak(item)


def speakable(text):
    """Drop what sounds wrong read aloud: [1] citations, markdown, links."""
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "the link on screen", text)
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"^\s*(?:[-•]|\d+\.)\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def sentences(buffer):
    """Split finished sentences off the front of the streamed text; returns (done, rest)."""
    parts = re.split(r"(?<=[.!?:])\s+|\n+", buffer)
    return parts[:-1], parts[-1]


# ---------- Athena ----------

def ask(question, history, voice, display, max_spoken):
    """Stream Athena's answer; speak it sentence by sentence as it arrives."""
    t0 = time.perf_counter()
    first_text = None
    answer, pending, spoken, skipped = "", "", 0, False

    def speak(s):
        nonlocal spoken, skipped
        s = speakable(s)
        if not s:
            return
        if spoken < max_spoken:
            voice.say(s)
            spoken += 1
        else:
            skipped = True

    print("Athena: ", end="", flush=True)
    try:
        with httpx.stream("POST", f"{SERVER}/api/ask", timeout=120,
                          json={"question": question, "program": "all", "history": history[-1:]}) as r:
            if r.status_code != 200:
                msg = r.read().decode(errors="replace")
                try:
                    msg = json.loads(msg).get("detail", msg)
                except ValueError:
                    pass
                raise RuntimeError(msg)
            for line in r.iter_lines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("t") == "delta":
                    if first_text is None:
                        first_text = time.perf_counter() - t0
                        display.talking(True)    # the GIF takes ~0.6 s; start it before the voice
                    answer += ev["text"]
                    pending += ev["text"]
                    print(ev["text"], end="", flush=True)
                    done, pending = sentences(pending)
                    for s in done:
                        speak(s)
                elif ev.get("t") == "error":
                    answer = pending = ""
                    voice.say(ev.get("text", "Something went wrong."))
                    print(ev.get("text", ""), end="")
    except (httpx.HTTPError, RuntimeError) as e:
        answer = pending = ""
        voice.say("I can't reach the Athena chat server right now.")
        print(f"I can't reach the Athena chat server right now. ({e})", end="")
    speak(pending)
    if skipped:
        voice.say("The rest is on the screen.")
    voice.end()
    print()
    return answer, first_text, time.perf_counter() - t0


# ---------- main ----------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--type", action="store_true", help="type questions instead of speaking")
    p.add_argument("--key", default="right ctrl", help="push-to-talk key (default: right ctrl)")
    p.add_argument("--whisper", default="base.en", help="Whisper model: tiny.en, base.en, small.en")
    p.add_argument("--display", default=DISPLAY_ADDRESS, help="Bluetooth address, 'search', or 'off'")
    p.add_argument("--voice", default="Zira", help="Windows voice name (Zira or David)")
    p.add_argument("--max-sentences", type=int, default=SPOKEN_SENTENCES)
    p.add_argument("--test-face", action="store_true", help="flip the mouth 3 times and quit")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    display = Display(None if args.display == "search" else args.display)
    if args.display != "off":
        print("Connecting to the pixel display...")
        if not display.connect():
            print("  Display not found (is the phone app connected to it?). Carrying on without it.")
    if args.test_face:
        for i in range(3):
            print(f"{i + 1}: talking"); display.talking(True); time.sleep(4)
            print(f"{i + 1}: closed"); display.talking(False); time.sleep(2)
        display.close()
        return

    voice = Voice(display, args.voice)
    ears = None if args.type else Ears(args.whisper)
    history = []
    prompt = "Type a question (empty line quits)" if args.type else f"Hold {args.key.title()} and talk (Ctrl+C quits)"
    print(prompt)
    try:
        while True:
            if args.type:
                question = input("\nYou: ").strip()
                if not question:
                    break
                stt = 0.0
            else:
                audio = ears.record(args.key)
                if len(audio) < RATE * 0.3:
                    continue
                t = time.perf_counter()
                question = ears.transcribe(audio)
                stt = time.perf_counter() - t
                if not question:
                    print("  (didn't catch that)")
                    continue
                print(f"\nYou: {question}")
            voice.idle.wait()
            answer, first, total = ask(question, history, voice, display, args.max_sentences)
            history = [{"q": question, "a": answer}]
            first_s = f"{first:.1f}" if first is not None else "-"
            print(f"  [speech->text {stt:.1f} s | first words {first_s} s | full answer {total:.1f} s]")
    except KeyboardInterrupt:
        pass
    finally:
        voice.idle.wait(timeout=60)
        display.close()


if __name__ == "__main__":
    main()
