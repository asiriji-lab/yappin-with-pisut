# Fox conversation face (32×32 pixel art)

Every face is exactly 32×32 pixels (1 art pixel = 1 image pixel) with a transparent background.

| Folder | What |
|---|---|
| `png/<emotion>/` | every face as PNG: `fox_<emotion>_<mouth>.png`, `fox_<emotion>_idle.png`, `fox_<emotion>_blink_half.png`, `fox_<emotion>_blink_closed.png` |
| `piskel/<emotion>/` | the same faces as Piskel files (open at piskelapp.com → Open) |
| `piskel/fox_<emotion>_all.piskel` | all of one emotion's faces as frames in one Piskel file |
| `sheets/` | sprite sheet per emotion, 32×32 cells, 6 per row (positions in `fox_face_map.json`) |
| `previews/` | enlarged, labelled views for looking at, not for use as sprites |
| `demo/` | the fox saying a sample line (`fox_demo.gif` real size, `fox_demo_x8.gif` enlarged) |
| `fox_face_map.json` | every file, plus phoneme → mouth tables (CMU/ARPAbet, 15-viseme lip-sync set, classic animation chart) |
| `fox_palette.gpl` | the colours, loadable in Piskel, Aseprite or GIMP |

**Mouths (15):** A, O, E, W/R, T/S, L/N, U/Q, M/B/P, F/V (the original 9), plus rest, EE/I, OO, TH, CH/SH/J, K/G.

**Emotions (6):** neutral, happy, sad, angry, surprised, thinking. The eyes carry the emotion and the mouth carries the speech, so any mouth works with any emotion. Each emotion also has its own idle mouth (rest, smile, frown, gritted, O, hmm).

**Lip-sync rules used:** 12 drawings a second; vowels held 2–3 frames, consonants 1; M/B/P, F/V, W, OO, TH and CH are always shown; quick tongue sounds between vowels are skipped; diphthongs get two shapes ("my" = A → EE); back to idle at commas and full stops; blink at pauses and when the emotion changes.
