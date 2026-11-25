# Run Athena with the fox on the LED panel

Athena answers by voice and the live pixel fox lip-syncs on the iDotMatrix 32x32 panel.

## Before you start

- Bluetooth is on.
- The panel is on.
- The iDotMatrix phone app is closed (the panel takes one connection at a time).

## Terminal 1: Athena

Search, Orion (Qwen 3.8-27B), Whisper speech-to-text and the Kokoro voice. Wait until it prints `Ready` (about a minute).

```powershell
cd D:\athena-autotune\CMKL-Athena\onyx\web
powershell -ExecutionPolicy Bypass -File run-summit.ps1 -Python D:\OneDrive\Documents\New_Life\Athena\CMKL-Athena\.venv\Scripts\python.exe
```

## Terminal 2: the panel and push-to-talk

```powershell
cd D:\OneDrive\Documents\New_Life\Athena\beam_local\athena-face
D:\athena-face-venv\Scripts\python.exe talk.py
```

Hold **Right Ctrl**, speak, and let go. Athena answers through the speakers while the fox lip-syncs on the panel. Press Right Ctrl while she talks to cut her off. Ctrl+C quits.

Athena remembers the last 3 questions and answers, so "What about ECE?" follows on and she doesn't greet you again. "Can you say that again?" repeats her last answer. She forgets when talk.py stops, or after 3 minutes with no question (the next visitor starts fresh). Change these with `$env:HISTORY_TURNS` and `$env:MEMORY_IDLE_S` before starting.

## Options for talk.py

| Option | What it does |
|---|---|
| `--brightness 60` | Panel brightness, 5-100 |
| `--type` | Type questions instead of speaking |
| `--saturation 1.2 --gamma 1.4` | LED colour (these are the defaults) |
| `--sprite snoopy-sprite.png` | Snoopy's mouth frames instead of the live fox |
| `--display off` | Sound only, no panel |

## Panel checks without Athena

```powershell
D:\athena-face-venv\Scripts\python.exe fox_live.py --panel   # every fox state on the panel, ~15 s
D:\athena-face-venv\Scripts\python.exe fox_live.py --tune    # compare 8 colour settings, 3 s each
```
