# Geely EX2 / EX5 — diseño sonoro procedural

Motor en Python que **sintetiza desde cero** (sin samples ni librerías) el diseño sonoro, foley y ambientes de un comercial de 49.75 s, en dos opciones:

- **Opción A — Hiperreal:** foley y ambientes creíbles, elegancia por contención.
- **Opción B — Cinemática / Sensorial:** sonido diseñado (sub-blooms, whooshes, brillos tonales, motivo "EV hum" de marca).

La música y la locución (mezcla final del cliente) **no se modifican**: el bed solo se suma, con un único trim estático global en la preview. Prueba de nulo incluida (`sfx.verify`).

> El material del cliente (video, mezcla) y todos los renders quedan **fuera del repo** (`media/`, `out/` en `.gitignore`).

## Estructura
| Ruta | Qué es |
|---|---|
| `docs/CONTRACT.md` | Interfaces: receta, cue sheet, buses, niveles, dueños de archivos |
| `cues/shots.yaml` | Planos (frames), cortes, huecos sin locución, tempo y tonalidad |
| `cues/recipe_catalog.yaml` | Catálogo de recetas (nombres y parámetros) |
| `cues/option_a.yaml`, `cues/option_b.yaml` | Hojas de spotting de cada opción |
| `cues/spotting_a.md`, `cues/spotting_b.md` | Las mismas hojas, legibles (timecode, plano, sonido, intención) |
| `sfx/dsp.py` | Primitivas DSP: ruidos, filtros variables, modales, Doppler, IRs sintéticas… |
| `sfx/recipes/*.py` | Recetas por familia: ambience, vehicle, creature, foley, designed |
| `sfx/render.py` | Cue sheet → buses (con protección de locución por cue) |
| `sfx/dynamics.py` | Protección de locución (duck + unmask M/S), duck por bombo, limitador solo-SFX |
| `sfx/mix.py` | Buses → stems → preview WAV/MP4 |
| `sfx/verify.py`, `sfx/viz.py` | Verificación automática y material de revisión visual |
| `sfx/analyze.py` | Análisis de la referencia (cortes, bombo, VAD, tonalidad) |

## Uso
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# modelo VAD (MIT): pip download silero-vad --no-deps y copiar silero_vad/data/silero_vad.onnx a tools/models/
# material: media/bed_DC_Geely.wav (mezcla final 48 kHz) y media/picture.mov
python -m sfx.analyze          # una vez
python -m sfx.render A && python -m sfx.mix A && python -m sfx.verify A && python -m sfx.viz A
python -m sfx.render B && python -m sfx.mix B && python -m sfx.verify B && python -m sfx.viz B
```
Salidas: `out/preview/<A|B>/Geely_SD_Opcion<A|B>_preview.mp4` y `.wav`, stems en `out/stems/<A|B>/`.

## Mezcla
- Preview = (mezcla original + SFX) × −1.5 dB. El limitador actúa **solo sobre los SFX**, para que la suma no pase de −1 dBTP. La mezcla original ya llega a +0.2 dBTP por sí sola.
- Stems 48 kHz / 24-bit, desde 00:00:00:00, nivelados para ir a 0 dB junto a la mezcla original a 0 dB.
