"""Ambiences / room tones / natural beds (familia "ambience").

Diseño (pensado en capas, como un editor de ambientes):
  * Todas las camas se construyen sobre ruido blanco de varianza 1 "pintado" en STFT (`_paint`), de modo
    que las capas (cuerpo, silbidos, textura) comparten la misma base física: su magnitud es densidad
    espectral relativa y se pueden equilibrar por física y no "a oído".
  * Estéreo de par espaciado: coherencia L/R dependiente de la frecuencia (graves coherentes, agudos
    decorrelados) -> ancho natural sin fase rara.
  * Nada estático: moduladores 1/f a tasa de control (`_ctrl_noise`) en ganancia, cortes y pitch.
  * Las camas se sintetizan con pre-roll y se recorta: la reverb/espacio ya está en régimen al sample 0.
  * Eventos (gotas, pájaros, olas, pasos lejanos) se re-sintetizan uno a uno desde el rng.
  * Paso alto 120 Hz 24 dB/oct por defecto; capas de cuerpo intencionales (rumble) a 70 Hz.
  * Elementos tonales sólo en notas de la tonalidad (Bb Db Eb F Ab).
"""
from __future__ import annotations

import re

import numpy as np
from scipy import signal

from .. import dsp
from ..core import SR, Render, recipe

FAM = "ambience"


# ====================================================================== utilidades básicas

def _db(x):
    return 10.0 ** (np.asarray(x, dtype=np.float64) / 20.0)


def _n(dur) -> int:
    return max(1, int(round(float(dur) * SR)))


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)


_SEMI = {"C": 0, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}


def _note(name: str) -> float:
    """'Bb4' -> Hz (A4 = 440)."""
    m = re.match(r"^([A-G]b?)(-?\d)$", str(name).strip())
    if not m:
        raise ValueError(f"nota inválida: {name}")
    midi = _SEMI[m.group(1)] + 12 * (int(m.group(2)) + 1)
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


_KEY = ("Bb", "Db", "Eb", "F", "Ab")


def _key_freqs(lo: float, hi: float) -> np.ndarray:
    """Frecuencias de las notas de la tonalidad (Bb Db Eb F Ab) entre lo y hi."""
    fs = [_note(f"{nm}{o}") for o in range(1, 9) for nm in _KEY]
    fs = np.array(sorted(f for f in fs if lo <= f <= hi))
    return fs if len(fs) else np.array([np.sqrt(lo * hi)])


