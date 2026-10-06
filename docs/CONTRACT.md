# Contrato del motor de diseño sonoro (Geely EX2/EX5)

Este documento fija las interfaces compartidas. Cada agente/autor es dueño exclusivo de sus archivos (ver tabla al final).

## Material
- **Bed (intocable):** `media/bed_DC_Geely.wav` (música + locución). Se carga con `sfx.core.load_bed()` → float32 [2_388_000, 2]. Jamás se procesa: solo se suma, con un único trim estático global en la preview.
- **Imagen:** `media/picture.mov` (24 fps, 1194 frames).
- **Análisis:** `analysis/*.json` (cortes, grilla de bombo, regiones de locución, tonalidad, ocupación espectral cada 0.5 s) y `cues/shots.yaml` (planos + huecos sin locución).

## Línea de tiempo
48 kHz, 24 fps, 1 frame = 2000 samples, total 2_388_000 samples (49.75 s). Posiciones en cues: segundos, `"f:182"`, `"s:12.5"`, `"cut[7]"`, `"cut[7]+2"` (frames) o `"cut[7]-0.1s"`.

## Receta
```python
from sfx.core import recipe, Render
from sfx import dsp

@recipe("veh.passby", family="vehicle", sync="peak", kind="event")
def passby(dur, rng, *, speed_kmh=50, closest_m=4, direction=1, surface="wet", ev=0.4, height_m=0.5, **_):
    ...
    return Render(audio_stereo_float, sync_offset=sample_del_pico, meta={...})
```
- Firma: `fn(dur: float, rng: np.random.Generator, **params) -> Render`. Aceptar `**_` para tolerar parámetros extra.
- `audio` estéreo [n, 2] float. La longitud puede exceder `dur` (colas de reverb), pero debe respetar `dur` como duración "útil".
- `sync_offset` = sample dentro del audio que debe caer en el tiempo `at` del cue (según `sync` del catálogo).
- Determinista: toda aleatoriedad desde `rng`. Sin `np.random` global.
- Bordes con fade ≥ 3 ms; sin DC; sin NaN; sin clics fuera de transientes intencionales.
- **No normalizar a mano para nivel de mezcla**: el renderer normaliza `event` a pico −6 dBFS y `bed` a RMS −20 dBFS; el nivel final lo da `gain_db` del cue.
- Realismo sin samples: capas separadas (transiente + cuerpo + textura + espacio), nada estático (modulación 1/f acotada en ganancia/corte/pitch), cada evento re-sintetizado con su propio rng, espacio coherente (`dsp.reverb(x, preset, send_db)`), distancia = nivel + LPF + relación directo/reverb.
- Paso alto por defecto 120 Hz (24 dB/oct) salvo cuerpos/golpes intencionales (≥ 70 Hz) y la familia `des.sub_impact` (subs ≤ 45 Hz de fundamental, debajo del bombo 58-70 Hz).
- Elementos tonales: solo notas Bb, Db, Eb, F, Ab (y octavas).

## Cue sheet (`cues/option_a.yaml`, `cues/option_b.yaml`)
```yaml
option: A
title: "Hiperreal"
cues:
  - id: A010_underpass_room        # único, prefijo de opción + número
    recipe: amb.room_tone           # nombre del catálogo
    at: 0.0                         # tiempo de sync (ver formatos)
    dur: 1.6                        # s
    bus: AMB                        # AMB | VEH | FOL | DES | SUB
    gain_db: -16                    # sobre la normalización de la receta
    params: {space: underpass}
    pan: 0.0                        # escalar o [[t_rel_s, pan], ...] (-1..1), balance de potencia constante
    width: 1.0                      # M/S (0 mono .. 1.5 ancho)
    fade_in: 0.05                   # s
    fade_out: 0.25                  # s
    until: "cut[0]+3"               # opcional: corte duro con fade_out terminando aquí (J/L cuts)
    gain_curve: [[0, -6], [0.5, 0]] # opcional, dB relativos, t_rel_s
    send: {preset: underpass_concrete, db: -14}   # opcional, reverb extra
    vo_protect: normal              # none | normal | strong   (ducking + carving bajo la locución)
    sync: {type: cut, frame: 29}    # cut | frame | free  (validación ±1 frame)
    notes_es: "Room tone de hormigón bajo el paso elevado"
```
Colocación: el sample `sync_offset` de la receta cae exactamente en `at`.

### Niveles de referencia
Bed ≈ −14.5 LUFS, RMS ≈ −16.5 dBFS, locución casi continua entre 1.0 y 46.2 s (huecos en `shots.yaml: vo_gaps_s`).
- Camas bajo locución: `gain_db` −14 a −24 (RMS final −34 a −44 dBFS).
- Eventos bajo locución: −10 a −20. En huecos sin locución: −4 a −12 (son los momentos donde el SFX se luce).
- Remate 46.6–49.75 (sin música): camas −8 a −14, eventos −2 a −8. Objetivo LUFS-S ≈ −24 (A) / −20 (B).
- La mezcla aplica automáticamente: duck + carving M/S de la locución, filtro anti-bombo en SUB, limitador de SFX con margen sobre el bed.

## Buses / stems
| Bus | Contenido |
|---|---|
| AMB | ambientes, room tones, texturas |
| VEH | auto: rodado, EV, pass-bys, sprays |
| FOL | foley: pandas, gansos, objetos, gotas |
| DES | diseñado: whooshes, risers, glints, motivo, impactos sin sub |
| SUB | solo graves diseñados (≤ 100 Hz), sólo en ventanas permitidas |

## Herramientas
- `python -m sfx.audition <receta> [--dur 3] [--params '{"k":v}'] [--at 12.3] [--out out/audition/<familia>]` → WAV + PNG espectrograma + stats JSON. Con `--at` además mezcla sobre el bed para escuchar en contexto.
- `python -m sfx.render A|B` → stems en `out/render/<opción>/`.
- `python -m sfx.mix A|B` → preview + verificación.

## Dueños de archivos
| Archivo | Dueño |
|---|---|
| `sfx/core.py`, `sfx/dsp.py`, `sfx/analyze.py`, `sfx/render.py`, `sfx/mix.py`, `sfx/verify.py`, `sfx/audition.py`, `cues/shots.yaml`, `cues/recipe_catalog.yaml`, `docs/CONTRACT.md` | orquestador |
| `sfx/recipes/ambience.py` + `out/audition/ambience/` | agente Ambience |
| `sfx/recipes/vehicle.py` + `out/audition/vehicle/` | agente Vehicle |
| `sfx/recipes/creature.py` + `out/audition/creature/` | agente Creature |
| `sfx/recipes/foley.py` + `out/audition/foley/` | agente Foley |
| `sfx/recipes/designed.py` + `out/audition/designed/` | agente Designed |
| `cues/option_a.yaml`, `cues/spotting_a.md` | spotter A |
| `cues/option_b.yaml`, `cues/spotting_b.md` | spotter B |

Si falta una primitiva en `sfx/dsp.py`, impleméntala dentro de tu propio módulo (helper privado `_nombre`) — no edites archivos ajenos.
