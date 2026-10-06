"""Primitivas DSP para síntesis procedural de SFX (sin samples).

Convenciones:
  * Todo a SR = 48 kHz, float64 internamente, salida float32.
  * Señales mono: np.ndarray 1-D. Estéreo: [n, 2].
  * Las curvas variables en el tiempo (frecuencia de corte, pan, ganancia) pueden ser escalares
    o arrays de longitud n (usa `curve()` para construirlas desde breakpoints).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .core import SR

TWO_PI = 2.0 * np.pi


# =============================================================== utilidades

def n_of(dur: float) -> int:
    return max(1, int(round(dur * SR)))


def as_curve(v, n: int) -> np.ndarray:
    """Escalar o array -> array float64 de longitud n."""
    if np.isscalar(v):
        return np.full(n, float(v))
    v = np.asarray(v, dtype=np.float64)
    if len(v) == n:
        return v
    return np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(v)), v)


def curve(points, n: int, shape: str = "lin") -> np.ndarray:
    """Curva desde breakpoints [(t_rel 0..1 o segundos, valor), ...].

    Si el último t > 1 se interpretan como segundos.
    shape: lin | exp (interpola en log, valores > 0) | smooth (s-curve por tramo)
    """
    pts = np.asarray(points, dtype=np.float64)
    ts, vs = pts[:, 0], pts[:, 1]
    if ts[-1] > 1.0 + 1e-9:
        ts = ts * SR / n
    x = np.linspace(0, 1, n)
    if shape == "exp":
        return np.exp(np.interp(x, ts, np.log(np.maximum(vs, 1e-9))))
    if shape == "smooth":
        idx = np.clip(np.searchsorted(ts, x, side="right") - 1, 0, len(ts) - 2)
        t0, t1 = ts[idx], ts[idx + 1]
        u = np.clip((x - t0) / np.maximum(t1 - t0, 1e-12), 0, 1)
        u = u * u * (3 - 2 * u)
        return vs[idx] + (vs[idx + 1] - vs[idx]) * u
    return np.interp(x, ts, vs)


def fade(x: np.ndarray, fin: float = 0.003, fout: float = 0.003, shape: str = "cos") -> np.ndarray:
    """Fade-in/out en segundos (mínimo 3 ms recomendado en todo borde)."""
    y = np.array(x, dtype=np.float64, copy=True)
    n = len(y)
    for dur, sl, rev in ((fin, slice(0, None), False), (fout, slice(None, None), True)):
        k = min(n, int(dur * SR))
        if k <= 1:
            continue
        r = np.linspace(0, 1, k)
        w = np.sin(r * np.pi / 2) ** 2 if shape == "cos" else r
        if rev:
            w = w[::-1]
            seg = slice(n - k, n)
        else:
            seg = slice(0, k)
        if y.ndim == 2:
            y[seg] *= w[:, None]
        else:
            y[seg] *= w
    return y


def stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return np.stack([x, x], axis=1) if x.ndim == 1 else x


def mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def mix_into(dst: np.ndarray, src: np.ndarray, at: int, gain: float = 1.0) -> np.ndarray:
    """Suma src en dst desde el sample `at` (recorta bordes). Ambos mono o ambos estéreo."""
    a0, b0 = max(0, at), min(len(dst), at + len(src))
    if b0 > a0:
        dst[a0:b0] += gain * src[a0 - at:b0 - at]
    return dst


def pad_to(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    pad = np.zeros((n - len(x),) + x.shape[1:], dtype=x.dtype)
    return np.concatenate([x, pad])


def peak_norm(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    p = np.abs(x).max()
    return x if p < 1e-12 else x * (10 ** (peak_db / 20) / p)


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12))


def dc_block(x: np.ndarray, fc: float = 10.0) -> np.ndarray:
    return sos_filter(x, butter_sos(2, fc, "highpass"))


# =============================================================== ruido

def white(n: int, rng) -> np.ndarray:
    return rng.standard_normal(n)


def colored(n: int, rng, slope_db_oct: float = -3.0, f_lo: float = 5.0) -> np.ndarray:
    """Ruido con pendiente espectral (dB/octava). -3 = rosa, -6 = marrón, +3 = azul. RMS = 1."""
    m = 1 << int(np.ceil(np.log2(n + 1)))
    spec = np.fft.rfft(rng.standard_normal(m))
    f = np.fft.rfftfreq(m, 1 / SR)
    f[0] = f[1]
    spec *= (np.maximum(f, f_lo) / 1000.0) ** (slope_db_oct / 6.0206)
    y = np.fft.irfft(spec, m)[:n]
    return y / (np.std(y) + 1e-12)


def pink(n, rng):
    return colored(n, rng, -3.0)


def brown(n, rng):
    return colored(n, rng, -6.0, f_lo=15.0)


def velvet(n: int, rng, density: float = 2000.0) -> np.ndarray:
    """Ruido velvet: impulsos ±1 dispersos (density por segundo)."""
    y = np.zeros(n)
    k = max(1, int(n * density / SR))
    pos = rng.integers(0, n, k)
    y[pos] = rng.choice([-1.0, 1.0], k)
    return y


def poisson_times(dur: float, rate, rng, t0: float = 0.0) -> np.ndarray:
    """Tiempos de eventos Poisson. rate escalar (eventos/s) o función rate(t)."""
    out, t = [], t0
    rmax = rate if np.isscalar(rate) else max(rate(x) for x in np.linspace(t0, t0 + dur, 64)) + 1e-9
    while True:
        t += rng.exponential(1.0 / rmax)
        if t >= t0 + dur:
            break
        r = rate if np.isscalar(rate) else rate(t)
        if rng.random() < r / rmax:
            out.append(t)
    return np.array(out)


def random_walk(n: int, rng, rate_hz: float = 0.3, depth: float = 1.0) -> np.ndarray:
    """Modulador 1/f suave y acotado en [-depth, depth] aprox. (para que nada sea estático)."""
    k = max(4, int(n / SR * rate_hz * 8) + 4)
    pts = np.cumsum(rng.standard_normal(k))
    pts -= np.linspace(pts[0], pts[-1], k)  # sin deriva
    pts /= (np.abs(pts).max() + 1e-9)
    xs = np.linspace(0, 1, k)
    y = np.interp(np.linspace(0, 1, n), xs, pts)
    # suavizado
    w = max(3, int(SR / (rate_hz * 6)))
    if w < n:
        ker = np.hanning(w)
        y = np.convolve(y, ker / ker.sum(), mode="same")
        y /= (np.abs(y).max() + 1e-9)
    return y * depth


def gust_env(n: int, rng, base: float = 0.5, depth: float = 0.5, rate_hz: float = 0.25) -> np.ndarray:
    """Envolvente de ráfagas (0..1) para viento."""
    g = base + depth * (0.6 * random_walk(n, rng, rate_hz) + 0.4 * random_walk(n, rng, rate_hz * 2.7))
    return np.clip(g, 0.02, 1.5)


# =============================================================== filtros

def butter_sos(order: int, fc, kind: str = "lowpass"):
    nyq = SR / 2
    if np.ndim(fc):
        fc = [min(max(f, 5.0), nyq * 0.98) for f in fc]
    else:
        fc = min(max(float(fc), 5.0), nyq * 0.98)
    return signal.butter(order, fc, btype=kind, fs=SR, output="sos")


def sos_filter(x: np.ndarray, sos) -> np.ndarray:
    return signal.sosfilt(sos, x, axis=0)


def lp(x, fc, order=4):
    return sos_filter(x, butter_sos(order, fc, "lowpass"))


def hp(x, fc, order=4):
    return sos_filter(x, butter_sos(order, fc, "highpass"))


def bp(x, lo, hi, order=2):
    return sos_filter(x, butter_sos(order, [lo, hi], "bandpass"))


def rbj(kind: str, fc: float, q: float = 0.707, gain_db: float = 0.0):
    """Coeficientes biquad RBJ normalizados (b, a)."""
    fc = min(max(fc, 10.0), SR * 0.49)
    w0 = TWO_PI * fc / SR
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    A = 10 ** (gain_db / 40)
    if kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":  # ganancia de pico 0 dB
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "notch":
        b = [1, -2 * cw, 1]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
        a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
    elif kind == "highshelf":
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
        a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError(kind)
    b, a = np.array(b), np.array(a)
    return b / a[0], a / a[0]


def eq(x, kind: str, fc: float, q: float = 0.707, gain_db: float = 0.0):
    b, a = rbj(kind, fc, q, gain_db)
    return signal.lfilter(b, a, x, axis=0)


def tv_filter(x: np.ndarray, fc, kind: str = "lowpass", q=0.707, gain_db=0.0, block: int = 64,
              stages: int = 1) -> np.ndarray:
    """Filtro biquad variable en el tiempo (fc, q, gain pueden ser curvas). Estado continuo por bloques.

    stages > 1 encadena biquads idénticos (pendientes más fuertes)."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    fcc = as_curve(fc, n)
    qc = as_curve(q, n)
    gc = as_curve(gain_db, n)
    y = x.copy()
    for _ in range(stages):
        out = np.empty_like(y)
        zi = np.zeros((2,) + y.shape[1:])
        for i in range(0, n, block):
            j = min(n, i + block)
            m = (i + j) // 2
            b, a = rbj(kind, fcc[m], qc[m], gc[m])
            out[i:j], zi = signal.lfilter(b, a, y[i:j], axis=0, zi=zi)
        y = out
    return y


