"""Constantes, E/S y contratos comunes del motor de diseño sonoro.

Toda la línea de tiempo se expresa en frames de video (24 fps) o en samples (48 kHz).
1 frame = 2000 samples. El spot dura 1194 frames = 2_388_000 samples = 49.75 s.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48_000
FPS = 24
SPF = SR // FPS  # samples por frame
N_FRAMES = 1194
N_TOTAL = N_FRAMES * SPF  # 2_388_000

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
OUT = ROOT / "out"
CUES = ROOT / "cues"
ANALYSIS = ROOT / "analysis"

BED_WAV = MEDIA / "bed_DC_Geely.wav"
PICTURE = MEDIA / "picture.mov"


# ---------------------------------------------------------------- tiempo

def f2s(frames: float) -> int:
    """Frames -> samples."""
    return int(round(frames * SPF))


def t2s(seconds: float) -> int:
    """Segundos -> samples."""
    return int(round(seconds * SR))


def s2t(samples: int) -> float:
    return samples / SR


def tc(samples: int) -> str:
    """Samples -> timecode HH:MM:SS:FF a 24 fps."""
    fr = int(samples // SPF)
    ff = fr % FPS
    s = fr // FPS
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}:{ff:02d}"


_CUT_RE = re.compile(r"^cut\[(\d+)\]\s*([+-]\s*\d+(?:\.\d+)?)?\s*(f|s)?$")


def resolve_time(spec, cuts_frames: list[int] | None = None) -> int:
    """Convierte una posición del cue sheet a samples.

    Formatos aceptados:
      12.5        -> segundos
      "f:182"     -> frame 182
      "s:12.5"    -> segundos
      "cut[7]"    -> frame del corte 7 (0-based, lista de cues/shots.yaml)
      "cut[7]+3"  -> corte 7 + 3 frames ("cut[7]+0.1s" -> +0.1 s)
    """
    if isinstance(spec, (int, float)):
        return t2s(float(spec))
    spec = str(spec).strip()
    if spec.startswith("f:"):
        return f2s(float(spec[2:]))
    if spec.startswith("s:"):
        return t2s(float(spec[2:]))
    m = _CUT_RE.match(spec)
    if m:
        if cuts_frames is None:
            raise ValueError("se necesita la lista de cortes para resolver " + spec)
        base = f2s(cuts_frames[int(m.group(1))])
        if m.group(2):
            off = float(m.group(2).replace(" ", ""))
            base += t2s(off) if m.group(3) == "s" else f2s(off)
        return base
    return t2s(float(spec))


# ---------------------------------------------------------------- dB

def db(x: float) -> float:
    return 10.0 ** (x / 20.0)


def to_db(x, floor: float = -200.0):
    x = np.asarray(x, dtype=np.float64)
    return np.maximum(20.0 * np.log10(np.maximum(np.abs(x), 1e-12)), floor)


# ---------------------------------------------------------------- RNG

def stable_rng(*keys) -> np.random.Generator:
    """RNG determinista a partir de claves (opción, id de cue, semilla...)."""
    h = hashlib.sha256("|".join(str(k) for k in keys).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


# ---------------------------------------------------------------- Render

@dataclass
class Render:
    """Resultado de una receta.

    audio: float32 [n, 2] estéreo.
    sync_offset: sample dentro de `audio` que debe caer exactamente en el tiempo del cue
                 (transiente de un impacto, pico de un whoosh, final de un swell reverso...).
    meta: información libre (p. ej. {"peak_t": ...}).
    """

    audio: np.ndarray
    sync_offset: int = 0
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        a = np.asarray(self.audio, dtype=np.float32)
        if a.ndim == 1:
            a = np.stack([a, a], axis=1)
        if a.shape[1] != 2 and a.shape[0] == 2:
            a = a.T
        self.audio = np.ascontiguousarray(a, dtype=np.float32)
        self.sync_offset = int(self.sync_offset)


# ---------------------------------------------------------------- registro de recetas

RECIPES: dict[str, dict] = {}


def recipe(name: str, family: str, sync: str = "start", kind: str = "event", doc: str = ""):
    """Decorador para registrar una receta.

    Firma obligatoria:  fn(dur: float, rng: np.random.Generator, **params) -> Render
    `dur` en segundos (duración nominal del evento; la cola de reverb puede excederla).
    `sync` describe qué representa sync_offset: start | transient | peak | end.
    `kind`: "event" (one-shot; el renderer lo normaliza a pico -6 dBFS) o
            "bed" (cama/loop; el renderer lo normaliza a RMS -20 dBFS). El gain_db del cue va encima.
    """

    def deco(fn):
        if name in RECIPES and RECIPES[name]["fn"].__module__ != fn.__module__:
            raise ValueError(f"receta duplicada: {name}")
        RECIPES[name] = {"fn": fn, "family": family, "sync": sync, "kind": kind,
                         "doc": doc or (fn.__doc__ or "").strip()}
        return fn

    return deco


def load_all_recipes():
    """Importa todos los módulos de sfx/recipes para poblar RECIPES."""
    import importlib
    import pkgutil

    from . import recipes as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{mod.name}")
    return RECIPES


# ---------------------------------------------------------------- E/S

def read_wav(path, sr_expected: int = SR) -> np.ndarray:
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != sr_expected:
        raise ValueError(f"{path}: sr={sr}, se esperaba {sr_expected}")
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x


def load_bed() -> np.ndarray:
    """Mezcla original (música + locución) como float32 [N_TOTAL, 2], sin ninguna modificación."""
    x = read_wav(BED_WAV)
    if len(x) < N_TOTAL:
        x = np.concatenate([x, np.zeros((N_TOTAL - len(x), 2), np.float32)])
    return x[:N_TOTAL]


def write_wav(path, x: np.ndarray, subtype: str = "PCM_24"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(x, dtype=np.float32), SR, subtype=subtype)


def env_threads():
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
