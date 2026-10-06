"""Protección de la locución y la música, y control de picos.

* protect_cue(): duck de banda ancha + "unmask" M/S en STFT durante la locución (por cue).
* kick_duck(): el bus SUB respira entre golpes de bombo.
* headroom_limiter(): limita SOLO el bus de SFX para que (bed + SFX) no supere el techo;
  el bed nunca recibe ganancia variable.
* true_peak(): pico real con sobremuestreo 4x.
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
from scipy import signal

from . import dsp
from .core import ANALYSIS, N_TOTAL, SR, load_bed

NPERSEG = 2048
HOP = 512


@lru_cache(maxsize=1)
def _bed():
    return load_bed().astype(np.float64)


@lru_cache(maxsize=1)
def vo_curve() -> np.ndarray:
    """0..1 por sample: presencia de locución, con anticipación de 80 ms y release de 300 ms."""
    v = json.loads((ANALYSIS / "vo_regions.json").read_text())
    m = np.zeros(N_TOTAL)
    for a, b in v["regions"]:
        m[int(a * SR):int(b * SR)] = 1.0
    # anticipación (offline): expandir 80 ms hacia atrás, rampas suaves
    pre = int(0.08 * SR)
    ker_a = np.ones(pre) / pre
    m_pre = np.convolve(m, ker_a, mode="full")[pre - 1:pre - 1 + N_TOTAL]  # mira hacia adelante
    rel = int(0.3 * SR)
    ker_r = np.ones(rel) / rel
    m_rel = np.convolve(m, ker_r, mode="full")[:N_TOTAL]
    return np.clip(np.maximum(m_pre, m_rel), 0, 1)


LEVELS = {"none": None,
          "light": dict(duck_db=2.0, margin_db=6.0, floor_db=-9.0),
          "normal": dict(duck_db=4.0, margin_db=9.0, floor_db=-15.0),
          "strong": dict(duck_db=6.0, margin_db=12.0, floor_db=-20.0)}


def protect_cue(a: np.ndarray, start: int, level: str = "normal") -> np.ndarray:
    """Aplica protección de locución a un cue estéreo ya colocado en `start` (sample absoluto)."""
    cfg = LEVELS.get(level, LEVELS["normal"])
    if cfg is None or len(a) == 0:
        return a
    n = len(a)
    i0, i1 = max(0, start), min(N_TOTAL, start + n)
    if i1 <= i0:
        return a
    vo = np.zeros(n)
    vo[i0 - start:i1 - start] = vo_curve()[i0:i1]
    if vo.max() < 1e-3:
        return a
    # 1) duck de banda ancha
    g = 1.0 - vo * (1.0 - 10 ** (-cfg["duck_db"] / 20))
    a = a * g[:, None]
    # 2) unmask M/S en STFT (250 Hz - 5 kHz)
    bed = np.zeros((n, 2))
    bed[i0 - start:i1 - start] = _bed()[i0:i1]
    m = (a[:, 0] + a[:, 1]) * 0.5
    s = (a[:, 0] - a[:, 1]) * 0.5
    om = (bed[:, 0] + bed[:, 1]) * 0.5
    if n < NPERSEG:
        return a
    f, t, X = signal.stft(m, SR, nperseg=NPERSEG, noverlap=NPERSEG - HOP)
    _, _, S = signal.stft(s, SR, nperseg=NPERSEG, noverlap=NPERSEG - HOP)
    _, _, O = signal.stft(om, SR, nperseg=NPERSEG, noverlap=NPERSEG - HOP)
    ratio = 10 ** (-cfg["margin_db"] / 20) * np.abs(O) / (np.abs(X) + 1e-9)
    G = np.minimum(1.0, ratio)
    band = ((f >= 250) & (f <= 5000)).astype(float)
    # transición suave de banda (1/3 oct)
    band = np.convolve(band, np.ones(5) / 5, mode="same")[:, None]
    vo_t = np.interp(t, np.arange(n) / SR, vo)[None, :]
    G = 1.0 - band * vo_t * (1.0 - G)
    # suavizado tiempo (~40 ms) y frecuencia
    G = signal.convolve2d(G, np.ones((3, 5)) / 15.0, mode="same", boundary="symm")
    G = np.maximum(G, 10 ** (cfg["floor_db"] / 20))
    _, m2 = signal.istft(X * G, SR, nperseg=NPERSEG, noverlap=NPERSEG - HOP)
    Gs = 1.0 - 0.3 * (1.0 - G)
    _, s2 = signal.istft(S * Gs, SR, nperseg=NPERSEG, noverlap=NPERSEG - HOP)
    m2, s2 = dsp.pad_to(m2, n), dsp.pad_to(s2, n)
    return np.stack([m2 + s2, m2 - s2], axis=1)


@lru_cache(maxsize=1)
def kick_env() -> np.ndarray:
    """Envolvente 0..1 del bombo del bed (30-150 Hz), ataque 5 ms / release 120 ms."""
    x = _bed().mean(axis=1)
    low = signal.sosfiltfilt(signal.butter(4, [30, 150], btype="band", fs=SR, output="sos"), x)
    e = np.abs(low)
    # seguidor ataque/release
    a_att = np.exp(-1 / (0.005 * SR))
    a_rel = np.exp(-1 / (0.12 * SR))
    env = np.zeros_like(e)
    # bloque para velocidad: decimar 48x
    d = 48
    ed = e[: len(e) // d * d].reshape(-1, d).max(axis=1)
    out = np.zeros_like(ed)
    acc = 0.0
    aa, ar = a_att ** d, a_rel ** d
    for i, v in enumerate(ed):
        acc = aa * acc + (1 - aa) * v if v > acc else ar * acc + (1 - ar) * v
        out[i] = acc
    env = np.repeat(out, d)
    env = dsp.pad_to(env, N_TOTAL)
    return env / (env.max() + 1e-12)


def kick_duck(sub: np.ndarray, depth_db: float = 10.0) -> np.ndarray:
    k = kick_env()
    g = 10 ** (-depth_db * np.clip(k * 1.5, 0, 1) / 20)
    return sub * g[:, None]


def true_peak(x: np.ndarray) -> float:
    """Pico real (lineal) con sobremuestreo 4x."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    tp = 0.0
    for c in range(x.shape[1]):
        y = signal.resample_poly(x[:, c], 4, 1)
        tp = max(tp, float(np.abs(y).max()))
    return tp