def _smooth01(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# ====================================================================== moduladores 1/f (rápidos)

def _ctrl_noise(n: int, rng, f_lo: float, f_hi: float, slope: float = -1.0) -> np.ndarray:
    """Ruido de control con espectro de potencia ~ f^slope entre f_lo y f_hi (Hz), a tasa de control
    e interpolado a n samples. Normalizado por la desviación del proceso completo (no de la ventana):
    en un buffer corto sólo aparece la deriva lenta que realmente cabe, como en la física."""
    kr = float(max(40.0, 8.0 * f_hi))
    m = int(n / SR * kr) + 4
    L = 1 << int(np.ceil(np.log2(max(64, 2 * m, int(4 * kr / max(f_lo, 1e-3))))))
    f = np.fft.rfftfreq(L, 1.0 / kr)
    f[0] = f[1]
    mag = f ** (slope / 2.0) / np.sqrt(1.0 + (f_lo / f) ** 4) / np.sqrt(1.0 + (f / f_hi) ** 4)
    mag[0] = 0.0
    spec = (rng.standard_normal(len(f)) + 1j * rng.standard_normal(len(f))) * mag
    y = np.fft.irfft(spec, L)
    y = y / (y.std() + 1e-12)
    y = y[:m]
    return np.interp(np.arange(n) * (kr / SR), np.arange(m), y)


def _mod(n, rng, f_lo, f_hi, depth, slope=-1.0):
    """Modulador acotado en ±depth (±depth ~ 2 sigma)."""
    z = _ctrl_noise(n, rng, f_lo, f_hi, slope)
    return depth * np.clip(np.tanh(z / 2.0) / np.tanh(1.0), -1.0, 1.0)


def _gmod(n, rng, f_lo, f_hi, depth_db, slope=-1.0):
    """Modulación de ganancia lineal acotada en ±depth_db."""
    return _db(_mod(n, rng, f_lo, f_hi, depth_db, slope))


def _gusts(n, rng, gustiness=0.5, corr=0.6, f_lo=0.08, f_hi=2.0):
    """Ráfagas normalizadas (mediana ~1), log-normales con espectro de Kolmogorov (-5/3).
    Devuelve [n, 2]; los procesos L/R tienen correlación `corr`."""
    sig = 0.6 * float(gustiness)
    z0 = _ctrl_noise(n, rng, f_lo, f_hi, slope=-5.0 / 3.0)
    out = []
    for _ in range(2):
        z = np.sqrt(corr) * z0 + np.sqrt(1.0 - corr) * _ctrl_noise(n, rng, f_lo, f_hi, slope=-5.0 / 3.0)
        g = np.exp(sig * z)
        g = 1.9 * np.tanh(g / 1.9)
        out.append(np.maximum(g, 0.05))
    return np.stack(out, axis=1)


# ====================================================================== pintura espectral estéreo

def _frames(curve, t):
    idx = np.clip((np.asarray(t) * SR).astype(np.int64), 0, len(curve) - 1)
    return curve[idx]


def _lpm(F, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (F / fc) ** (2 * order))


def _hpm(F, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (fc / np.maximum(F, 1.0)) ** (2 * order))


def _bump(F, fc, sig_oct):
    """Campana gaussiana en log-frecuencia (sig en octavas)."""
    return np.exp(-0.5 * (np.log2(np.maximum(F, 1.0) / fc) / sig_oct) ** 2)


def _coh(f, lo=0.8, hi=0.3, f0=500.0):
    """Coherencia L/R de par espaciado: alta en graves, baja en agudos."""
    return hi + (lo - hi) / (1.0 + (np.asarray(f) / f0) ** 1.5)


def _paint(n: int, rng, gain, *, coh=0.5, slope: float = 0.0, nperseg: int = 2048, tdec: int = 4) -> np.ndarray:
    """Ruido blanco estéreo (var 1) moldeado en STFT.

    gain: array [F,T] / [2,F,T] o función gain(t [T], f [F]) -> idem (magnitud = densidad relativa).
          Las funciones se evalúan cada `tdec` frames (control ~43 ms) y se interpolan (todo es lento).
    coh: escalar o función de f -> coherencia (= correlación) L/R por banda.
    slope: inclinación global en dB/oct (ref 1 kHz)."""
    hop = nperseg // 4
    # STFT de ruido blanco = coeficientes gaussianos complejos i.i.d. (se sintetizan directo: sólo ISTFT)
    T = (n + nperseg) // hop + 2
    f = np.fft.rfftfreq(nperseg, 1.0 / SR)
    t = np.arange(T) * hop / SR
    win = signal.get_window("hann", nperseg)
    sig = np.float32(np.sqrt(2.0 * np.sum(win ** 2)) / np.sum(win))  # -> var 1 a la salida (verificado)
    Z = (rng.standard_normal((3, len(f), T), dtype=np.float32)
         + 1j * rng.standard_normal((3, len(f), T), dtype=np.float32)) * sig
    Z[:, 0, :] = Z[:, 0, :].real * np.sqrt(2.0)
    Z[:, -1, :] = Z[:, -1, :].real * np.sqrt(2.0)
    c = coh(f) if callable(coh) else np.full(len(f), float(coh))
    c = np.clip(np.asarray(c, np.float64), 0.0, 1.0)[:, None]
    a, b = np.sqrt(c).astype(np.float32), np.sqrt(1.0 - c).astype(np.float32)
    tilt = ((np.maximum(f, 20.0) / 1000.0) ** (slope / 6.0206))[:, None].astype(np.float32)
    if callable(gain):
        if tdec > 1 and T > 2 * tdec:
            ts = t[::tdec]
            if ts[-1] < t[-1]:
                ts = np.append(ts, t[-1])
            Gs = np.asarray(gain(ts, f), dtype=np.float32)
            pos = np.interp(t, ts, np.arange(len(ts)))
            i0 = np.minimum(pos.astype(np.int64), len(ts) - 2)
            w = (pos - i0).astype(np.float32)
            G = Gs[..., i0] * (1 - w) + Gs[..., i0 + 1] * w
        else:
            G = np.asarray(gain(t, f), dtype=np.float32)
    else:
        G = np.asarray(gain, dtype=np.float32)
    if G.ndim == 2:
        G = np.stack([G, G])
    Y = np.stack([(a * Z[0] + b * Z[1]) * (tilt * G[0]), (a * Z[0] + b * Z[2]) * (tilt * G[1])])
    _, y = signal.istft(Y, SR, nperseg=nperseg, noverlap=nperseg - hop)
    y = y[:, nperseg // 2: nperseg // 2 + n]  # descartar el borde (primer frame centrado en 0)
    if y.shape[1] < n:
        y = np.pad(y, ((0, 0), (0, n - y.shape[1])))
    return np.ascontiguousarray(y.T, dtype=np.float64)


# ====================================================================== espacio / acabado

def _ir_len(preset) -> int:
    if not preset or preset == "none":
        return 0
    return len(dsp.ir_preset(preset))


def _pre(*presets, extra=0.3, cap=2.5) -> int:
    L = max([_ir_len(p) for p in presets] + [0])
    return int(min(L, cap * SR) + extra * SR)


def _space(x, preset, wet_db=-10.0, dry_db=0.0, hp_send=0.0):
    """dry + envío a IR (mismo largo que x; usar con pre-roll para estar en régimen)."""
    x = dsp.stereo(x)
    if not preset or preset == "none":
        return x * _db(dry_db)
    s = dsp.hp(x, hp_send, 2) if hp_send else x
    wet = dsp.convolve(s, dsp.ir_preset(preset), wet=float(_db(wet_db)), tail=False)
    return float(_db(dry_db)) * x + wet


def _bass_width(y, fc=280.0, w=0.45):
    """Graves más coherentes (como un par espaciado real en campo difuso; las IR sintéticas decorrelan todo
    por igual). División complementaria exacta: high = y - low."""
    if w >= 0.999:
        return y
    low = dsp.lp(y, fc, 2)
    return dsp.width(low, w) + (y - low)


def _finish(y, pre: int, n: int, hp_hz=120.0, order=4, fin=0.012, fout=0.04, bass_w=0.45, bass_fc=280.0):
    """HP (24 dB/oct) sobre todo el buffer (asienta el filtro en el pre-roll), graves coherentes, recorte,
    fades, higiene."""
    y = dsp.stereo(np.asarray(y, np.float64))
    if hp_hz:
        y = dsp.hp(y, hp_hz, order)
    else:
        y = dsp.dc_block(y, 8.0)
    y = _bass_width(y, bass_fc, bass_w)
    y = y[pre:pre + n]
    if len(y) < n:
        y = dsp.pad_to(y, n)
    y = dsp.fade(y, fin, fout)
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    return y.astype(np.float32)


def _finish_event(y, hp_hz=120.0, order=4, fin=0.003, fout=0.05):
    y = dsp.stereo(np.asarray(y, np.float64))
    if hp_hz:
        y = dsp.hp(y, hp_hz, order)
    y = dsp.fade(y, fin, fout)
    return np.nan_to_num(y).astype(np.float32)


# ====================================================================== granos / partículas

def _thin_times(n, rng, rate_curve, rmax=None):
    """Tiempos (samples) Poisson con tasa variable (eventos/s por sample) por thinning vectorizado."""
    rc = np.asarray(rate_curve, np.float64)
    rmax = float(rc.max() if rmax is None else rmax) + 1e-9
    k = rng.poisson(rmax * n / SR)
    pos = np.sort(rng.integers(0, n, k))
    keep = rng.random(k) < rc[pos] / rmax
    return pos[keep]


def _crackle(n, rng, rate_curve, lo=3000.0, hi=10000.0, k_ms=(0.08, 0.6), amp_sigma=0.7, n_kernels=6):
    """Crepitar denso (arena, espuma, nieve): impulsos Poisson de amplitud log-normal convolucionados con
    varios núcleos cortos distintos (cada grano con forma propia), luego pasabanda."""
    pos = _thin_times(n, rng, rate_curve)
    out = np.zeros(n)
    if len(pos) == 0:
        return out
    amps = rng.lognormal(0.0, amp_sigma, len(pos)) * rng.choice([-1.0, 1.0], len(pos))
    which = rng.integers(0, n_kernels, len(pos))
    for k in range(n_kernels):
        sel = which == k
        if not sel.any():
            continue
        imp = np.zeros(n)
        np.add.at(imp, pos[sel], amps[sel])
        tau = rng.uniform(*k_ms) * 1e-3
        L = max(4, int(6 * tau * SR))
        tt = np.arange(L) / SR
        ker = rng.standard_normal(L) * np.exp(-tt / tau)
        ker[:2] *= (0.3, 0.7)
        out += signal.oaconvolve(imp, ker)[:n]
    return dsp.bp(out, lo, hi, 2)


def _grain_bank(n, rng, rate_curve, bands, *, att_ms=(0.4, 3.0), dec_ms=(4.0, 30.0), pan_spread=0.8,
                cluster=(1, 4), crackle=0.6):
    """Granos de roce (hojas, pasto seco): cada grano abre por un instante una portadora de banda distinta
    (ruido + crepitar), con ataque nítido y caída exponencial, en su propio pan. Devuelve [n, 2]."""
    pos = _thin_times(n, rng, rate_curve)
    nb = len(bands)
    envL = np.zeros((nb, n))
    envR = np.zeros((nb, n))
    max_len = int(0.2 * SR)
    tt_all = np.arange(max_len) / SR
    k = len(pos)
    # parámetros por grano (vectorizados) y micro-crujidos dentro de cada grano
    nc = rng.integers(cluster[0], cluster[1] + 1, k)
    gi = np.repeat(np.arange(k), nc)
    first = np.ones(len(gi), bool)
    first[1:] = gi[1:] != gi[:-1]
    off = pos[gi] + np.where(first, 0, (rng.uniform(2, 18, len(gi)) * 1e-3 * SR).astype(np.int64))
    band = rng.integers(0, nb, k)[gi]
    amp = (10 ** (rng.uniform(-14, 0, k) / 20))[gi] * np.where(first, 1.0, rng.uniform(0.25, 0.7, len(gi)))
    pl, pr = dsp.pan_gains(rng.uniform(-pan_spread, pan_spread, k))
    pl, pr = pl[gi], pr[gi]
    ta = rng.uniform(*att_ms, len(gi)) * 1e-3
    td = rng.uniform(*dec_ms, len(gi)) * 1e-3
    Ls = np.minimum(max_len, ((ta + 5 * td) * SR).astype(np.int64))
    for i in range(len(gi)):
        o, L = int(off[i]), int(Ls[i])
        if o >= n or L < 8:
            continue
        tt = tt_all[:L]
        e = np.exp(-np.maximum(tt - ta[i], 0.0) / td[i])
        ka = min(L, int(ta[i] * SR))
        if ka > 0:
            e[:ka] = np.sin(0.5 * np.pi * tt[:ka] / ta[i]) ** 2
        m = min(L, n - o)
        e = amp[i] * e[:m]
        envL[band[i], o:o + m] += pl[i] * e
        envR[band[i], o:o + m] += pr[i] * e
    out = np.zeros((n, 2))
    for b, (lo, hi) in enumerate(bands):
        if not envL[b].any():
            continue
        car = rng.standard_normal(n) + crackle * 3.0 * dsp.velvet(n, rng, 2500.0)
        car = dsp.bp(car, lo, hi, 2)
        car /= _rms(car)
        out[:, 0] += car * envL[b]
        out[:, 1] += car * envR[b]
    return out


# ====================================================================== agua

def _bubble_soft(f0, tau, n, glide=0.2):
    """Burbuja Minnaert formada dentro del agua (sin tic de impacto): ataque suave 1-2 ms."""
    t = np.arange(n) / SR
    f = f0 * (1 + glide * (1 - np.exp(-t / (tau * 0.8))))
    y = np.sin(dsp.phase_from_freq(f, n)) * np.exp(-t / tau)
    k = min(n, int(0.0015 * SR))
    y[:k] *= np.sin(0.5 * np.pi * np.arange(k) / k) ** 2
    return y


def _splash(f0, tau, glide, L, energy_db):
    """Corona de salpicadura del impacto de la gota en el charco (ruido 1.2-9 kHz, 2-5 ms, + 1-3 gotitas
    secundarias). Ruido de un generador local sembrado con los valores ya sorteados (f0, tau, glide): no
    consume el rng del cue, así los tiempos de goteo de cada semilla no cambian. energy_db = energía
    relativa a la de la burbuja (que con tau corto ya no domina la cola de la reverb como un tono fijo)."""
    lr = np.random.default_rng(int(abs(f0 * 7919.0 + tau * 1.3e7 + glide * 9.1e4)) % (2 ** 32))
    tt = np.arange(L) / SR
    tk = lr.uniform(0.002, 0.005)
    y = dsp.bp(lr.standard_normal(L), 1200.0, 9000.0, 2) * np.exp(-tt / tk)
    ka = max(2, int(0.0003 * SR))
    y[:ka] *= np.linspace(0.0, 1.0, ka)
    for _ in range(int(lr.integers(1, 4))):
        k = int(lr.uniform(0.006, 0.03) * SR)
        m = int(0.003 * SR)
        if k + m < L:
            y[k:k + m] += lr.uniform(0.2, 0.5) * dsp.hp(lr.standard_normal(m), 2500, 2) * np.hanning(m)
    e_b = 0.25 * tau                            # energía de un seno amortiguado de amplitud 1
    return y * np.sqrt(e_b * 10 ** (energy_db / 10) / (np.sum(y ** 2) / SR + 1e-20))


def _drop(rng, f0, tau, glide, hard=False, splash_db=None):
    """Una gota: burbuja Minnaert (f sube al aflorar) + tic de impacto, o 'splat' sobre superficie dura.
    splash_db (opcional): agrega la corona de salpicadura con esa energía relativa a la burbuja."""
    if not hard:
        L = int((6.5 * tau + 0.003) * SR)
        if splash_db is not None:
            L = max(L, int(0.035 * SR))
        y = dsp.bubble(f0, tau, L, glide, rng)
        if splash_db is not None:
            y = y + _splash(f0, tau, glide, L, splash_db)
        if rng.random() < 0.35:  # segunda burbujita (salpicadura que vuelve a caer)
            k = int(rng.uniform(0.012, 0.04) * SR)
            t2 = rng.uniform(0.5, 0.9) * tau
            y2 = dsp.bubble(f0 * rng.uniform(1.25, 1.8), t2, int(6 * t2 * SR) + 32, glide * 0.7, rng)
            y = dsp.pad_to(y, max(len(y), k + len(y2)))
            y[k:k + len(y2)] += rng.uniform(0.15, 0.4) * y2
    else:
        L = int(0.045 * SR)
        tt = np.arange(L) / SR
        y = dsp.bp(rng.standard_normal(L), 1400, 6500, 2) * np.exp(-tt / rng.uniform(0.0015, 0.004))
        for _ in range(int(rng.integers(1, 4))):  # micro-gotitas secundarias
            k = int(rng.uniform(0.008, 0.035) * SR)
            m = int(0.004 * SR)
            if k + m < L:
                y[k:k + m] += rng.uniform(0.1, 0.3) * dsp.hp(rng.standard_normal(m), 2500, 2) * np.hanning(m)
        y /= (np.abs(y).max() + 1e-9)
        y *= 0.6
    return dsp.fade(y, 0.0004, 0.002)


_DRIP_TAU_MAX = 0.0065   # s: el tono de la burbuja muere en <= ~30 ms (-40 dB) antes de la reverb
_DRIP_SPLASH_DB = -4.0  # energía de la corona de salpicadura re la burbuja (gota que cae 3-5 m a un charco)


def _drip_tau(tau_draw, f0):
    """Amortiguamiento físico de la burbuja de Minnaert de una gota (r ~ 1-2.5 mm): Q = pi f tau ~ 15-40,
    o sea tau ~ 2.5-6.5 ms a 1.5-3.5 kHz. El sorteo histórico (8-26 ms, Q ~ 40-160) dejaba un tono casi puro
    que la reverb del espacio sostenía 0.5-1 s como una línea fija (~2 kHz). Se conserva el sorteo del rng
    (mismos tiempos/semillas) y se mapea a ~0.36x, con tope absoluto y tope Q <= 40."""
    return float(min(0.36 * tau_draw, _DRIP_TAU_MAX, 40.0 / (np.pi * max(f0, 300.0))))


def _drips_layer(N, rng, *, rate=1.0, pitch=1.0, dist=0.5, t_start=0.0, t_vis=None):
    """Goteo: 1-6 fuentes cuasi periódicas (cada una con su pan, distancia, altura de gota) + algunas
    gotas aleatorias. Devuelve (direct [N,2], send [N,2]) para alimentar la reverb aparte."""
    dur = N / SR
    direct = np.zeros((N, 2))
    send = np.zeros((N, 2))
    ks = int(np.clip(round(1 + 1.3 * rate), 1, 6))
    times = []

    def place(t, f0, tau, glide, pn, d, hard):
        if t_vis is not None and -0.005 <= t - t_vis < 0.04:  # no cortar un ataque con el fade-in
            t = t_vis + rng.uniform(0.045, 0.09)
        y = _drop(rng, f0, _drip_tau(tau, f0), glide, hard, splash_db=_DRIP_SPLASH_DB)
        g = 1.0 / (1.0 + 3.0 * d)
        y = dsp.lp(y, 13000 * (1 - 0.7 * d), 2)
        st = dsp.pan(y, pn)
        i = int(t * SR)
        dsp.mix_into(direct, st, i, g * 10 ** (rng.uniform(-4, 0) / 20))
        dsp.mix_into(send, st, i, g * (0.5 + 1.6 * d))
        times.append(round(t, 3))

    for _ in range(ks):
        ri = max(1e-3, 0.8 * rate / ks * rng.lognormal(-0.06, 0.35))
        per = 1.0 / ri
        t = t_start + rng.uniform(0, per)
        pn = rng.uniform(-0.85, 0.85)
        d = float(np.clip(dist + rng.uniform(-0.35, 0.35), 0.05, 1.0))
        f0 = rng.uniform(1500, 3500) * pitch
        tau = rng.uniform(0.008, 0.02)
        hard = rng.random() < 0.25
        while t < dur:  # misma fuente: tamaño de gota, altura y ritmo varían gota a gota
            place(t, f0 * (1 + 0.08 * rng.standard_normal()), tau * rng.uniform(0.75, 1.3),
                  rng.uniform(0.1, 0.6), pn + rng.uniform(-0.05, 0.05), d, hard and rng.random() < 0.8)
            t += per * max(0.3, 1 + 0.27 * rng.standard_normal())
    for t in dsp.poisson_times(max(0.0, dur - t_start), 0.2 * rate, rng, t_start):
        place(t, rng.uniform(1500, 3500) * pitch, rng.uniform(0.008, 0.02), rng.uniform(0.1, 0.6),
              rng.uniform(-0.9, 0.9), float(np.clip(dist + rng.uniform(-0.4, 0.4), 0.05, 1.0)), rng.random() < 0.2)
    return direct, send, sorted(times)


def _river(N, rng, *, far=True):
    """Río lejano: ruido turbulento 300 Hz-2 kHz con AM 1/f rápida + nube de burbujas graves."""
    def g(t, f):
        F = f[:, None]
        return _hpm(F, 300, 2) * _lpm(F, 2000 if far else 3500, 2) * np.ones((1, len(t)))
    y = _paint(N, rng, g, coh=0.35, slope=-3.0)
    for c in range(2):
        y[:, c] *= _gmod(N, rng, 1.5, 25.0, 4.0)
    bub = np.zeros((N, 2))
    for t in dsp.poisson_times(N / SR, 70.0, rng):
        f0 = np.exp(rng.uniform(np.log(380), np.log(1900)))
        tau = rng.uniform(0.004, 0.012)
        b = _bubble_soft(f0, tau, int(6 * tau * SR) + 16, rng.uniform(0.05, 0.3))
        dsp.mix_into(bub, dsp.pan(b, rng.uniform(-0.8, 0.8)), int(t * SR), 10 ** (rng.uniform(-18, 0) / 20))
    bub = dsp.lp(bub, 2200 if far else 4000, 2)
    return y / _rms(y) + 0.6 * bub / (_rms(bub) + 1e-9)


def _lapping(N, rng, *, lap=0.5, t_vis=0.0):
    """Chapoteo de orilla: ráfagas graves burbujeantes 300 Hz-2 kHz a ritmo irregular (0.5-2 s), con
    nube de burbujas Minnaert graves y gotas que vuelven a caer. El primer chapoteo visible cae
    0.08-0.45 s después de t_vis (planos cortos) y hay uno previo en el pre-roll. Devuelve [N, 2] y tiempos."""
    dur = N / SR
    out = np.zeros((N, 2))
    t1 = t_vis + rng.uniform(0.08, 0.45)
    t_prev = t1 - float(np.clip(rng.gamma(3.0, 0.38), 0.5, 2.2))
    t = t_prev if t_prev > 0.02 else t1
    times = []
    first = True
    while t < dur:
        amp = rng.uniform(0.45, 1.0) * (0.6 + 0.8 * lap)
        pn = rng.uniform(-0.85, 0.85)
        ta = rng.uniform(0.06, 0.16)
        td = rng.uniform(0.22, 0.6)
        L = int((ta + 4 * td) * SR)
        tt = np.arange(L) / SR
        e = np.where(tt < ta, np.sin(0.5 * np.pi * tt / ta) ** 2, np.exp(-(tt - ta) / td))
        # cuerpo: dos sub-golpes (agua contra la piedra + resaca) con centros espectrales distintos
        lapb = np.zeros(L)
        for j in range(2):
            fc = np.exp(rng.uniform(np.log(380), np.log(950)))
            body = dsp.bp(rng.standard_normal(L), fc * 0.5, min(2000, fc * 2.2), 2)
            pk = (ta if j == 0 else ta + rng.uniform(0.06, 0.2)) / (L / SR)
            body = dsp.tv_filter(body, dsp.curve([(0, 500), (min(pk, 0.9), rng.uniform(1300, 2000)), (1, 600)], L,
                                                 "exp"), "lowpass", 0.7, block=256)
            ej = e if j == 0 else np.roll(e, int(rng.uniform(0.06, 0.2) * SR)) * rng.uniform(0.35, 0.7)
            lapb += body * ej
        lapb *= _gmod(L, rng, 6.0, 35.0, 6.0)  # gorgoteo: AM rápida y profunda, irregular
        lapb /= (np.abs(lapb).max() + 1e-9)
        # burbujas graves (radio 2-9 mm), audibles dentro del chapoteo
        for _ in range(int(rng.integers(6, 20))):
            k = int(rng.gamma(2.0, 0.5) * ta * SR)
            f0 = np.exp(rng.uniform(np.log(320), np.log(1500)))
            tau = rng.uniform(0.012, 0.04)
            b = _bubble_soft(f0, tau, int(6 * tau * SR) + 16, rng.uniform(0.05, 0.3))
            lapb = dsp.pad_to(lapb, max(len(lapb), k + len(b)))
            lapb[k:k + len(b)] += rng.uniform(0.15, 0.5) * b
        # gotas que vuelven a caer
        for _ in range(int(rng.integers(0, 4))):
            k = int((ta + rng.uniform(0.05, 0.35)) * SR)
            tau = rng.uniform(0.006, 0.014)
            b = _drop(rng, rng.uniform(1500, 3000), tau, rng.uniform(0.2, 0.5))
            lapb = dsp.pad_to(lapb, max(len(lapb), k + len(b)))
            lapb[k:k + len(b)] += rng.uniform(0.05, 0.16) * b
        lapb = dsp.fade(lapb, 0.003, 0.03)
        st = dsp.pan(lapb, pn)
        st = dsp.haas(st, pn * 0.5, 0.4)
        dsp.mix_into(out, st, int(t * SR), amp)
        times.append(round(t, 3))
        if first and t < t1:
            t = t1
        else:
            t += float(np.clip(rng.gamma(3.0, 0.38), 0.5, 2.2))
        first = False
    return out, times


# ====================================================================== viento (bloque de construcción)

_TEX = {
    "none": dict(band=(3000.0, 8000.0), slope=-1.5, coh=0.2, pw=2.5, gain=1.0),
    "grass": dict(band=(2200.0, 7500.0), slope=-1.0, coh=0.12, pw=2.2, gain=1.2),
    "snow": dict(band=(4500.0, 12000.0), slope=-1.0, coh=0.18, pw=2.5, gain=0.7),
    "sand": dict(band=(4000.0, 10000.0), slope=-0.5, coh=0.15, pw=2.5, gain=0.6),
    "leaves": dict(band=(1500.0, 6500.0), slope=-2.0, coh=0.2, pw=1.6, gain=0.9),
}


def _wind_layers(N, rng, *, strength=0.5, gustiness=0.5, whistle=0.3, texture="none", corr=0.6,
                 body=(400.0, 900.0), whistle_band=(400.0, 1600.0), n_whistles=None, tex_db=0.0,
                 hp_hz=120.0, gust_lo=None, gust_hi=2.0, sand=0.5, body_coh=0.85, grain_db=0.0, gate_floor=0.0,
                 leaf_att=(0.4, 3.0), leaf_crackle=0.6):
    """Viento por capas: cuerpo (marrón/rosa LPF 400-900 Hz con corte guiado por la ráfaga), filo (2-4
    silbidos eólicos Q 8-25 cuya frecuencia ~ velocidad, regla de Strouhal), textura (HP 3-8 kHz gateada).
    Devuelve dict de capas [N, 2] y las ráfagas."""
    dur = N / SR
    gn = _gusts(N, rng, gustiness, corr, gust_lo or max(0.06, 0.6 / dur), gust_hi)
    s = float(np.clip(strength, 0.05, 1.5))
    bright = 0.8 + 0.4 * s
    jit = [_mod(N, rng, 0.05, 0.6, 0.08) for _ in range(2)]
    bf = max(0.12, gate_floor)
    lvl = bf + (1.0 - bf) * gn ** 1.8  # nivel aerodinámico ~ v^1.8 (amplitud); el viento lejano nunca calla

    def fc_body(c, t):
        g = _frames(gn[:, c], t)
        return (body[0] + (body[1] - body[0]) * np.clip((g - 0.4) / 1.4, 0, 1)) * bright * (1 + _frames(jit[c], t))

    def body_mag(F, c, t):
        fc = fc_body(c, t)[None, :]
        tilt = (np.maximum(F, 20.0) / 1000.0) ** (-4.5 / 6.0206)
        m = _lpm(F, fc, 2) * (1 + 0.5 * _bump(F, fc, 0.4)) * _hpm(F, hp_hz, 2)
        return tilt * m * _frames(lvl[:, c], t)[None, :]

    def body_gain(t, f):
        F = f[:, None]
        tilt = (np.maximum(F, 20.0) / 1000.0) ** (-4.5 / 6.0206)
        return np.stack([body_mag(F, c, t) / tilt for c in range(2)])

    y_body = _paint(N, rng, body_gain, coh=lambda f: _coh(f, body_coh, 0.3, 450.0), slope=-4.5)
    layers = {"body": y_body}

    # ------------------------------------------------ silbidos eólicos
    if whistle > 0:
        nw = int(n_whistles or rng.integers(2, 5))
        # altura de reposo en notas de la tonalidad (luego se desliza con la ráfaga, regla de Strouhal)
        base = rng.choice(_key_freqs(whistle_band[0] * 1.1, whistle_band[1] * 0.8), nw)
        Q = rng.uniform(8, 25, nw)
        thr = rng.uniform(0.7, 1.15, nw)
        pans = rng.uniform(-0.75, 0.75, nw)
        mixc = rng.uniform(0.2, 0.8, nw)
        wob = [_mod(N, rng, 0.3, 4.0, 0.004) for _ in range(nw)]
        flick = [_gmod(N, rng, 0.3, 5.0, 3.0) * _smooth01(0.55 + 0.9 * _mod(N, rng, 0.4, 4.0, 1.0))
                 for _ in range(nw)]  # intermitencia: el tono eólico aparece y se corta
        boost = 1.0 + 4.0 * float(whistle)

        def w_gain(t, f):
            F = f[:, None]
            G = np.zeros((2, len(f), len(t)))
            gL, gR = _frames(gn[:, 0], t), _frames(gn[:, 1], t)
            for i in range(nw):
                gi = mixc[i] * gL + (1 - mixc[i]) * gR
                fc = base[i] * np.clip(gi, 0.6, 1.8) ** 0.8 * (1 + _frames(wob[i], t))
                act = _smooth01((gi - thr[i]) / 0.5) * _frames(flick[i], t)
                # nivel = cuerpo en esa frecuencia * boost (sobresale +9..+17 dB del cuerpo)
                ref = 0.5 * (body_mag(fc[None, :], 0, t) + body_mag(fc[None, :], 1, t))[0]
                sig = fc / Q[i] / 2.355
                bmp = np.exp(-0.5 * ((F - fc[None, :]) / sig[None, :]) ** 2) * (act * ref * boost)[None, :]
                pl, pr = dsp.pan_gains(pans[i])
                G[0] += pl * bmp
                G[1] += pr * bmp
            return G

        layers["whistle"] = _paint(N, rng, w_gain, coh=0.8, nperseg=4096)

    # ------------------------------------------------ textura
    tx = _TEX.get(texture, _TEX["none"])
    ref_body = 0.5 * (np.median(lvl[:, 0]) + np.median(lvl[:, 1]))
    tex_mag = 0.22 * tx["gain"] * _db(tex_db)
    lo, hi = tx["band"]
    gate = gate_floor + (1.0 - gate_floor) * np.clip(gn, 0, None) ** tx["pw"]
    if texture == "sand":
        gate = np.clip(gn - 0.5, 0, None) ** 2 * 1.6

    def t_gain(t, f):
        F = f[:, None]
        m = _hpm(F, lo, 3) * _lpm(F, hi, 3)
        return np.stack([m * (tex_mag * ref_body * _frames(gate[:, c], t))[None, :] for c in range(2)])

    tex = _paint(N, rng, t_gain, coh=tx["coh"], slope=tx["slope"])
    if texture == "grass":  # aleteo de hojas de pasto
        for c in range(2):
            tex[:, c] *= _gmod(N, rng, 3.0, 16.0, 4.0)
    layers["texture"] = tex

    body_rms = _rms(y_body)
    if texture == "sand":  # saltación: granos ~ (v - v_umbral)^3
        rc = [9000.0 * sand * np.clip(gn[:, c] - 0.5, 0, None) ** 2 + 400.0 * sand for c in range(2)]
        cr = np.stack([_crackle(N, rng, rc[c], 3000, 10000, (0.05, 0.35), amp_sigma=0.5) for c in range(2)], axis=1)
        layers["grains"] = cr / _rms(cr) * body_rms * _db(-17 + 10 * np.log10(max(sand, 0.05) / 0.5) + grain_db)
    elif texture == "leaves":
        rate = 50.0 + 150.0 * np.clip((0.5 * (gn[:, 0] + gn[:, 1]) - 0.3) / 1.2, 0, 1)
        gr = _grain_bank(N, rng, rate, [(2000, 3300), (3000, 4800), (4300, 6600), (5800, 8500)], att_ms=leaf_att,
                         crackle=leaf_crackle)
        layers["grains"] = gr / (_rms(gr) + 1e-12) * body_rms * _db(-15 + grain_db)
    elif texture == "snow":  # cristales de hielo sueltos, casi inaudibles
        rc = 12.0 * np.clip(0.5 * (gn[:, 0] + gn[:, 1]), 0, None) ** 2
        tk = np.stack([_crackle(N, rng, rc, 7000, 13000, (0.05, 0.2), 0.5) for _ in range(2)], axis=1)
        layers["grains"] = tk / (_rms(tk) + 1e-12) * body_rms * _db(-34 + grain_db)
    elif texture == "grass":  # tallos secos (coirón)
        rate = 25.0 + 70.0 * np.clip(0.5 * (gn[:, 0] + gn[:, 1]) - 0.6, 0, 1.5)
        gr = _grain_bank(N, rng, rate, [(2500, 4500), (4000, 7500)], dec_ms=(2.0, 10.0), cluster=(1, 3))
        layers["grains"] = gr / (_rms(gr) + 1e-12) * body_rms * _db(-26 + grain_db)
    layers["gusts"] = gn
    return layers


def _wind_mix(L, body_db=0.0, whistle_db=0.0, tex_db=0.0, grain_db=0.0):
    y = _db(body_db) * L["body"] + _db(tex_db) * L["texture"]
    if "whistle" in L:
        y = y + _db(whistle_db) * L["whistle"]
    if "grains" in L:
        y = y + _db(grain_db) * L["grains"]
    return y


# ====================================================================== ciudad / tráfico

def _far_passby(N, rng, t_c, *, speed_kmh=45.0, closest_m=80.0, direction=1, lp_hz=1200.0):
    """Paso lejano de auto eléctrico (sólo rodadura, sin motor): Doppler + suelo + absorción del aire."""
    src = dsp.colored(N, rng, -2.5)
    src = dsp.bp(src, 250, 1500, 2) + 0.25 * dsp.bp(rng.standard_normal(N), 1500, 4000, 2)
    src *= _gmod(N, rng, 0.2, 3.0, 1.5)
    y = dsp.passby(src, speed_ms=speed_kmh / 3.6, closest_m=closest_m, t_closest=t_c, direction=direction,
                   height_m=0.4, ground=0.45, air=True, pan_scale=0.85)
    return dsp.lp(y, lp_hz, 2)


def _traffic_wash(N, rng, *, lp_hz=600.0, density=0.5, fog=True):
    """Lavado de tráfico lejano: marrón/rosa pasabajos con corte que deriva y respiración lenta (más
    profunda cuanto menos denso es el tráfico)."""
    lpc = lp_hz * (0.78 if fog else 1.0)
    jit = [_mod(N, rng, 0.03, 0.3, 0.10) for _ in range(2)]
    shared = _mod(N, rng, 0.02, 0.35, 1.0)
    dens = float(np.clip(density, 0, 1))
    depth = 1.2 + 2.5 * (1.0 - dens)
    amp = [_db(depth * (0.7 * shared + 0.3 * _mod(N, rng, 0.02, 0.35, 1.0))) for _ in range(2)]
    # autos en otras calles: swells lentos localizados (banda, pan, tiempo), más marcados si hay poco tráfico
    dur = N / SR
    ks = int(rng.poisson(max(0.3, (0.4 + 0.8 * dens) * dur)))
    sw = [dict(t=rng.uniform(-1, dur + 1), s=rng.uniform(0.8, 2.5), a=_db(rng.uniform(2, 6 - 2 * dens)) - 1,
               fc=np.exp(rng.uniform(np.log(200), np.log(min(900.0, 1.3 * lpc)))), p=dsp.pan_gains(rng.uniform(-0.8, 0.8)))
          for _ in range(ks)]

    def g(t, f):
        F = f[:, None]
        out = []
        for c in range(2):
            fc = (lpc * (1 + _frames(jit[c], t)))[None, :]
            m = 1.0
            for s in sw:
                e = np.exp(-0.5 * ((t - s["t"]) / s["s"]) ** 2) * s["a"] * s["p"][c] * 1.41
                m = m + e[None, :] * _bump(F, s["fc"], 0.7)
            out.append(_lpm(F, fc, 2) * _hpm(F, 110, 2) * (1 + 0.4 * _bump(F, 220.0, 0.6)) *
                       _frames(amp[c], t)[None, :] * m)
        return np.stack(out)

    y = _paint(N, rng, g, coh=lambda f: _coh(f, 0.75, 0.3, 300.0), slope=-5.0)
    # siseo de rodadura lejano muy tenue (le da "distancia" y no sólo grave)
    def g2(t, f):
        F = f[:, None]
        return _hpm(F, 500, 2) * _lpm(F, 1500 if fog else 2500, 2) * np.ones((1, len(t)))
    h = _paint(N, rng, g2, coh=0.3, slope=-3.0)
    y = y / _rms(y) + _db(-17 if fog else -13) * h / _rms(h)
    if fog:
        y = dsp.eq(y, "highshelf", 1500, 0.7, -6)
    return y


def _tonal_hint(N, rng, t0, *, level=1.0):
    """Indicio tonal muy lejano: silbido de un tranvía/bus eléctrico distante (nota de la tonalidad),
    con leve deriva de pitch, envolvente lenta y mucha distancia. Nada de bocinas."""
    note = rng.choice(["Ab4", "Bb4", "Db5", "Eb5", "F5"])
    f0 = _note(note)
    sw = rng.uniform(2.5, 4.5)
    L = int(min(N - int(t0 * SR), sw * 2.2 * SR))
    if L < SR // 4:
        return np.zeros((N, 2)), None
    tt = np.arange(L) / SR
    fcur = f0 * (1 + 0.012 * _smooth01(tt / (sw * 1.6))) * (1 + _mod(L, rng, 0.2, 2.0, 0.003))
    ph = dsp.phase_from_freq(fcur, L, rng.uniform(0, 6.28))
    y = np.sin(ph) + 0.2 * np.sin(2 * ph + 1.1)
    y += 0.4 * dsp.bp(rng.standard_normal(L), f0 * 0.97, f0 * 1.03, 2) * 4.0
    env = dsp.curve([(0, 0), (0.45, 1), (0.6, 0.85), (1, 0)], L, "smooth")
    y = dsp.lp(y * env, 1600, 2)
    out = np.zeros((N, 2))
    dsp.mix_into(out, dsp.pan(y, rng.uniform(-0.6, 0.6)), int(t0 * SR), level)
    return out, note


# ====================================================================== pájaros

def _bird_note(rng, pts, dur_s, *, harm=(1.0, 0.15, 0.04), trill_hz=0.0, trill_depth=0.0, rough=0.0,
               att=0.006, breath=0.03, shape="smooth", jitter=0.004, jitter_band=(5.0, 40.0)):
    n = max(16, int(dur_s * SR))
    tt = np.arange(n) / SR
    fcur = dsp.curve(pts, n, shape) * (1 + _mod(n, rng, jitter_band[0], jitter_band[1], jitter))
    if trill_hz:
        fcur = fcur + trill_depth * np.sin(2 * np.pi * trill_hz * (1 + 0.05 * _mod(n, rng, 1, 8, 1.0)) * tt
                                           + rng.uniform(0, 6.28))
    fcur = np.clip(fcur, 200.0, 0.45 * SR)
    ph = dsp.phase_from_freq(fcur, n, rng.uniform(0, 6.28))
    y = np.zeros(n)
    for k, h in enumerate(harm):
        if h <= 0 or (k + 1) * fcur.max() > 0.45 * SR:
            continue
        y += h * np.sin((k + 1) * ph + rng.uniform(0, 6.28) * (k > 0))
    a = min(att / dur_s, 0.4)
    env = dsp.curve([(0, 0), (a, 1), (0.55, 0.8), (1, 0)], n, "smooth")
    if rough:
        env *= 1 + rough * _mod(n, rng, 20.0, 70.0, 1.0)
    if breath:
        y += breath * dsp.hp(rng.standard_normal(n), 2500, 4)
    return y * env


def _sparrow_call(rng, reg=1.0):
    """Gorrión: chirp FM 4-7 kHz, 50-150 ms, ligeramente áspero. Formas variadas: 'chirp' en V invertida,
    'cheep' descendente, 'chirrup' en dos partes, subida corta. reg = registro propio del pájaro (±8 %)."""
    parts = []
    shape = rng.choice(["chev", "chev", "down", "chirrup", "up"])
    hm = (1.0, rng.uniform(0.08, 0.16), 0.03)
    tr = dict(trill_hz=rng.uniform(45, 85), trill_depth=rng.uniform(50, 150), rough=rng.uniform(0.05, 0.2))
    if shape == "chirrup" or (shape == "chev" and rng.random() < 0.35):
        parts.append(_bird_note(rng, [(0, 3900 * reg), (1, rng.uniform(5300, 6100) * reg)],
                                rng.uniform(0.03, 0.05), harm=hm, att=0.004))
        parts.append(np.zeros(int(rng.uniform(0.012, 0.03) * SR)))
    d = rng.uniform(0.06, 0.14)
    if shape in ("chev", "chirrup"):
        pk = rng.uniform(0.22, 0.45)
        pts = [(0, rng.uniform(4000, 4600)), (pk, rng.uniform(5800, 6900)), (1, rng.uniform(4300, 5200))]
    elif shape == "down":
        pts = [(0, rng.uniform(6200, 6900)), (0.3, rng.uniform(5600, 6200)), (1, rng.uniform(4100, 4700))]
    else:
        d = rng.uniform(0.05, 0.08)
        pts = [(0, rng.uniform(4100, 4600)), (1, rng.uniform(5800, 6800))]
    pts = [(x, float(np.clip(v * reg, 3800, 7200))) for x, v in pts]
    parts.append(_bird_note(rng, pts, d, harm=hm, att=0.005, **tr))
    return np.concatenate(parts)


def _sparrow_bouts(rng, k, t0, t1):
    """Tiempos y 'quién canta' para k chirps de gorrión: a veces un pájaro repite enseguida (120-260 ms),
    luego una pausa más larga (0.35-0.9 s) y canta otro. Devuelve [(t, bird_id)]."""
    out, t, bird = [], t0, 0
    while len(out) < k and t < t1:
        out.append((t, bird))
        if len(out) < k and rng.random() < 0.5:  # repetición del mismo pájaro
            t2 = t + rng.uniform(0.12, 0.26)
            if t2 < t1:
                out.append((t2, bird))
            t = t2
        bird += 1 if rng.random() < 0.7 else 0
        t += rng.uniform(0.35, 0.9)
    return out[:k]


def _songbird_phrase(rng):
    """Pájaro genérico: 2-5 notas FM 3-7 kHz (subidas, bajadas, chevrones, trinos), 50-150 ms."""
    base = rng.uniform(3300, 5200)
    k = int(rng.integers(2, 6))
    motifs = []
    for _ in range(2):
        shp = rng.choice(["up", "down", "chev", "trill", "flat"])
        d = rng.uniform(0.05, 0.15)
        b = base * rng.uniform(0.85, 1.2)
        if shp == "up":
            pts = [(0, b * 0.82), (1, b * 1.3)]
        elif shp == "down":
            pts = [(0, b * 1.3), (1, b * 0.8)]
        elif shp == "chev":
            pts = [(0, b * 0.9), (0.4, b * 1.28), (1, b * 0.95)]
        else:
            pts = [(0, b), (1, b * rng.uniform(0.95, 1.05))]
        motifs.append((shp, d, pts))
    parts = []
    for i in range(k):
        shp, d, pts = motifs[0 if (i % 2 == 0 or rng.random() < 0.3) else 1]
        pts = [(x, np.clip(v * rng.uniform(0.98, 1.02), 3000, 7000)) for x, v in pts]
        tr = (rng.uniform(25, 45), rng.uniform(250, 600)) if shp == "trill" else (0.0, 0.0)
        parts.append(_bird_note(rng, pts, d * rng.uniform(0.9, 1.1), harm=(1.0, 0.1, 0.03), trill_hz=tr[0],
                                trill_depth=tr[1], att=0.008))
        parts.append(np.zeros(int(rng.uniform(0.04, 0.15) * SR)))
    return np.concatenate(parts)


def _raptor_cry(rng, max_len=None):
    """Rapaz muy lejana: UN grito descendente áspero (~3.3 -> 1.9 kHz) de 0.7-1.15 s, acortado a `max_len`
    (s, mínimo 0.3) para que termine dentro de la duración útil del cue. Aspereza (un FM armónico limpio se
    lee como silbido): jitter rápido de pitch (±1.2 %, 20-150 Hz) que ensancha los armónicos, AM irregular
    20-70 Hz (rough 0.6) + banda de ruido 1.5-4 kHz modulada a 30-60 Hz con la envolvente del grito
    (relación armónico/ruido ~4-7 dB)."""
    d = rng.uniform(0.7, 1.15)
    if max_len is not None:
        d = float(min(d, max(0.3, max_len)))
    f_hi = rng.uniform(3000, 3500)
    pts = [(0, f_hi * 0.8), (0.12, f_hi), (0.4, f_hi * 0.88), (1.0, rng.uniform(1800, 2100))]
    y = _bird_note(rng, pts, d, harm=(1.0, 0.45, 0.25, 0.12, 0.06), rough=0.6, att=0.04, breath=0.08,
                   jitter=0.012, jitter_band=(20.0, 150.0))     # jitter rápido: ensancha los armónicos (aspereza)
    n = len(y)
    env = dsp.curve([(0, 0), (min(0.04 / d, 0.4), 1), (0.55, 0.8), (1, 0)], n, "smooth")
    f_am = rng.uniform(30.0, 60.0) * (1.0 + _mod(n, rng, 0.5, 4.0, 0.15))
    am = 0.5 + 0.5 * np.sin(2 * np.pi * np.cumsum(f_am) / SR + rng.uniform(0, 6.28))
    rasp = dsp.bp(rng.standard_normal(n), 1500.0, 4000.0, 4) * env * (0.3 + 0.7 * am)
    rasp *= _db(rng.uniform(-7.0, -4.0)) * _rms(y) / _rms(rasp)
    return dsp.fade(y + rasp, 0.004, 0.03)


def _bird_track(N, rng, times, *, species="generic", dist=(40.0, 150.0), lp_ref=4000.0, pans=None, birds=None,
                fit=False, fit_fade=0.08):
    """Coloca llamadas de pájaro en [N,2] con distancia (nivel 1/r + absorción del aire). birds: id de pájaro
    por llamada (el mismo pájaro conserva posición, distancia y registro). Devuelve (direct, send).
    fit=True (eventos): las llamadas se sintetizan en un buffer más largo (nunca se truncan en seco en N), el
    grito de rapaz se acorta para terminar antes del siguiente / del final útil, y lo que pase de N se
    desvanece en `fit_fade` s terminando exactamente en N (sólo el eco/reverb posterior excede N)."""
    L = N + (int(1.7 * SR) if fit else 0)
    direct = np.zeros((L, 2))
    send = np.zeros((L, 2))
    who = {}
    order = sorted(times)
    for i, t in enumerate(times):
        sp = species if species != "mixed" else rng.choice(["generic", "sparrow"])
        bid = birds[i] if birds is not None else i
        if bid not in who:
            who[bid] = dict(dm=float(np.exp(rng.uniform(np.log(dist[0]), np.log(dist[1])))),
                            pn=(pans[i] if pans is not None else rng.uniform(-0.8, 0.8)), reg=rng.uniform(0.92, 1.08))
        if sp == "sparrow":
            call = _sparrow_call(rng, who[bid]["reg"])
        elif sp == "raptor":
            nxt = [u for u in order if u > t + 1e-6]
            lim = min([N / SR - 0.03] + [u - 0.12 for u in nxt]) - t
            call = _raptor_cry(rng, max_len=(lim if fit else None))
        else:
            call = _songbird_phrase(rng)
        dm = who[bid]["dm"] * rng.uniform(0.95, 1.05)
        lpf = float(np.clip(lp_ref * (60.0 / dm) ** 0.4, 2200.0, 9000.0))
        y = dsp.lp(call, lpf, 2)
        y = dsp.fade(y, 0.002, 0.01)
        pn = float(np.clip(who[bid]["pn"] + rng.uniform(-0.04, 0.04), -0.9, 0.9))
        st = dsp.pan(y, pn)  # sin ITD: en tonos de 3-7 kHz un retardo de 0.1-0.3 ms es anti-fase en mono
        g = (40.0 / dm) * 10 ** (rng.uniform(-3, 0) / 20)
        dsp.mix_into(direct, st, int(t * SR), g)
        dsp.mix_into(send, st, int(t * SR), g * (0.35 + dm / 250.0))
    if fit:
        k = max(8, int(fit_fade * SR))
        a = max(0, N - k)
        if np.abs(direct[a:]).max() > 0 or np.abs(send[a:]).max() > 0:
            ramp = np.cos(0.5 * np.pi * np.linspace(0.0, 1.0, N - a)) ** 2
            if np.abs(direct[N:]).max() == 0 and np.abs(send[N:]).max() == 0:
                ramp = np.ones(N - a)  # nada cruza N: no tocar lo que ya termina
            direct[a:N] *= ramp[:, None]
            send[a:N] *= ramp[:, None]
        direct, send = direct[:N], send[:N]
    return direct, send


def _valley_echo(x, rng, *, tail_db=-8.0, echoes=((0.31, -12.0), (0.54, -16.0), (0.86, -20.0), (1.21, -25.0)),
                 lp_hz=3400.0, tail_lp=3000.0):
    """Eco de valle compatible con mono para eventos (pájaros, gritos): reflexiones discretas de las
    laderas con polaridad coherente, cada una más lejana = más oscura y con pan espejado, + cola difusa
    estrechada (la IR del preset tiene taps con signo aleatorio por canal -> anti-fase en eventos tonales)."""
    x = dsp.stereo(x)
    n = len(x)
    L = n + int(1.6 * SR)
    out = np.zeros((L, 2))
    m = dsp.mono(x)
    for i, (dt, gdb) in enumerate(echoes):
        d = int(dt * (1 + rng.uniform(-0.06, 0.06)) * SR)
        e = dsp.lp(m, float(lp_hz) / (1 + 0.45 * i), 2)
        side = (-1) ** i * rng.uniform(0.3, 0.8)
        dsp.mix_into(out, dsp.pan(e, side), d, float(_db(gdb)))
    tail = dsp.convolve(x, dsp.ir_preset("valley_mountain"), wet=float(_db(tail_db)))
    tail = dsp.width(dsp.lp(tail, float(tail_lp), 2), 0.6)
    out[:min(L, len(tail))] += tail[:L]
    return out


def _natural_times(rng, count, t0, t1, min_gap=0.3):
    """Tiempos 'naturales' (no equiespaciados) para count eventos entre t0 y t1."""
    if count <= 0 or t1 <= t0:
        return []
    span = t1 - t0
    w = rng.gamma(2.0, 1.0, count + 1)
    pts = t0 + np.cumsum(w)[:-1] / w.sum() * span
    pts = np.sort(pts + rng.uniform(-0.1, 0.1, count) * span / (count + 1))
    for i in range(1, len(pts)):
        pts[i] = max(pts[i], pts[i - 1] + min_gap)
    return [float(p) for p in pts if p < t1]


# ====================================================================== cabina / máquinas

def _hvac(N, rng):
    """Aire de climatización: siseo suave 1-5 kHz (bordes que derivan) + soplador 150-350 Hz tenue."""
    jit = _mod(N, rng, 0.02, 0.2, 0.05)
    am = [_gmod(N, rng, 0.05, 0.6, 0.6) for _ in range(2)]

    def g(t, f):
        F = f[:, None]
        j = 1 + _frames(jit, t)[None, :]
        m = _hpm(F, 1000 * j, 2) * _lpm(F, 5000 * j, 2)
        return np.stack([m * _frames(am[c], t)[None, :] for c in range(2)])

    hiss = _paint(N, rng, g, coh=0.4, slope=-2.0)

    def g2(t, f):
        F = f[:, None]
        return _hpm(F, 150, 2) * _lpm(F, 350, 2) * np.ones((1, len(t)))

    blow = _paint(N, rng, g2, coh=0.7, slope=-3.0)
    return hiss / _rms(hiss) + _db(-8) * blow / _rms(blow)


def _fan_drone(N, rng, *, note="F3", beat=0.0045):
    """Ventiladores de túnel: ruido 120-400 Hz + tono de paso de aspas (dos ventiladores que baten,
    estrecho y vacilante, armónicos 1-2-4 = misma nota)."""
    f1 = _note(note)

    def g(t, f):
        F = f[:, None]
        return _hpm(F, 120, 2) * _lpm(F, 400, 2) * (1 + 0.8 * _bump(F, 260, 0.5)) * np.ones((1, len(t)))

    broad = _paint(N, rng, g, coh=lambda f: _coh(f, 0.8, 0.4, 300.0), slope=-3.0)
    broad *= _gmod(N, rng, 0.05, 0.8, 1.2)[:, None]
    tone = np.zeros(N)
    for j, det in enumerate([0.0, beat]):
        fj = f1 * (1 + det) * (1 + _mod(N, rng, 0.05, 0.8, 0.003))
        ph = dsp.phase_from_freq(fj, N, rng.uniform(0, 6.28))
        amp = _gmod(N, rng, 0.1, 3.0, 1.5)
        tone += amp * (np.sin(ph) + 0.35 * np.sin(2 * ph + rng.uniform(0, 6.28))
                       + 0.1 * np.sin(4 * ph + rng.uniform(0, 6.28))) * (1.0 if j == 0 else 0.7)
    # aire turbulento alrededor del tono (no es un seno puro)
    def gn_(t, f):
        F = f[:, None]
        return (np.exp(-0.5 * ((F - f1) / 3.0) ** 2) + 0.4 * np.exp(-0.5 * ((F - 2 * f1) / 5.0) ** 2)) * np.ones((1, len(t)))

    nb = _paint(N, rng, gn_, coh=0.7, nperseg=8192)
    tone_st = np.stack([tone, tone], axis=1) / _rms(tone) + 0.8 * nb / (_rms(nb) + 1e-12)
    return broad / _rms(broad), tone_st


# ====================================================================== RECETAS

_ROOM = {
    "underpass": dict(ir="underpass_concrete", band=(150, 1500), wet=-3.0, dry=-6.0, air=(4000, 12000), air_slope=-2.0,
                      air_trim=0.0, rumble=(70, 170), modes=[(118, 0.12, 3.0), (176, 0.1, 2.5), (290, 0.15, 2.0),
                                                              (610, 0.3, 1.5)]),
    "city_fog": dict(ir="city_fog_street", band=(150, 1100), wet=-4.0, dry=-4.0, air=(3500, 9000), air_slope=-3.0,
                     air_trim=-4.0, rumble=(70, 200), modes=[(230, 0.5, 1.5)]),
    "city_day": dict(ir="city_day_street", band=(150, 1800), wet=-6.0, dry=-3.0, air=(4000, 14000), air_slope=-1.5,
                     air_trim=0.0, rumble=(70, 200), modes=[(240, 0.4, 1.5)]),
    "cabin": dict(ir="cabin_small", band=(120, 800), wet=-6.0, dry=-2.0, air=(2500, 7000), air_slope=-3.0,
                  air_trim=-6.0, rumble=(70, 160), modes=[(95, 0.15, 3.0), (160, 0.15, 2.0)]),
    "studio": dict(ir="studio_stage", band=(150, 1500), wet=-2.0, dry=-8.0, air=(4000, 14000), air_slope=-2.0,
                   air_trim=-2.0, rumble=(70, 150), modes=[]),
    "tunnel": dict(ir="tunnel", band=(130, 900), wet=-2.0, dry=-8.0, air=(3000, 10000), air_slope=-2.5,
                   air_trim=-3.0, rumble=(70, 180), modes=[(140, 0.2, 2.0), (210, 0.2, 1.5)]),
}


def _room_core(N, rng, sp, *, air_db=-18.0, rumble_db=-6.0, motion=1.0):
    lo, hi = sp["band"]
    elo = [_mod(N, rng, 0.03, 0.25, 0.07) for _ in range(2)]
    ehi = [_mod(N, rng, 0.03, 0.25, 0.07) for _ in range(2)]
    sh = _mod(N, rng, 0.05, 0.2, 1.0)
    am = [_db(1.5 * motion * (0.6 * sh + 0.4 * _mod(N, rng, 0.05, 0.2, 1.0))) for _ in range(2)]

    def g_body(t, f):
        F = f[:, None]
        out = []
        for c in range(2):
            m = _hpm(F, (lo * (1 + _frames(elo[c], t)))[None, :], 2) * _lpm(F, (hi * (1 + _frames(ehi[c], t)))[None, :], 2)
            for fc, so, gdb in sp["modes"]:
                m = m * (1 + (_db(gdb) - 1) * _bump(F, fc, so))
            out.append(m * _frames(am[c], t)[None, :])
        return np.stack(out)

    body = _paint(N, rng, g_body, coh=lambda f: _coh(f, 0.75, 0.3, 400.0), slope=-4.5)
    br = _rms(body)
    a_lo, a_hi = sp["air"]
    am2 = [_gmod(N, rng, 0.05, 0.3, 1.5 * motion) for _ in range(2)]

    def g_air(t, f):
        F = f[:, None]
        m = _hpm(F, a_lo, 2) * _lpm(F, a_hi, 2)
        return np.stack([m * _frames(am2[c], t)[None, :] for c in range(2)])

    air = _paint(N, rng, g_air, coh=0.15, slope=sp["air_slope"])
    air *= _db(air_db + sp["air_trim"]) * br / _rms(air)
    r_lo, r_hi = sp["rumble"]
    am3 = _gmod(N, rng, 0.03, 0.15, 2.0 * motion)

    def g_rum(t, f):
        F = f[:, None]
        return _hpm(F, r_lo, 2) * _lpm(F, r_hi, 2) * _frames(am3, t)[None, :]

    rum = _paint(N, rng, g_rum, coh=0.85, slope=-6.0)
    rum *= _db(rumble_db) * br / _rms(rum)
    return body + air + rum


@recipe("amb.room_tone", family=FAM, sync="start", kind="bed")
def room_tone(dur, rng, *, space="underpass", air_db=-18.0, rumble_db=-6.0, motion=1.0, **_):
    """Tono de sala: rosa 150 Hz-1.5 kHz (-4.5 dB/oct) con AM lenta 1/f + aire 4-14 kHz + rumble, en su IR.
    space: underpass|city_fog|city_day|cabin|studio|tunnel."""
    sp = _ROOM.get(space, _ROOM["underpass"])
    n = _n(dur)
    pre = _pre(sp["ir"])
    N = n + pre
    y = _room_core(N, rng, sp, air_db=air_db, rumble_db=rumble_db, motion=motion)
    y = _space(y, sp["ir"], sp["wet"], sp["dry"])
    out = _finish(y, pre, n, hp_hz=70.0 if rumble_db > -40 else 120.0)
    return Render(out, 0, {"space": space, "ir": sp["ir"], "layers": ["body", "air", "rumble"]})


@recipe("amb.city_distant", family=FAM, sync="start", kind="bed")
def city_distant(dur, rng, *, density=0.5, lp_hz=600.0, passbys=1, fog=True, tonal=0.3, space=None, **_):
    """Ciudad lejana: lavado de tráfico + 0-3 pasos lejanos EV muy filtrados y reverberados + un indicio
    tonal muy lejano opcional (tranvía eléctrico, nunca bocina)."""
    n = _n(dur)
    ir = space or ("city_fog_street" if fog else "city_day_street")
    pre = _pre(ir)
    N = n + pre
    wash = _traffic_wash(N, rng, lp_hz=lp_hz, density=density, fog=fog)
    wr = _rms(wash)
    y = wash.copy()
    send = 0.35 * wash
    pb = []
    npb = int(np.clip(passbys, 0, 3))
    slots = np.sort(rng.permutation(npb) + rng.uniform(0.15, 0.85, npb)) / max(npb, 1) if npb else []
    for i in range(npb):
        tc = pre / SR + float(slots[i]) * (n / SR)
        sp = rng.uniform(35, 60)
        cm = rng.uniform(40, 90)
        p = _far_passby(N, rng, tc, speed_kmh=sp, closest_m=cm, direction=int(rng.choice([-1, 1])),
                        lp_hz=(900.0 if fog else 1200.0))
        # nivel: en su paso más cercano la rodadura asoma +4..+7 dB sobre el lavado en 300 Hz-1.2 kHz
        i0, i1 = int((tc - 0.6) * SR), int((tc + 0.6) * SR)
        wb = _rms(dsp.bp(wash[max(0, i0):max(1, i1)], 300, 1200, 2))
        pbv = _rms(dsp.bp(p[max(0, i0):max(1, i1)], 300, 1200, 2))
        p *= wb / (pbv + 1e-12) * _db(rng.uniform(4, 7) - 3.0)
        y += 0.6 * p
        send += 0.9 * p
        pb.append({"t_closest": round(tc - pre / SR, 2), "speed_kmh": round(sp, 1), "closest_m": round(cm, 1)})
    hint = None
    if tonal > 0 and n / SR > 2.0 and rng.random() < min(1.0, 1.5 * tonal):
        t0 = pre / SR + rng.uniform(0.0, 0.6) * (n / SR)
        th, hint = _tonal_hint(N, rng, t0)
        th *= wr * _db(-19 + 10 * tonal) / (_rms(th[int(t0 * SR):]) + 1e-12)
        y += 0.25 * th
        send += 1.5 * th
    y = y + _space(send, ir, 0.0, -200)
    out = _finish(y, pre, n)
    return Render(out, 0, {"ir": ir, "passbys": pb, "tonal_hint": hint})


@recipe("amb.fog_air", family=FAM, sync="start", kind="bed")
def fog_air(dur, rng, *, brightness=0.5, motion=0.3, **_):
    """Aire de niebla: ruido 4-14 kHz pintado en STFT con 2-4 picos que derivan lento; muy ancho."""
    n = _n(dur)
    pre = int(0.3 * SR)
    N = n + pre
    k = int(rng.integers(2, 5))
    cen = np.sort(rng.uniform(np.log2(4800), np.log2(12500), k))
    wid = rng.uniform(0.12, 0.26, k)
    gdb = rng.uniform(4, 8, k)
    drift = [_mod(N, rng, 0.02, 0.1 + 0.4 * motion, 0.2 + 0.5 * motion) for _ in range(k)]
    side = [[_mod(N, rng, 0.03, 0.3, 0.05) for _ in range(k)] for _ in range(2)]
    pamp = [_gmod(N, rng, 0.05, 0.5, 3.0) for _ in range(k)]
    am = [_gmod(N, rng, 0.03, 0.2, 1.5) for _ in range(2)]
    top = 14000 * (0.8 + 0.4 * brightness)

    def g(t, f):
        F = f[:, None]
        base = _hpm(F, 4000, 3) * _lpm(F, top, 3)
        out = []
        for c in range(2):
            m = np.ones((len(f), len(t)))
            for i in range(k):
                fc = 2 ** (cen[i] + _frames(drift[i], t) + _frames(side[c][i], t))
                m += (_db(gdb[i]) - 1) * _frames(pamp[i], t)[None, :] * _bump(F, fc[None, :], wid[i])
            out.append(base * m * _frames(am[c], t)[None, :])
        return np.stack(out)

    y = _paint(N, rng, g, coh=0.22, slope=-4.0 + 4.0 * brightness)
    out = _finish(y, pre, n, hp_hz=120.0, fin=0.02)
    return Render(out, 0, {"peaks_hz": [round(float(2 ** c)) for c in cen]})


@recipe("amb.drips", family=FAM, sync="start", kind="bed")
def drips(dur, rng, *, rate=1.0, space="underpass_concrete", pitch=1.0, distance=0.5, **_):
    """Goteo esporádico (burbujas Minnaert), cada fuente con su pan/distancia, en el espacio dado."""
    n = _n(dur)
    pre = _pre(space, cap=1.5)
    N = n + pre
    direct, send, times = _drips_layer(N, rng, rate=rate, pitch=pitch, dist=distance, t_start=0.0, t_vis=pre / SR)
    y = direct + _space(send, space, 0.0, -200, hp_send=450.0)
    out = _finish(y, pre, n, hp_hz=150.0)
    tl = [round(t - pre / SR, 3) for t in times if t >= pre / SR]
    return Render(out, 0, {"drop_times_s": tl[:40], "space": space})


@recipe("amb.surf", family=FAM, sync="start", kind="bed")
def surf(dur, rng, *, intensity=0.7, crest_at=0.5, distance="far", crest_s=None, **_):
    """Mar: cama de rompiente (amplitud 1/f, LPF que respira 1.5-6 kHz) + una cresta en crest_at (corte
    300 Hz -> 5 kHz -> 1 kHz en ~3 s, barrida lateral) + espuma (crepitar HP 4-12 kHz que decae)."""
    far = dict(lpk=0.5, ir="valley_mountain", wet=-12.0, fizz=-6.0, thump=0.0, bed=0.0, crest=4.0)
    D = {"far": far,
         "mid": dict(lpk=0.8, ir="open_exterior", wet=-9.0, fizz=-2.0, thump=0.3, bed=-4.0, crest=8.0),
         "near": dict(lpk=1.0, ir="open_exterior", wet=-12.0, fizz=0.0, thump=1.0, bed=-7.0, crest=12.0)
         }.get(distance, far)
    n = _n(dur)
    pre = _pre(D["ir"], cap=1.5)
    N = n + pre
    tt = np.arange(N) / SR
    tc = pre / SR + float(np.clip(crest_at, 0, 1)) * n / SR
    cs = float(crest_s) if crest_s else float(np.clip(0.9 * dur, 1.2, 3.0))
    t_up, t_dn = cs / 3.0, 2.0 * cs / 3.0
    # ---- cama
    breath = _mod(N, rng, 0.04, 0.3, 1.0)
    fc_bed = 1500 * 4 ** (0.5 + 0.5 * breath) * D["lpk"]
    amp_bed = [_db(_mod(N, rng, 0.03, 0.4, 3.0) + 2.0 * breath) for _ in range(2)]

    def g_bed(t, f):
        F = f[:, None]
        fc = _frames(fc_bed, t)[None, :]
        return np.stack([_lpm(F, fc, 2) * _hpm(F, 120, 2) * _frames(amp_bed[c], t)[None, :] for c in range(2)])

    bed = _paint(N, rng, g_bed, coh=lambda f: _coh(f, 0.6, 0.15, 400.0), slope=-3.0)
    bed /= _rms(bed)
    # ---- cresta
    x = tt - tc
    env = np.where(x < 0, _smooth01(1 + x / t_up) ** 2, np.exp(-np.maximum(x, 0) / (0.45 * t_dn)))
    env *= (x > -t_up)
    fcc = np.where(x < 0, 300 * (5000 / 300) ** _smooth01(1 + x / t_up),
                   1000 + 4000 * np.exp(-np.maximum(x, 0) / (0.35 * t_dn))) * (0.6 + 0.4 * D["lpk"])
    pdir = rng.choice([-1, 1])
    pan_c = pdir * np.clip(x / (t_up + t_dn), -0.6, 0.6)
    gl, gr = dsp.pan_gains(pan_c)
    ce = [env * gl * 1.41, env * gr * 1.41]

    def g_cr(t, f):
        F = f[:, None]
        fc = _frames(fcc, t)[None, :]
        return np.stack([_lpm(F, fc, 2) * _hpm(F, 120, 2) * _frames(ce[c], t)[None, :] for c in range(2)])

    crest = _paint(N, rng, g_cr, coh=lambda f: _coh(f, 0.7, 0.3, 500.0), slope=-2.0)
    i0, i1 = int((tc - 0.3 * t_up) * SR), int((tc + 0.3 * t_dn) * SR)
    crest *= _db(D["bed"] + D["crest"] + 8.0 * (intensity - 0.7)) / (_rms(crest[max(0, i0):i1]) + 1e-12)
    # ---- golpe grave de la ola (sólo mid/near): cuerpo intencional >= 70 Hz
    thump = np.zeros((N, 2))
    if D["thump"] > 0:
        L = int(0.9 * SR)
        k = max(0, int(tc * SR) - int(0.03 * SR))
        th = dsp.lp(dsp.colored(L, rng, -6.0), 260, 2) * dsp.exp_decay(L, 0.22, 0.02)
        th = dsp.pan(th / (np.abs(th).max() + 1e-9), 0.0)
        dsp.mix_into(thump, th, k, 3.0 * _db(D["bed"] + D["crest"] - 6.0) * D["thump"] * intensity)
    # ---- espuma
    foam_e = np.where(x < 0, 0.15 + 0.35 * env, 0.15 + 0.85 * np.exp(-np.maximum(x, 0) / (0.5 * t_dn + 0.3)))
    rate = (2000 + 3000 * foam_e) * (0.6 + 0.5 * intensity)
    fz = np.stack([_crackle(N, rng, rate, 4000, 12000 * (0.7 + 0.3 * D["lpk"]), (0.05, 0.4)) for _ in range(2)], 1)
    fz *= foam_e[:, None]
    fz *= _db(-9 + D["fizz"]) / (_rms(fz) + 1e-12)
    y = _db(D["bed"]) * bed + crest + thump + fz
    y = _space(y, D["ir"], D["wet"], 0.0)
    out = _finish(y, pre, n, hp_hz=70.0 if D["thump"] > 0 else 120.0)
    return Render(out, 0, {"crest_t": round(tc - pre / SR, 3), "distance": distance, "crest_s": round(cs, 2)})


@recipe("amb.wind", family=FAM, sync="start", kind="bed")
def wind(dur, rng, *, strength=0.5, gustiness=0.5, whistle=0.3, texture="none", space="open_exterior",
         corr=0.6, **_):
    """Viento: cuerpo + silbidos eólicos + textura (none|grass|sand|snow|leaves)."""
    n = _n(dur)
    pre = _pre(space, cap=1.5)
    N = n + pre
    L = _wind_layers(N, rng, strength=strength, gustiness=gustiness, whistle=whistle, texture=texture, corr=corr)
    y = _wind_mix(L)
    y = _space(y, space, -12.0, 0.0)
    out = _finish(y, pre, n)
    return Render(out, 0, {"texture": texture, "layers": [k for k in L if k != "gusts"]})


@recipe("amb.mountain_wind", family=FAM, sync="start", kind="bed")
def mountain_wind(dur, rng, *, strength=0.6, river=0.3, echo=True, texture="grass", **_):
    """Viento patagónico abierto (ráfagas fuertes) + rugido lejano de laderas + río lejano + ecos de valle."""
    ir = "valley_mountain" if echo else "open_exterior"
    n = _n(dur)
    pre = _pre(ir)
    N = n + pre
    L = _wind_layers(N, rng, strength=strength, gustiness=0.8, whistle=0.35, texture=texture, corr=0.55,
                     body=(380.0, 1000.0), gust_hi=3.0, tex_db=2.0)
    y = _wind_mix(L)
    br = _rms(L["body"])

    def g_roar(t, f):
        F = f[:, None]
        return _hpm(F, 120, 2) * _lpm(F, 500, 2) * np.ones((1, len(t)))

    roar = _paint(N, rng, g_roar, coh=lambda f: _coh(f, 0.7, 0.3, 300.0), slope=-4.0)
    roar *= _gmod(N, rng, 0.02, 0.12, 3.0)[:, None]
    y += roar / _rms(roar) * br * _db(-6)
    send = y.copy()
    if river > 0:
        rv = _river(N, rng, far=True)
        rv *= br * _db(-14 + 12 * np.log10(max(river, 0.02) / 0.3))
        y += 0.6 * rv
        send += 1.2 * rv
    y = y + _space(send, ir, -7.0 if echo else -14.0, -200)
    out = _finish(y, pre, n)
    return Render(out, 0, {"ir": ir, "river": river})


@recipe("amb.forest", family=FAM, sync="start", kind="bed")
def forest(dur, rng, *, rustle=0.5, birds=1, wind=0.3, **_):
    """Bosque: hojas (granos HP con ráfagas + lavado de copas) + 0-3 pájaros lejanos + viento suave; IR forest."""
    n = _n(dur)
    pre = _pre("forest")
    N = n + pre
    L = _wind_layers(N, rng, strength=0.25 + 0.5 * wind, gustiness=0.45, whistle=0.0, texture="leaves", corr=0.5,
                     body=(300.0, 700.0), tex_db=6.0 * (rustle - 0.5), grain_db=8.0 * (rustle - 0.5),
                     gate_floor=0.35)
    br = _rms(L["body"])
    y = _db(-4) * L["body"] + L["texture"] + L["grains"]
    times = _natural_times(rng, int(np.clip(birds, 0, 3)), pre / SR + 0.1, (N / SR) - 0.4, 0.5)
    bd, bs = _bird_track(N, rng, times, species="generic", dist=(30.0, 110.0), lp_ref=4500.0)
    bscale = br * _db(-4) / (np.abs(bd).max() / 4.0 + 1e-12) if bd.any() else 0.0
    y = _space(y, "forest", -10.0, 0.0)  # cama con su espacio
    y = y + bscale * (bd + _space(bs, "forest", -3.0, -200))
    out = _finish(y, pre, n)
    return Render(out, 0, {"bird_times_s": [round(t - pre / SR, 2) for t in times]})


@recipe("amb.lake", family=FAM, sync="start", kind="bed")
def lake(dur, rng, *, lap=0.5, wind=0.2, **_):
    """Orilla de lago: chapoteo grave burbujeante a ritmo irregular + brillo de ondas + brisa."""
    n = _n(dur)
    pre = _pre("open_exterior")
    N = n + pre
    laps, times = _lapping(N, rng, lap=lap, t_vis=pre / SR)
    lr = _rms(laps)

    def g_sh(t, f):
        F = f[:, None]
        return _hpm(F, 400, 2) * _lpm(F, 1600, 2) * np.ones((1, len(t)))

    shim = _paint(N, rng, g_sh, coh=0.3, slope=-3.0)
    shim *= np.stack([_gmod(N, rng, 0.5, 6.0, 4.0) for _ in range(2)], 1)
    Lw = _wind_layers(N, rng, strength=0.2 + 0.5 * wind, gustiness=0.4, whistle=0.0, texture="grass", corr=0.5,
                      body=(350.0, 700.0))
    br = _wind_mix(Lw, body_db=-3.0)
    y = laps + shim / _rms(shim) * lr * _db(-13) + br / _rms(br) * lr * _db(-9 + 14 * np.log10(max(wind, 0.02) / 0.2))
    y = _space(y, "open_exterior", -7.0, 0.0)
    out = _finish(y, pre, n)
    return Render(out, 0, {"lap_times_s": [round(t - pre / SR, 2) for t in times if t >= pre / SR]})


@recipe("amb.desert_wind", family=FAM, sync="start", kind="bed")
def desert_wind(dur, rng, *, strength=0.5, sand=0.5, **_):
    """Viento seco de desierto: cuerpo oscuro + pocos silbidos de roca + arena (saltación granular 3-10 kHz)."""
    n = _n(dur)
    pre = _pre("open_exterior")
    N = n + pre
    L = _wind_layers(N, rng, strength=strength, gustiness=0.6, whistle=0.12, texture="sand", corr=0.5,
                     body=(350.0, 750.0), n_whistles=2, sand=sand, tex_db=4.0 * (sand - 0.5))
    y = _wind_mix(L)
    y = _space(y, "open_exterior", -16.0, 0.0)
    out = _finish(y, pre, n)
    return Render(out, 0, {"sand": sand})


@recipe("amb.alpine", family=FAM, sync="start", kind="bed")
def alpine(dur, rng, *, strength=0.5, **_):
    """Montaña nevada: viento frío, ralo y alto (casi sin graves), silbidos finos, nieve silenciosa."""
    n = _n(dur)
    pre = _pre("valley_mountain")
    N = n + pre
    L = _wind_layers(N, rng, strength=strength, gustiness=0.9, whistle=0.35, texture="snow", corr=0.5,
                     body=(700.0, 1600.0), whistle_band=(900.0, 2000.0), hp_hz=350.0, n_whistles=2, tex_db=4.0)
    y = _wind_mix(L, body_db=-2.0)
    # silencio de nieve: piso de aire finísimo para que las calmas no sean digitales
    def g(t, f):
        F = f[:, None]
        return _hpm(F, 5000, 2) * _lpm(F, 12000, 2) * np.ones((1, len(t)))
    fl = _paint(N, rng, g, coh=0.2, slope=-2.0)
    y += fl / _rms(fl) * _rms(L["body"]) * _db(-30)
    y = _space(y, "valley_mountain", -17.0, 0.0, hp_send=400.0)
    out = _finish(y, pre, n, hp_hz=300.0)
    return Render(out, 0, {})


@recipe("amb.cabin", family=FAM, sync="start", kind="bed")
def cabin(dur, rng, *, speed_kmh=60.0, road=0.5, hvac=0.3, pillar_wind=0.3, **_):
    """Cabina EV en marcha (muy silenciosa): rumble de ruta 120-500 Hz, rodadura a través del vidrio,
    HVAC 1-5 kHz y viento de pilar A 500 Hz-3 kHz (nivel ~ 60 log v, centroide sube con v)."""
    n = _n(dur)
    pre = _pre("cabin_small")
    N = n + pre
    v = max(5.0, float(speed_kmh))
    tire_db = 30 * np.log10(v / 60.0)
    aero_db = 60 * np.log10(v / 60.0)
    # rumble de ruta: centro y nivel caminan con el pavimento
    cen = 220 * (1 + _mod(N, rng, 0.1, 1.5, 0.15))
    cav = _note("Bb3") * (0.98 + 0.03 * min(v, 130) / 130) * (1 + _mod(N, rng, 0.05, 0.5, 0.01))  # cavidad neumático
    surf_amp = [_db(_mod(N, rng, 0.2, 1.5, 2.0) + _mod(N, rng, 4.0, 20.0, 0.8)) for _ in range(2)]

    def g_road(t, f):
        F = f[:, None]
        c = _frames(cen, t)[None, :]
        m = _hpm(F, 120, 2) * _lpm(F, 500, 2) * (1 + 1.2 * _bump(F, c, 0.6)) * \
            (1 + 0.6 * _bump(F, _frames(cav, t)[None, :], 0.08))
        return np.stack([m * _frames(surf_amp[ch], t)[None, :] for ch in range(2)])

    rd = _paint(N, rng, g_road, coh=lambda f: _coh(f, 0.85, 0.5, 300.0), slope=-4.0)
    rd /= _rms(rd)
    # rodadura (exterior) a través del vidrio
    def g_tire(t, f):
        F = f[:, None]
        return _hpm(F, 400, 2) * _lpm(F, 1800, 2) * np.ones((1, len(t)))

    tr = _paint(N, rng, g_tire, coh=0.4, slope=-2.0)
    tr *= _gmod(N, rng, 0.2, 2.0, 1.5)[:, None]
    tr = dsp.through_glass(tr)
    tr /= _rms(tr)
    hv = _hvac(N, rng)
    hv /= _rms(hv)
    # viento de pilar A (dos lados, independientes)
    pc = 1100 * (v / 60.0) ** 0.5
    pg = [_gmod(N, rng, 0.3, 3.0, 2.5) for _ in range(2)]

    def g_pil(t, f):
        F = f[:, None]
        m = _hpm(F, 500, 2) * _lpm(F, 3000, 2) * (1 + 1.0 * _bump(F, pc, 0.7))
        return np.stack([m * _frames(pg[c], t)[None, :] for c in range(2)])

    pw = _paint(N, rng, g_pil, coh=0.15, slope=-2.0)
    pw /= _rms(pw)
    y = (rd * _db(20 * np.log10(max(road, 0.02) / 0.5) + tire_db)
         + tr * _db(-6 + tire_db + 20 * np.log10(max(road, 0.02) / 0.5))
         + hv * _db(-14 + 20 * np.log10(max(hvac, 0.01) / 0.3))
         + pw * _db(-15 + aero_db + 20 * np.log10(max(pillar_wind, 0.01) / 0.3)))
    y = _space(y, "cabin_small", -8.0, 0.0)
    out = _finish(y, pre, n)
    return Render(out, 0, {"speed_kmh": v, "tire_db": round(tire_db, 1), "aero_db": round(aero_db, 1)})


@recipe("amb.cabin_still", family=FAM, sync="start", kind="bed")
def cabin_still(dur, rng, *, hvac=0.3, exterior="city_fog", **_):
    """Cabina detenida: HVAC + tono de cabina + exterior (city_fog|city_day|wind|forest|none) a través del vidrio."""
    n = _n(dur)
    pre = _pre("cabin_small", "city_fog_street")
    N = n + pre
    hv = _hvac(N, rng)
    hv /= _rms(hv)
    room = _room_core(N, rng, _ROOM["cabin"], air_db=-30.0, rumble_db=-10.0)
    room /= _rms(room)
    if exterior in ("city_fog", "city_day"):
        fog = exterior == "city_fog"
        ex = _traffic_wash(N, rng, lp_hz=700.0, density=0.5, fog=fog)
        ex = _space(ex, "city_fog_street" if fog else "city_day_street", -4.0, 0.0)
    elif exterior == "wind":
        ex = _wind_mix(_wind_layers(N, rng, strength=0.5, gustiness=0.6, whistle=0.2))
    elif exterior == "forest":
        Lw = _wind_layers(N, rng, strength=0.4, gustiness=0.6, whistle=0.0, texture="leaves")
        ex = Lw["body"] + Lw["texture"] + Lw["grains"]
    else:
        ex = np.zeros((N, 2))
    if ex.any():
        ex = dsp.through_glass(ex)
        ex /= _rms(ex)
    y = hv * _db(-6 + 20 * np.log10(max(hvac, 0.01) / 0.3)) + room * _db(-4) + ex * _db(-2)
    y = _space(y, "cabin_small", -8.0, 0.0)
    out = _finish(y, pre, n)
    return Render(out, 0, {"exterior": exterior})


@recipe("amb.tunnel", family=FAM, sync="start", kind="bed")
def tunnel(dur, rng, *, fans=0.5, drip=0.2, note="F3", **_):
    """Túnel: dron de ventiladores 120-400 Hz con tono de paso de aspas (F3, dos ventiladores que baten),
    aire de ventilación, goteo lejano, IR de túnel (larga, flutter)."""
    n = _n(dur)
    pre = _pre("tunnel")
    N = n + pre
    broad, tone = _fan_drone(N, rng, note=note)
    fg = 20 * np.log10(max(fans, 0.02) / 0.5)
    y = broad * _db(fg) + tone * _db(-5 + fg)

    def g_air(t, f):
        F = f[:, None]
        return _hpm(F, 1500, 2) * _lpm(F, 7000, 2) * np.ones((1, len(t)))

    air = _paint(N, rng, g_air, coh=0.2, slope=-3.0)
    air *= np.stack([_gmod(N, rng, 0.05, 0.5, 2.0) for _ in range(2)], 1)
    y += air / _rms(air) * _db(-20)
    send = y.copy()
    times = []
    if drip > 0:
        d, s, times = _drips_layer(N, rng, rate=2.5 * drip, pitch=0.9, dist=0.85, t_vis=pre / SR)
        dscale = _db(-4 + 20 * np.log10(max(drip, 0.02) / 0.2)) / (np.abs(d).max() / 4.0 + 1e-12) * 0.25
        y += d * dscale
        send += dsp.hp(s, 450.0, 2) * dscale
    y = 0.5 * y + _space(send, "tunnel", -2.0, -200)
    out = _finish(y, pre, n)
    return Render(out, 0, {"blade_note": note, "drop_times_s": [round(t - pre / SR, 2) for t in times if t >= pre / SR]})


@recipe("amb.studio", family=FAM, sync="start", kind="bed")
def studio(dur, rng, *, hum=0.3, hum_note="Ab2", **_):
    """Escenario grande vacío: aire del recinto + HVAC lejano + zumbido de lámparas muy bajo (Ab2 ~ 104 Hz,
    afinado a la tonalidad; armónicos 1-2-3-4-6 = Ab/Eb; LPF 800 Hz)."""
    n = _n(dur)
    pre = _pre("studio_stage")
    N = n + pre
    y = _room_core(N, rng, _ROOM["studio"], air_db=-15.0, rumble_db=-12.0, motion=0.7)
    br = _rms(y)
    f0 = _note(hum_note)
    fcur = f0 * (1 + _mod(N, rng, 0.05, 0.5, 0.0005))
    ph = dsp.phase_from_freq(fcur, N, rng.uniform(0, 6.28))
    h = np.zeros(N)
    for k, a in [(1, 1.0), (2, 0.7), (3, 0.35), (4, 0.3), (6, 0.12), (8, 0.05)]:
        h += a * np.sin(k * ph + rng.uniform(0, 6.28)) * _gmod(N, rng, 0.1, 1.0, 1.0)
    h = dsp.lp(h, 800, 2)
    h *= _gmod(N, rng, 0.05, 0.4, 1.0)
    hst = dsp.pan(h, rng.uniform(-0.3, 0.3))
    hst = hst / _rms(hst) * br * _db(-23 + 20 * np.log10(max(hum, 0.01) / 0.3))
    y = _space(y, "studio_stage", -2.0, -8.0) + _space(hst, "studio_stage", -6.0, 0.0)
    out = _finish(y, pre, n, hp_hz=90.0)
    return Render(out, 0, {"hum_hz": round(f0, 2)})


@recipe("amb.empty_city_day", family=FAM, sync="start", kind="bed")
def empty_city_day(dur, rng, *, traffic=0.3, birds=2, wind=0.2, **_):
    """Calle vacía de día (remate expuesto): tráfico muy lejano (LPF 500 Hz), brisa suave en árboles,
    2-3 gorriones espaciados con naturalidad, espacio city_day_street."""
    n = _n(dur)
    ir = "city_day_street"
    pre = _pre(ir)
    N = n + pre
    wash = _traffic_wash(N, rng, lp_hz=500.0, density=0.35, fog=False)
    wash /= _rms(wash)
    Lw = _wind_layers(N, rng, strength=0.2 + 0.4 * wind, gustiness=0.4, whistle=0.0, texture="leaves", corr=0.5,
                      body=(300.0, 650.0), grain_db=-6.0, gate_floor=0.35, leaf_att=(1.5, 5.0), leaf_crackle=0.0)
    br = Lw["body"] * _db(-6) + Lw["texture"] + Lw["grains"]
    br /= _rms(br)

    def g_air(t, f):
        F = f[:, None]
        return _hpm(F, 2500, 2) * _lpm(F, 13000, 2) * np.ones((1, len(t)))

    air = _paint(N, rng, g_air, coh=0.2, slope=-2.0)
    air *= np.stack([_gmod(N, rng, 0.05, 0.4, 1.5) for _ in range(2)], 1)
    air /= _rms(air)
    y = (wash * _db(20 * np.log10(max(traffic, 0.02) / 0.3)) + br * _db(-4 + 20 * np.log10(max(wind, 0.02) / 0.2))
         + air * _db(-21))
    send = 0.6 * y
    # pasada EV muy lejana, apenas un swell
    if n / SR > 1.2 and traffic > 0.1:
        tc = pre / SR + rng.uniform(0.3, 1.2) * n / SR
        p = _far_passby(N, rng, tc, speed_kmh=rng.uniform(35, 50), closest_m=rng.uniform(70, 140),
                        direction=int(rng.choice([-1, 1])), lp_hz=1100.0)
        p /= (np.abs(p).max() / 3.0 + 1e-12)
        y += p * _db(-9)
        send += p * _db(-6)
    # gorriones: birds=2 -> 2-3 chirps
    k = int(np.clip(birds, 0, 4))
    if k:
        k = k + int(rng.random() < 0.5) if k < 4 else k
    t0 = pre / SR + rng.uniform(0.15, 0.45)
    tb = _sparrow_bouts(rng, k, t0, (N / SR) - 0.2)
    times = [t for t, _ in tb]
    bd, bs = _bird_track(N, rng, times, species="sparrow", dist=(14.0, 35.0), lp_ref=4500.0,
                         birds=[b for _, b in tb])
    if bd.any():
        sc = _db(-5) / (np.abs(bd).max() / 5.0 + 1e-12) * _rms(y)
        y += bd * sc
        send += bs * sc * _db(-4)
    y = y + _space(send, ir, -4.0, -200)
    out = _finish(y, pre, n)
    return Render(out, 0, {"chirp_times_s": [round(t - pre / SR, 3) for t in times]})


@recipe("amb.birds_distant", family=FAM, sync="start", kind="event")
def birds_distant(dur, rng, *, count=2, species="generic", space=None, distance=1.0, **_):
    """1-4 pájaros lejanos (FM 3-7 kHz, 50-150 ms, LPF ~4 kHz) con eco de valle/bosque.
    species: generic|sparrow|raptor (rapaz = grito descendente áspero, muy lejos). sync = inicio.
    count = número exacto de llamadas (rapaz: un grito por llamada). Las llamadas terminan dentro de `dur`
    (el grito de rapaz se acorta a lo disponible; lo que cruce `dur` se desvanece en 80 ms); sólo el eco del
    valle / la reverb exceden `dur` (hasta ~1.6-2.2 s)."""
    n = _n(dur)
    sp = species if species in ("generic", "sparrow", "raptor", "mixed") else "generic"
    ir = space or {"raptor": "valley_mountain", "sparrow": "city_day_street"}.get(sp, "valley_mountain")
    k = int(np.clip(count, 1, 4))
    dist = {"raptor": (250.0, 600.0), "sparrow": (15.0, 45.0)}.get(sp, (40.0, 150.0))
    dist = (dist[0] * distance, dist[1] * distance)
    first = rng.uniform(0.01, 0.04)
    if sp == "sparrow":
        tb = _sparrow_bouts(rng, k, first, max(first + 0.4, 0.85 * dur))
        times, who = [t for t, _ in tb], [b for _, b in tb]
    else:
        times = [first] + _natural_times(rng, k - 1, first + 0.35, max(first + 0.4, 0.85 * dur), 0.3)
        who = None
    bd, bs = _bird_track(n, rng, times, species=sp, dist=dist, lp_ref=(3200.0 if sp == "raptor" else 4000.0),
                         birds=who, fit=True)
    if ir == "none":
        wet = np.zeros((n, 2))
    elif ir == "valley_mountain":
        if sp == "raptor":  # rapaz a 250-600 m: ecos oscuros (absorción) y cola difusa baja (no "silbido")
            wet = _valley_echo(bs, rng, tail_db=-12.0, lp_hz=2500.0, tail_lp=2500.0)
        else:
            wet = _valley_echo(bs, rng, tail_db=-10.0)
    else:
        wet = dsp.convolve(bs, dsp.ir_preset(ir), wet=float(_db(-7.0)))
        wet = _bass_width(wet, 1500.0, 0.7)
    y = np.zeros((len(wet), 2))
    y[:n] += bd
    y += wet
    if sp == "raptor":
        y = dsp.lp(y, 3500, 2)
    out = _finish_event(y, hp_hz=300.0, fin=0.003, fout=0.2)
    # sync = primer contacto (inicio de la primera llamada; los 10-40 ms previos quedan antes de `at`)
    return Render(out, int(round(times[0] * SR)), {"call_times_s": [round(t, 3) for t in times], "space": ir})


# ====================================================================== auditions

AUDITIONS = [
    # (receta, dur, params, at (timeline s) o None, gain_db, tag[, seed])
    ("amb.room_tone", 1.6, {"space": "underpass"}, 0.0, -14, "room_tone_underpass"),
    ("amb.room_tone", 1.6, {"space": "underpass"}, 0.0, -14, "room_tone_underpass_s1", 1),
    ("amb.room_tone", 2.0, {"space": "studio"}, 23.63, -16, "room_tone_studio"),
    ("amb.room_tone", 2.0, {"space": "city_fog"}, 5.0, -16, "room_tone_city_fog"),
    ("amb.room_tone", 2.0, {"space": "cabin"}, None, None, "room_tone_cabin"),
    ("amb.room_tone", 2.0, {"space": "tunnel"}, None, None, "room_tone_tunnel"),
    ("amb.city_distant", 7.0, {"density": 0.5, "lp_hz": 600, "passbys": 1, "fog": True}, 5.0, -18, "city_distant_fog"),
    ("amb.city_distant", 7.0, {"density": 0.5, "lp_hz": 600, "passbys": 2, "fog": True, "tonal": 0.5}, None, None,
     "city_distant_fog_s3", 3),
    ("amb.fog_air", 7.0, {"brightness": 0.5, "motion": 0.3}, 5.0, -18, "fog_air"),
    ("amb.fog_air", 7.0, {"brightness": 0.7, "motion": 0.5}, None, None, "fog_air_s1", 1),
    ("amb.drips", 4.0, {"rate": 1.0, "space": "underpass_concrete"}, 0.0, -16, "drips_underpass"),
    ("amb.drips", 6.0, {"rate": 1.0, "space": "underpass_concrete"}, None, None, "drips_underpass_s1", 1),
    ("amb.surf", 2.5, {"intensity": 0.7, "crest_at": 0.3, "distance": "far"}, 14.4, -12, "surf_far"),
    ("amb.surf", 2.5, {"intensity": 0.7, "crest_at": 0.3, "distance": "far"}, None, None, "surf_far_s1", 1),
    ("amb.surf", 5.0, {"intensity": 0.8, "crest_at": 0.35, "distance": "near"}, None, None, "surf_near"),
    ("amb.wind", 8.0, {"strength": 0.5, "gustiness": 0.5, "whistle": 0.3, "texture": "none"}, None, None, "wind_none"),
    ("amb.wind", 6.0, {"strength": 0.6, "texture": "grass"}, None, None, "wind_grass"),
    ("amb.wind", 4.0, {"strength": 0.5, "texture": "leaves"}, None, None, "wind_leaves"),
    ("amb.wind", 4.0, {"strength": 0.5, "texture": "snow"}, None, None, "wind_snow"),
    ("amb.mountain_wind", 1.6, {"strength": 0.6, "river": 0.3, "echo": True}, 18.1, -14, "mountain_wind_valley"),
    ("amb.mountain_wind", 3.0, {"strength": 0.7, "river": 0.2, "echo": True}, 39.92, -14, "mountain_wind_torres"),
    ("amb.mountain_wind", 3.0, {"strength": 0.7, "river": 0.2, "echo": True}, None, None, "mountain_wind_torres_s1", 1),
    ("amb.forest", 1.6, {"rustle": 0.5, "birds": 1, "wind": 0.3}, 28.0, -14, "forest_aerial"),
    ("amb.forest", 2.6, {"rustle": 0.6, "birds": 2, "wind": 0.3}, 31.5, -14, "forest_low"),
    ("amb.forest", 2.6, {"rustle": 0.6, "birds": 2, "wind": 0.3}, None, None, "forest_low_s1", 1),
    ("amb.lake", 1.6, {"lap": 0.5, "wind": 0.2}, 30.0, -12, "lake"),
    ("amb.lake", 6.0, {"lap": 0.5, "wind": 0.2}, None, None, "lake_long_s1", 1),
    ("amb.desert_wind", 1.4, {"strength": 0.5, "sand": 0.5}, 25.3, -12, "desert_wind"),
    ("amb.desert_wind", 6.0, {"strength": 0.6, "sand": 0.6}, None, None, "desert_wind_long_s1", 1),
    ("amb.alpine", 1.2, {"strength": 0.5}, 36.2, -14, "alpine"),
    ("amb.alpine", 6.0, {"strength": 0.5}, None, None, "alpine_long_s1", 1),
    ("amb.cabin", 3.4, {"speed_kmh": 60}, 19.2, -16, "cabin_60"),
    ("amb.cabin", 1.6, {"speed_kmh": 80}, 38.5, -16, "cabin_80_ex5"),
    ("amb.cabin", 3.0, {"speed_kmh": 110, "pillar_wind": 0.4}, None, None, "cabin_110"),
    ("amb.cabin_still", 3.0, {"hvac": 0.3, "exterior": "city_fog"}, None, None, "cabin_still"),
    ("amb.tunnel", 1.8, {"fans": 0.5, "drip": 0.2}, 42.4, -14, "tunnel"),
    ("amb.tunnel", 6.0, {"fans": 0.5, "drip": 0.3}, None, None, "tunnel_long_s1", 1),
    ("amb.studio", 1.8, {"hum": 0.3}, 23.5, -16, "studio"),
    ("amb.empty_city_day", 1.9, {"traffic": 0.3, "birds": 2, "wind": 0.2}, 46.75, -10, "empty_city_day"),
    ("amb.empty_city_day", 1.9, {"traffic": 0.3, "birds": 2, "wind": 0.2}, 46.75, -10, "empty_city_day_s1", 1),
    ("amb.empty_city_day", 1.9, {"traffic": 0.3, "birds": 2, "wind": 0.2}, 46.75, -10, "empty_city_day_s2", 2),
    ("amb.birds_distant", 3.0, {"count": 2, "species": "generic"}, None, None, "birds_generic"),
    ("amb.birds_distant", 3.0, {"count": 2, "species": "generic", "space": "forest"}, None, None, "birds_generic_forest",
     1),
    ("amb.birds_distant", 3.0, {"count": 1, "species": "raptor"}, 40.0, -10, "birds_raptor"),
    ("amb.birds_distant", 2.0, {"count": 3, "species": "sparrow", "space": "city_day_street"}, 46.9, -8,
     "birds_sparrow"),
]


def _run_auditions(only=None):
    from ..audition import audition
    for item in AUDITIONS:
        name, dur, params, at, gain, tag = item[:6]
        seed = item[6] if len(item) > 6 else 0
        if only and not any(o in tag or o == name for o in only):
            continue
        met = audition(name, dur, params, seed=seed, at=at, gain=gain, tag=tag)
        ctx = met.get("context", {}).get("sfx_vs_bed_db_by_band", {})
        print(f"{tag:28s} peak {met['peak_dbfs']:6.1f} rms {met['rms_dbfs']:6.1f} corr {met.get('lr_corr')} "
              f"cent {met['centroid_hz']:6.0f} clicks {met['click_candidates']:3d} "
              f"ac {met.get('max_autocorr_0.1-5s')} dc {met['dc_db']}"
              + (f"\n{'':28s} ctx {ctx}" if ctx else ""), flush=True)


if __name__ == "__main__":
    # python -m sfx.recipes.ambience [filtro ...]  -> regenera out/audition/ambience/
    # Como script este módulo se carga como __main__: se retiran sus registros y se usa el del paquete
    # (audition() importa sfx.recipes.* y si no, el registro se duplicaría).
    import importlib
    import sys

    from ..core import RECIPES

    for _k in [k for k, v in RECIPES.items() if v["fn"].__module__ == "__main__"]:
        del RECIPES[_k]
    importlib.import_module("sfx.recipes.ambience")._run_auditions(sys.argv[1:] or None)
