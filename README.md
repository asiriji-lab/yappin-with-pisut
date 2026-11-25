# yappin-with-pisut

Athena's talking face. You hold a key and ask Athena (CMKL University's handbook assistant) a question
out loud. She answers through the speakers, and a 32x32 iDotMatrix LED display lip-syncs to her voice.

```
your voice -> /api/stt (Whisper) -> /api/ask (search + qwen, short spoken answer)
           -> /api/tts (Kokoro: audio + X-Mouth = which mouth frame, when)
           -> talk.py plays the audio and sends the mouth frames to the display over Bluetooth
```

The chat server (STT, RAG, TTS) is **not** in this repo. It lives in the CMKL-Athena repo (`onyx/web`,
voice branch). This repo is everything on the face side: the client, the display driver and the
mouth sprites.

## Setup (Windows)

```powershell
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

You need a mic, speakers, Bluetooth, and the iDotMatrix display switched on. The display's address is
hard-coded as `7C:C5:ED:E9:D9:30` (IDM-E9D930). Pass `--display search` to find any iDotMatrix nearby,
or `--display off` to run without one.

## Run it

**Check the display only** (shows each mouth for 0.5 s, then quits):

```powershell
venv\Scripts\python face_bridge.py --sprite snoopy-sprite.png --test
```

**Talk to Athena.** First you need a chat server:

- **GPU server** (the lab 4070 Ti, needs the VPN): `talk.py` uses `http://127.0.0.1:3040` if it
  answers. If not, it opens its own SSH tunnel to the GPU box, which needs the `athena_gpu_ed25519` key.
- **This laptop**: `run-voice-local.ps1` starts the server locally (Ollama + qwen3:4b). It expects
  Beam's folder layout (`D:\athena-autotune`, the CMKL-Athena venv), so change the paths at the top.

Then:

```powershell
venv\Scripts\python talk.py                              # the live pixel fox (breathes, blinks, listens, thinks)
venv\Scripts\python talk.py --sprite snoopy-sprite.png   # Snoopy's mouth frames instead
venv\Scripts\python talk.py --saturation 1.2 --gamma 1.4 --brightness 60   # LED colour (fox_live.py --tune to pick)
venv\Scripts\python talk.py --type              # type questions instead of speaking
venv\Scripts\python talk.py --display off       # sound only
```

Hold **Right Ctrl**, speak, let go. Press it again while Athena is talking to cut her off.

## Files

| File | What it does |
|---|---|
| `talk.py` | The main client: push-to-talk, plays Athena's voice, drives the mouth frames on time |
| `face_bridge.py` | Shows sprite frames on the display over Bluetooth. Also a small HTTP server on :3050 so the web chat page can drive the display |
| `fox_live.py` | The live fox on the panel: a port of the web fox (`fox/web/atlas.*`, KP's `fox-avatar.js`). `--preview x.gif`, `--panel`, `--tune` (pick the LED colour settings) |
| `fox_sprite.py` | The pixel fox (`fox/`, drawn at 32x32) -> `fox-sprite.png` in frame order, no resizing: `python fox_sprite.py [emotion]` or `--all` |
| `fox/` | The pixel fox pack: 15 mouths x 6 emotions + blinks as 32x32 PNGs, Piskel files, sheets, palette, phoneme -> mouth tables (`fox_face_map.json`) |
| `fox-sprite.png`, `fox-<emotion>-sprite.png` | The built fox strips (10 frames), plus `@8x` and talking GIFs to look at |
| `viseme_sprite.py` | Turns a character's 9 viseme pictures into a 32x32 sprite strip: `python viseme_sprite.py snoopy` or `hearty` |
| `snoopy_sprite.py` | The older Snoopy-only version of `viseme_sprite.py` |
| `snoopy_visemes/`, `hearty_visemes/` | The source pictures, one per mouth shape (256x256 on white) |
| `snoopy-sprite.png` | The built strip (10 frames of 32x32), plus `@8x`, preview and talking GIFs to look at |
| `pixel-art/snoopy-mouths/` | A hand-drawn Snoopy, kept as a fallback (`build.py` needs Beam's pixel-art-studio skill) |
| `face-sprite.png` | The default 7-frame strip if you don't pass `--sprite` |
| `athena_face.py`, `display.py`, `face.py` | First version: local Whisper, Windows voice, a simple open/closed cartoon face |

## Sprite frame order

A sprite strip is 32x32 frames placed side by side. The server's `X-Mouth` header sends frame numbers
0-6, so the first 7 frames have to be in this order:

```
0 rest   1 A (ah)   2 E (ee)   3 O (oh)   4 M_B_P   5 F_V   6 L_N   |   7 T_S   8 U_Q   9 W_R
```

Frames 7-9 exist but the server doesn't send them yet.

**Adding a new character:** draw 9 pictures named like the ones in `snoopy_visemes/` (same head
position in each, white background), put them in `<name>_visemes/`, add an entry to `CHARACTERS` in
`viseme_sprite.py`, then run it.

## Known issues

- At 32x32, O, U_Q and W_R barely read as mouths (they look like a bigger nose).
- On the LED panel black means "off", so dark parts like Snoopy's ear are drawn dim grey instead.
- One still frame takes ~20 ms over Bluetooth. `--lead` (default 0.03 s) sends each frame early
  to make up for it.