def spectral_paint(n: int, rng, mag_fn, nperseg: int = 2048, slope_db_oct: float = 0.0) -> np.ndarray:
    """Ruido modelado en STFT: mag_fn(t_s [T], f_hz [F]) -> ganancia lineal [F, T]. RMS ~1."""
    hop = nperseg // 4
    x = colored(n + nperseg, rng, slope_db_oct) if slope_db_oct else rng.standard_normal(n + nperseg)
    f, t, Z = signal.stft(x, SR, nperseg=nperseg, noverlap=nperseg - hop)
    G = np.asarray(mag_fn(t, f), dtype=np.float64)
    _, y = signal.istft(Z * G, SR, nperseg=nperseg, noverlap=nperseg - hop)
    y = y[:n]
    return y / (np.std(y) + 1e-12)


def comb(x: np.ndarray, delay_s, fb: float = 0.5, mix: float = 0.5) -> np.ndarray:
    """Comb con retardo variable (flanger) vía interpolación lineal."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    d = as_curve(delay_s, n) * SR
    idx = np.arange(n) - d
    delayed = np.interp(idx, np.arange(n), x, left=0.0)
    return (1 - mix) * x + mix * (delayed * (1 - fb) + fb * np.interp(idx - d, np.arange(n), x, left=0.0))


def one_pole_lp(x, fc):
    a = np.exp(-TWO_PI * fc / SR)
    return signal.lfilter([1 - a], [1, -a], x, axis=0)


# =============================================================== envolventes

def adsr(n: int, a: float, d: float, s: float, r: float, curve_pow: float = 1.0) -> np.ndarray:
    """ADSR en segundos; sustain ocupa el resto. curve_pow > 1 = más exponencial."""
    ia, idd, ir = int(a * SR), int(d * SR), int(r * SR)
    isus = max(0, n - ia - idd - ir)
    env = np.concatenate([
        np.linspace(0, 1, ia, endpoint=False) ** (1 / curve_pow) if ia else np.zeros(0),
        1 - (1 - s) * np.linspace(0, 1, idd, endpoint=False) ** (1 / curve_pow) if idd else np.zeros(0),
        np.full(isus, s),
        s * (1 - np.linspace(0, 1, ir) ** (1 / curve_pow)) if ir else np.zeros(0),
    ])
    return pad_to(env, n)


def exp_decay(n: int, tau: float, attack: float = 0.0005) -> np.ndarray:
    t = np.arange(n) / SR
    env = np.exp(-t / max(tau, 1e-5))
    ka = int(attack * SR)
    if ka > 1:
        env[:ka] *= np.linspace(0, 1, ka)
    return env


def swell(n: int, peak_pos: float = 0.65, attack_pow: float = 2.0, release_pow: float = 1.5) -> np.ndarray:
    """Envolvente asimétrica 0->1->0 con pico en peak_pos (fracción). Para whooshes/pass-bys."""
    k = max(1, int(n * peak_pos))
    up = np.linspace(0, 1, k) ** attack_pow
    down = (1 - np.linspace(0, 1, n - k)) ** release_pow
    return np.concatenate([up, down])


# =============================================================== osciladores

def phase_from_freq(f, n: int, phase0: float = 0.0) -> np.ndarray:
    return phase0 + TWO_PI * np.cumsum(as_curve(f, n)) / SR


def sine(f, n: int, phase0: float = 0.0) -> np.ndarray:
    return np.sin(phase_from_freq(f, n, phase0))


def _polyblep(t, dt):
    y = np.zeros_like(t)
    m = t < dt
    u = t[m] / dt[m]
    y[m] = u + u - u * u - 1.0
    m2 = t > 1.0 - dt
    u = (t[m2] - 1.0) / dt[m2]
    y[m2] = u * u + u + u + 1.0
    return y


def saw(f, n: int, phase0: float = 0.0) -> np.ndarray:
    fc = as_curve(f, n)
    dt = np.clip(fc / SR, 1e-7, 0.5)
    ph = (phase0 / TWO_PI + np.cumsum(dt)) % 1.0
    return 2.0 * ph - 1.0 - _polyblep(ph, dt)


def pulse(f, n: int, width=0.5, phase0: float = 0.0) -> np.ndarray:
    fc = as_curve(f, n)
    dt = np.clip(fc / SR, 1e-7, 0.5)
    w = as_curve(width, n)
    ph = (phase0 / TWO_PI + np.cumsum(dt)) % 1.0
    ph2 = (ph + 1.0 - w) % 1.0
    return (2.0 * ph - 1.0 - _polyblep(ph, dt)) - (2.0 * ph2 - 1.0 - _polyblep(ph2, dt))


def additive(f0, n: int, ratios, amps_db, rng=None, detune_cents: float = 0.0, beat_hz: float = 0.0,
             decays=None) -> np.ndarray:
    """Banco de parciales sobre f0 (escalar o curva). ratios/amps_db listas. Opcional: pares desafinados
    que baten a beat_hz, decays (tau por parcial en s)."""
    f0c = as_curve(f0, n)
    y = np.zeros(n)
    for i, (r, a) in enumerate(zip(ratios, amps_db)):
        amp = 10 ** (a / 20)
        ph0 = 0.0 if rng is None else rng.uniform(0, TWO_PI)
        fr = f0c * r
        part = np.sin(phase_from_freq(fr * 2 ** (detune_cents / 1200), n, ph0))
        if beat_hz:
            part = 0.5 * part + 0.5 * np.sin(phase_from_freq(fr + beat_hz * (1 + 0.37 * i), n, ph0 + 1.3))
        if decays is not None:
            part *= exp_decay(n, decays[i])
        y += amp * part
    return y


def fm(fc, ratio: float, index, n: int, phase0: float = 0.0) -> np.ndarray:
    """FM de 2 operadores. fc/index pueden ser curvas."""
    fcc = as_curve(fc, n)
    mod = np.sin(phase_from_freq(fcc * ratio, n))
    return np.sin(phase_from_freq(fcc, n, phase0) + as_curve(index, n) * mod)


# =============================================================== modales / físicos

def modal(n: int, freqs, decays, amps_db, rng=None, exciter: np.ndarray | None = None,
          detune: float = 0.0) -> np.ndarray:
    """Banco de senos amortiguados (vidrio, metal, plástico...). Si exciter se da, se convoluciona."""
    t = np.arange(n) / SR
    y = np.zeros(n)
    for f, tau, a in zip(freqs, decays, amps_db):
        if rng is not None and detune:
            f = f * (1 + rng.uniform(-detune, detune))
        ph = 0.0 if rng is None else rng.uniform(0, TWO_PI)
        y += 10 ** (a / 20) * np.exp(-t / tau) * np.sin(TWO_PI * f * t + ph)
    if exciter is not None:
        y = signal.oaconvolve(y, exciter)[:n]
    return y


def soft_exciter(dur: float = 0.01) -> np.ndarray:
    """Excitador half-cosine (golpe blando)."""
    k = max(2, int(dur * SR))
    return np.sin(np.linspace(0, np.pi, k)) / (k / 2)


def bubble(f0: float, tau: float, n: int, glide: float = 0.3, rng=None) -> np.ndarray:
    """Burbuja/gota (Minnaert): seno amortiguado con glissando ascendente + tick inicial."""
    t = np.arange(n) / SR
    f = f0 * (1 + glide * (1 - np.exp(-t / (tau * 0.8))))
    y = np.sin(phase_from_freq(f, n)) * np.exp(-t / tau)
    k = int(0.0015 * SR)
    tick = np.zeros(n)
    tick[:k] = (rng.standard_normal(k) if rng is not None else np.random.standard_normal(k)) * np.linspace(1, 0, k)
    return y + 0.3 * hp(tick, 2000, 2)


def stick_slip(n: int, f_curve, rng, jitter: float = 0.08, sharp: float = 0.002) -> np.ndarray:
    """Tren de pulsos de fricción (chirrido/squeak). f_curve = tasa de pulsos (Hz)."""
    fc = as_curve(f_curve, n)
    y = np.zeros(n)
    t = 0.0
    k = int(sharp * SR) + 2
    pulse_shape = np.exp(-np.linspace(0, 6, k)) * np.sin(np.linspace(0, np.pi * 3, k))
    while True:
        i = int(t * SR)
        if i >= n:
            break
        y[i:i + k] += pulse_shape[: max(0, min(k, n - i))] * (0.7 + 0.6 * rng.random())
        f = max(20.0, fc[i])
        t += (1.0 / f) * (1 + jitter * rng.standard_normal())
    return y


def grains(n: int, times_s, make_grain, rng, gain_jitter_db: float = 4.0) -> np.ndarray:
    """Coloca granos: make_grain(rng, i) -> array (mono o estéreo). times en segundos relativos."""
    out = None
    for i, ts in enumerate(times_s):
        g = make_grain(rng, i)
        if out is None:
            out = np.zeros((n,) + g.shape[1:])
        mix_into(out, g, int(ts * SR), 10 ** (rng.uniform(-gain_jitter_db, 0) / 20))
    return out if out is not None else np.zeros(n)


# =============================================================== espacio

def pan_gains(p):
    p = np.clip(p, -1, 1)
    th = (p + 1) * np.pi / 4
    return np.cos(th), np.sin(th)


def pan(x: np.ndarray, p=0.0) -> np.ndarray:
    """Pan de potencia constante (p escalar o curva, -1 izq .. +1 der). Entrada mono."""
    x = mono(x)
    gl, gr = pan_gains(as_curve(p, len(x)))
    return np.stack([x * gl, x * gr], axis=1)


def width(x: np.ndarray, w=1.0) -> np.ndarray:
    """Ancho estéreo vía M/S (w=0 mono, 1 igual, >1 más ancho)."""
    x = stereo(x)
    m = (x[:, 0] + x[:, 1]) * 0.5
    s = (x[:, 0] - x[:, 1]) * 0.5 * as_curve(w, len(x))
    return np.stack([m + s, m - s], axis=1)


def decorrelated_stereo(make, rng, corr: float = 0.5) -> np.ndarray:
    """Construye estéreo con correlación aprox. `corr` a partir de un generador make(rng)->mono."""
    a, b, c = make(rng), make(rng), make(rng)
    k = np.sqrt(max(0.0, corr))
    j = np.sqrt(max(0.0, 1 - corr))
    return np.stack([k * a + j * b, k * a + j * c], axis=1)


def haas(x: np.ndarray, side: float = 0.0, max_ms: float = 0.6) -> np.ndarray:
    """ITD simple: retrasa el canal opuesto según side (-1..1)."""
    x = stereo(x)
    d = int(abs(side) * max_ms * 1e-3 * SR)
    if d == 0:
        return x
    y = x.copy()
    ch = 1 if side < 0 else 0  # si suena a la izq., retrasar el derecho
    y[:, ch] = np.concatenate([np.zeros(d), x[:-d, ch]])
    return y


def passby(src: np.ndarray, *, speed_ms: float, closest_m: float, t_closest: float,
           direction: int = 1, height_m: float = 0.5, ground: float = 0.35, air: bool = True,
           near_clamp_m: float = 1.0, pan_scale: float = 0.9) -> np.ndarray:
    """Pass-by con cinemática real: Doppler (retardo variable), 1/r, absorción del aire,
    reflejo de suelo (barrido de peine) y pan/ITD. src mono a nivel de "1 m".
    Devuelve estéreo normalizado para que el punto más cercano tenga ganancia ~1."""
    src = mono(src)
    n = len(src)
    t = np.arange(n) / SR
    c = 343.0
    x = direction * speed_ms * (t - t_closest)
    r = np.sqrt(x ** 2 + closest_m ** 2)
    r2 = np.sqrt(x ** 2 + closest_m ** 2 + (2 * height_m) ** 2)
    idx = np.arange(n)
    direct = np.interp(idx - r / c * SR, idx, src, left=0.0, right=0.0)
    refl = np.interp(idx - r2 / c * SR, idx, src, left=0.0, right=0.0)
    rr = np.maximum(r, near_clamp_m)
    g = closest_m / rr
    y = direct * g + ground * refl * (closest_m / np.maximum(r2, near_clamp_m))
    if air:
        fc = np.clip(20000.0 * np.sqrt(np.maximum(closest_m, 1.0) / np.maximum(rr, 1.0)) ** 1.2, 1800.0, 19000.0)
        y = tv_filter(y, fc, "lowpass", 0.6)
    p = np.clip(np.arctan2(x, closest_m) / (np.pi / 2) * pan_scale, -1, 1)
    out = pan(y, p)
    # ITD leve
    d = (p * 0.0005 * SR)
    out[:, 0] = np.interp(idx - np.maximum(d, 0), idx, out[:, 0], left=0.0)
    out[:, 1] = np.interp(idx - np.maximum(-d, 0), idx, out[:, 1], left=0.0)
    return out


# =============================================================== reverb (IR sintética)

def make_ir(rt60_low: float, rt60_mid: float, rt60_high: float, rng, *, predelay_ms: float = 8.0,
            er_taps=None, er_gain_db: float = -6.0, length_s: float | None = None, density_ms: float = 0.0,
            corr: float = 0.15, flutter_ms: float = 0.0, flutter_gain: float = 0.0) -> np.ndarray:
    """IR estéreo sintética: reflexiones tempranas + cola por bandas con decaimiento exponencial.

    er_taps: lista de (ms, dB) para reflexiones tempranas (se jitterean por canal).
    flutter_ms: eco periódico (túnel, paredes paralelas)."""
    length_s = length_s or max(0.25, 1.3 * max(rt60_low, rt60_mid, rt60_high))
    n = int(length_s * SR)
    t = np.arange(n) / SR
    pre = int(predelay_ms * 1e-3 * SR)
    chans = []
    shared = rng.standard_normal(n)
    for ch in range(2):
        own = rng.standard_normal(n)
        nz = np.sqrt(corr) * shared + np.sqrt(1 - corr) * own
        lo = lp(nz, 400, 2)
        mid = bp(nz, 400, 4000, 2)
        hi = hp(nz, 4000, 2)
        tail = (lo * np.exp(-6.91 * t / max(rt60_low, 0.01)) +
                mid * np.exp(-6.91 * t / max(rt60_mid, 0.01)) +
                hi * np.exp(-6.91 * t / max(rt60_high, 0.01)))
        # entrada suave de la cola (tiempo de mezcla)
        mix_t = 0.012 + 0.02 * rt60_mid
        tail *= np.clip(t / mix_t, 0, 1) ** 1.5
        if density_ms:
            sparse = velvet(n, rng, 1000.0 / density_ms) * np.exp(-6.91 * t / max(rt60_mid, 0.01))
            tail = 0.6 * tail + 0.8 * lp(sparse, 6000, 2)
        ir = np.zeros(n)
        ir[pre:] = tail[: n - pre]
        ir /= (np.sqrt(np.sum(ir ** 2)) + 1e-12)
        if er_taps:
            for ms, gdb in er_taps:
                k = pre + int((ms * (1 + rng.uniform(-0.08, 0.08))) * 1e-3 * SR)
                if 0 <= k < n:
                    ir[k] += 10 ** ((gdb + er_gain_db) / 20) * rng.choice([-1, 1]) * 0.5
        if flutter_ms and flutter_gain:
            step = int(flutter_ms * 1e-3 * SR)
            for i, k in enumerate(range(pre + step, n, step)):
                ir[k] += flutter_gain * (0.82 ** i) * rng.choice([-1, 1]) * 0.3
        chans.append(ir)
    ir = np.stack(chans, axis=1)
    return ir / (np.sqrt(np.sum(ir ** 2) / 2) + 1e-12)


def convolve(x: np.ndarray, ir: np.ndarray, wet: float = 1.0, dry: float = 0.0, tail: bool = True) -> np.ndarray:
    """Convoluciona (estéreo o mono) con IR estéreo. Devuelve estéreo con cola si tail=True."""
    x = stereo(x)
    n = len(x)
    L = signal.oaconvolve(x[:, 0], ir[:, 0])
    R = signal.oaconvolve(x[:, 1], ir[:, 1])
    y = np.stack([L, R], axis=1) * wet
    if dry:
        y[:n] += dry * x
    return y if tail else y[:n]


_IR_CACHE: dict = {}


def ir_preset(name: str) -> np.ndarray:
    """IRs con nombre (deterministas). Ver docs/CONTRACT.md para la lista."""
    if name in _IR_CACHE:
        return _IR_CACHE[name]
    from .core import stable_rng

    rng = stable_rng("ir", name)
    P = {
        "underpass_concrete": dict(rt60_low=2.0, rt60_mid=1.6, rt60_high=0.8, predelay_ms=12,
                                   er_taps=[(25, -3), (33, -5), (41, -6), (58, -9), (77, -12)]),
        "city_fog_street": dict(rt60_low=1.1, rt60_mid=0.9, rt60_high=0.35, predelay_ms=20,
                                er_taps=[(38, -8), (64, -11), (95, -14), (121, -17)]),
        "city_day_street": dict(rt60_low=0.7, rt60_mid=0.6, rt60_high=0.3, predelay_ms=15,
                                er_taps=[(30, -8), (52, -11), (88, -15)]),
        "open_exterior": dict(rt60_low=0.35, rt60_mid=0.25, rt60_high=0.12, predelay_ms=4,
                              er_taps=[(3, -6)], length_s=0.5),
        "valley_mountain": dict(rt60_low=1.4, rt60_mid=1.0, rt60_high=0.4, predelay_ms=30,
                                er_taps=[(310, -18), (540, -22), (860, -27)], er_gain_db=0.0, length_s=2.2),
        "forest": dict(rt60_low=0.6, rt60_mid=0.5, rt60_high=0.3, predelay_ms=6, density_ms=1.5),
        "tunnel": dict(rt60_low=3.5, rt60_mid=3.0, rt60_high=1.4, predelay_ms=10, flutter_ms=41,
                       flutter_gain=0.6, er_taps=[(20, -4), (41, -5)]),
        "cabin_small": dict(rt60_low=0.2, rt60_mid=0.15, rt60_high=0.08, predelay_ms=1.5,
                            er_taps=[(1.5, -2), (2.7, -4), (4.1, -6), (6.0, -8)], length_s=0.3),
        "studio_stage": dict(rt60_low=2.2, rt60_mid=2.2, rt60_high=1.6, predelay_ms=25,
                             er_taps=[(40, -10), (70, -12)]),
        "designed_hall": dict(rt60_low=5.0, rt60_mid=5.0, rt60_high=3.5, predelay_ms=35, corr=0.05),
        "rock_arch": dict(rt60_low=0.6, rt60_mid=0.6, rt60_high=0.3, predelay_ms=2,
                          er_taps=[(4, -2), (7, -3), (11, -5), (15, -6)]),
    }
    if name not in P:
        raise KeyError(f"IR desconocida: {name}. Disponibles: {sorted(P)}")
    ir = make_ir(rng=rng, **P[name])
    _IR_CACHE[name] = ir
    return ir


IR_PRESETS = ["underpass_concrete", "city_fog_street", "city_day_street", "open_exterior", "valley_mountain",
              "forest", "tunnel", "cabin_small", "studio_stage", "designed_hall", "rock_arch"]


def through_glass(x: np.ndarray) -> np.ndarray:
    """Exterior escuchado desde dentro del auto (vidrio laminado)."""
    y = lp(x, 1200, 2)
    y = eq(y, "highshelf", 2000, 0.7, -10)
    y = eq(y, "peak", 220, 0.9, 2)
    return y


def reverb(x: np.ndarray, preset: str, send_db: float = -12.0, dry: float = 1.0, hp_send: float = 0.0) -> np.ndarray:
    """Atajo: dry + envío a IR preset (con cola). hp_send filtra el envío (p. ej. 200 Hz en subs)."""
    x = stereo(x)
    s = hp(x, hp_send, 2) if hp_send else x
    wet = convolve(s, ir_preset(preset), wet=10 ** (send_db / 20))
    wet[: len(x)] += dry * x
    return wet


# =============================================================== saturación

def soft_clip(x, drive: float = 1.0):
    return np.tanh(x * drive) / np.tanh(drive)