def headroom_limiter(bed: np.ndarray, sfx: np.ndarray, ceiling_db: float = -1.0, lookahead_ms: float = 1.5,
                     release_ms: float = 60.0) -> np.ndarray:
    """Curva de ganancia g(t) en [0,1] para el SFX tal que |bed + g*sfx| <= max(techo, |bed|) (4x).

    El bed NUNCA se toca: si el bed ya supera el techo, el SFX solo no puede empeorarlo."""
    C = 10 ** (ceiling_db / 20)
    n = len(bed)
    gmin = np.ones(n)
    for c in range(2):
        o = signal.resample_poly(bed[:, c], 4, 1)
        s = signal.resample_poly(sfx[:, c], 4, 1)
        Cp = np.maximum(C, np.abs(o))
        same = np.sign(o) == np.sign(s)
        lim = np.where(same, (Cp - np.abs(o)) / (np.abs(s) + 1e-12), (Cp + np.abs(o)) / (np.abs(s) + 1e-12))
        lim = np.clip(lim, 0, 1)
        lim1 = lim.reshape(-1, 4).min(axis=1) if len(lim) % 4 == 0 else dsp.pad_to(lim, n * 4).reshape(-1, 4).min(axis=1)
        gmin = np.minimum(gmin, lim1[:n])
    # mínimo deslizante con look-ahead y release suave
    la = max(1, int(lookahead_ms * 1e-3 * SR))
    from scipy.ndimage import minimum_filter1d

    g = minimum_filter1d(gmin, size=2 * la + 1, mode="nearest")
    a_rel = np.exp(-1 / (release_ms * 1e-3 * SR))
    # suavizado: release exponencial (bloques de 16 para velocidad)
    d = 16
    gd = dsp.pad_to(g, (n + d - 1) // d * d).reshape(-1, d).min(axis=1)
    out = np.empty_like(gd)
    acc = 1.0
    ar = a_rel ** d
    for i, v in enumerate(gd):
        acc = v if v < acc else ar * acc + (1 - ar) * v
        out[i] = acc
    g2 = np.repeat(out, d)[:n]
    return np.minimum(g2, g)
