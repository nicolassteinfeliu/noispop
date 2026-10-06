"""Familia VEHICLE: EV Geely (EX2 / EX5) -- rodado, pass-bys, aproximaciones, motor eléctrico, salpicaduras.

Todo es síntesis procedural (numpy/scipy), sin samples. Modelos con base física:

  * tire_roll(v):  ruido rosa pintado en STFT. Asfalto seco: pico 700-1300 Hz que sube con v,
    nivel ~ 30*log10(v); banda de tread hum (Q~5) en f = v / 0.03 m con aleatorización de pitch +-10 %;
    AM de rotación a v / (2*pi*0.33 m) (1-2 dB, no periódica). Mojado: siseo HP 2.5-10 kHz +
    micro-burbujas de Minnaert Poisson 2-6 k/s + swish de desplazamiento de agua 200-600 Hz.
    Grava: granos (senos amortiguados 1.5-6 kHz, tau 2-6 ms, 300-1500/s ~ v) + crunches BP 300-900 Hz.
    Nieve: LPF 2.5 kHz + granos de compactación 0.5-3 kHz + chirridos stick-slip ocasionales.
    Perspectiva: far (LPF 3 kHz) | onboard (foco 120-600 Hz) | interior (through_glass + rumble 120-500) | close.
  * ev_drive(v):  órdenes de motor 8/16/24/48 x f_rotor (f_rotor 0-150 Hz ~ v) a -20..-40 dB con jitter,
    silbido de inversor (portadora Bb8 = 7459 Hz, bandas laterales +-2 f_elec, ~-45 dB), AVAS < 20 km/h
    (3 parciales armónicos sobre Eb4 0/-8/-14 dB que suben con v). Opcionalmente se "afina" la relación
    de reducción para que el orden 8 caiga en una nota segura (Bb Db Eb Ab, cuyas quintas también son seguras).
  * aero(v):  rosa pasabanda con centroide ~ 300 + 15 v[m/s] Hz, nivel ~ 60*log10(v), ráfagas 0.1-0.5 Hz.

Propagación: dsp.passby (Doppler, reflejo de suelo, absorción del aire, pan/ITD) para pasos rectos, y un
propagador propio (_propagate) para trayectorias arbitrarias (aproximación frontal, curva de grava).
Espacio con dsp.reverb / dsp.ir_preset. Toda la aleatoriedad sale del rng recibido.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .. import dsp
from ..core import SR, Render, recipe

C_SOUND = 343.0
V_REF = 50.0 / 3.6          # velocidad de referencia (nivel 1.0 del rodado)
R_TIRE = 0.33               # radio de rueda (m)
TWO_PI = 2.0 * np.pi
SURFACES = ("dry", "wet", "gravel", "snow")
PERSPECTIVES = ("close", "far", "onboard", "interior")
_GROUND = {"dry": 0.42, "wet": 0.62, "gravel": 0.3, "snow": 0.15}

_PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7,
       "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
_SAFE_PCS = (10, 1, 3, 5, 8)        # Bb Db Eb F Ab
_ROOT_PCS = (10, 1, 3, 8)           # raíces cuya 3a armónica (quinta) también es segura


# =====================================================================================================
# utilidades privadas
# =====================================================================================================

def _note_hz(name: str) -> float:
    name = str(name).strip()
    i = 2 if len(name) > 2 and name[1] in "b#" else 1
    pc = _PC[name[:i]]
    octv = int(name[i:])
    return 440.0 * 2 ** ((12 * (octv + 1) + pc - 69) / 12)


def _snap(f: float, pcs=_SAFE_PCS) -> float:
    """Frecuencia -> nota segura más cercana."""
    m = 69 + 12 * np.log2(max(f, 1e-3) / 440.0)
    cands = [k for k in range(int(np.floor(m)) - 6, int(np.ceil(m)) + 7) if k % 12 in pcs]
    k = min(cands, key=lambda c: abs(c - m))
    return 440.0 * 2 ** ((k - 69) / 12)


def _ss(x, a, b):
    """Smoothstep 0->1 entre a y b."""
    u = np.clip((np.asarray(x, np.float64) - a) / (b - a + 1e-12), 0.0, 1.0)
    return u * u * (3 - 2 * u)


def _mod(t, rng, rate=0.3, depth=1.0, octaves=3, decay=0.7):
    """Modulador ~1/f acotado en [-depth, depth]: suma de octavas de nudos aleatorios con interpolación
    coseno (fase aleatoria). t: array de tiempos (s). Vectorizado (rápido a tasa de audio)."""
    t = np.asarray(t, np.float64)
    if t.size == 0:
        return t
    if t.size > 8192:   # a tasa de audio: evaluar en grilla de control (~1.5 kHz) e interpolar
        tc = np.linspace(t[0], t[-1], t.size // 32 + 2)
        return np.interp(t, tc, _mod(tc, rng, rate, depth, octaves, decay))
    t0 = float(t.min())
    span = float(t.max()) - t0
    y = np.zeros_like(t)
    for o in range(octaves):
        r = rate * 2 ** o
        step = 0.5 / r
        k = int(span / step) + 4
        vals = rng.uniform(-1, 1, k)
        u = (t - t0) / step + rng.uniform(0, 1)
        i = np.floor(u).astype(np.int64)
        fr = u - i
        w = 0.5 - 0.5 * np.cos(np.pi * fr)
        y += decay ** o * (vals[i] * (1 - w) + vals[i + 1] * w)
    return y / (np.abs(y).max() + 1e-12) * depth


def _bl_noise(n: int, rng, bw: float) -> np.ndarray:
    """Ruido gaussiano de banda limitada (~bw Hz), std 1 (nudos a 4*bw con interpolación coseno)."""
    fs_c = max(4.0 * bw, 0.5)
    k = int(n / SR * fs_c) + 4
    w = rng.standard_normal(k)
    u = np.arange(n) / SR * fs_c + rng.uniform(0, 1)
    i = u.astype(np.int64)
    s = 0.5 - 0.5 * np.cos(np.pi * (u - i))
    y = w[i] * (1 - s) + w[i + 1] * s
    return (y - y.mean()) / (y.std() + 1e-12)


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)


def _bump(lf, f0, w_oct):
    """Campana gaussiana en log2-frecuencia (potencia)."""
    return np.exp(-0.5 * ((lf - np.log2(f0)) / w_oct) ** 2)


def _sig(F, f0, w_oct=0.5):
    """Escalón suave en log-frecuencia (0 debajo de f0, 1 encima)."""
    return 1.0 / (1.0 + np.exp(-4.0 * np.log2(F / f0) / w_oct))


def _paint(n: int, rng, mag_fn, nperseg: int = 2048, corr=None) -> np.ndarray:
    """Ruido blanco modelado en STFT SIN normalizar: con G=1 la salida es ruido blanco RMS 1, así que la
    potencia de salida por frame ~ mean_f(G^2). corr != None -> estéreo [n, 2] con esa correlación."""
    hop = nperseg // 4
    if corr is None:
        x = rng.standard_normal(n + nperseg)
    else:
        k, j = np.sqrt(max(0.0, corr)), np.sqrt(max(0.0, 1 - corr))
        a = rng.standard_normal(n + nperseg)
        x = np.stack([k * a + j * rng.standard_normal(n + nperseg), k * a + j * rng.standard_normal(n + nperseg)])
    f, t, Z = signal.stft(x, SR, nperseg=nperseg, noverlap=nperseg - hop)
    G = np.asarray(mag_fn(t, f), np.float64)
    _, y = signal.istft(Z * G, SR, nperseg=nperseg, noverlap=nperseg - hop)
    y = y[..., :n]
    if y.shape[-1] < n:
        y = np.concatenate([y, np.zeros(y.shape[:-1] + (n - y.shape[-1],))], axis=-1)
    return y if corr is None else y.T


def _poisson_pos(rate, rng, n: int) -> np.ndarray:
    """Posiciones (samples) de un proceso de Poisson inhomogéneo con tasa rate[n] (eventos/s)."""
    r = np.maximum(dsp.as_curve(rate, n), 0.0)
    cum = np.cumsum(r) / SR
    tot = float(cum[-1])
    if tot <= 0:
        return np.zeros(0, np.int64)
    k = rng.poisson(tot)
    u = np.sort(rng.uniform(0, tot, k))
    return np.clip(np.searchsorted(cum, u), 0, n - 1).astype(np.int64)


def _grains(n: int, pos, f, tau, amp, rng, pan=None, glide=0.0, attack=2.5e-4, max_len=0.25):
    """Granos = senos amortiguados, cada uno con su frecuencia/tau/amplitud/fase propias (re-sintetizados,
    nada copiado). glide > 0 => chirp ascendente tipo burbuja de Minnaert. pan (array) => estéreo.
    Vectorizado por bloques + bincount."""
    pos = np.asarray(pos, np.int64)
    k = len(pos)
    stereo_out = pan is not None
    out = np.zeros((n, 2)) if stereo_out else np.zeros(n)
    if k == 0:
        return out
    f = np.broadcast_to(np.asarray(f, np.float64), (k,)).copy()
    tau = np.broadcast_to(np.asarray(tau, np.float64), (k,)).copy()
    amp = np.broadcast_to(np.asarray(amp, np.float64), (k,)).copy()
    gl_all = np.broadcast_to(np.asarray(glide, np.float64), (k,)).copy()
    phi = rng.uniform(0, TWO_PI, k)
    if stereo_out:
        pl, pr = dsp.pan_gains(np.broadcast_to(np.asarray(pan, np.float64), (k,)))
    order = np.argsort(tau)
    f32 = np.float32
    i = 0
    while i < k:
        L = int(min(4.0 * tau[order[min(k - 1, i)]], max_len) * SR) + 2
        chunk = max(8, int(1.5e6 // max(L, 1)))
        sel = order[i:i + chunk]
        L = int(min(4.0 * tau[sel].max(), max_len) * SR) + 2       # 4 tau = -35 dB
        T = (np.arange(L, dtype=f32) / f32(SR))[None, :]
        tk = tau[sel].astype(f32)[:, None]
        env = (f32(1.0) - np.exp(-T / f32(attack))) * np.exp(-T / tk)
        g = gl_all[sel].astype(f32)[:, None]
        if np.any(g):
            tg = f32(0.8) * tk
            ph = f32(TWO_PI) * f[sel].astype(f32)[:, None] * (T + g * (T - tg * (f32(1.0) - np.exp(-T / tg))))
        else:
            ph = f32(TWO_PI) * f[sel].astype(f32)[:, None] * T
        G = amp[sel].astype(f32)[:, None] * env * np.sin(ph + phi[sel].astype(f32)[:, None])
        idx = pos[sel][:, None] + np.arange(L)[None, :]
        m = idx < n
        ii = idx[m]
        if stereo_out:
            out[:, 0] += np.bincount(ii, weights=(G * pl[sel].astype(f32)[:, None])[m], minlength=n)
            out[:, 1] += np.bincount(ii, weights=(G * pr[sel].astype(f32)[:, None])[m], minlength=n)
        else:
            out += np.bincount(ii, weights=G[m], minlength=n)
        i += len(sel)
    return out


_SOS_CACHE: dict = {}


def _bp_sos(order, flo, fhi):
    """Pasabanda Butterworth cacheado (bordes cuantizados a 1/24 de octava)."""
    key = (order, int(round(np.log2(flo) * 24)), int(round(np.log2(fhi) * 24)))
    if key not in _SOS_CACHE:
        _SOS_CACHE[key] = dsp.butter_sos(order, [2 ** (key[1] / 24), 2 ** (key[2] / 24)], "bandpass")
    return _SOS_CACHE[key]


def _crackle(n: int, rate, rng, f_lo, f_hi, q=6.0, n_res=6, amp=None, amp_sigma=0.45, pan_spread=None):
    """Nube densa de micro-eventos (micro-burbujas, cristales): tren de impulsos Poisson (amplitud y
    polaridad propias) repartido en n_res resonadores de 2o orden (cada impulso -> seno amortiguado,
    tau = Q / (pi f)). Mucho más rápido que _grains para miles de eventos por segundo."""
    pos = _poisson_pos(rate, rng, n)
    k = len(pos)
    st = pan_spread is not None
    out = np.zeros((n, 2)) if st else np.zeros(n)
    if k == 0:
        return out
    a = rng.lognormal(0, amp_sigma, k) * rng.choice([-1.0, 1.0], k)
    if amp is not None:
        a = a * np.asarray(amp, np.float64)[pos]
    cls = rng.integers(0, n_res, k)
    fcs = np.exp(np.linspace(np.log(f_lo), np.log(f_hi), n_res) + rng.uniform(-0.1, 0.1, n_res))
    if st:
        gl, gr = dsp.pan_gains(rng.uniform(-pan_spread, pan_spread, k))
    for c in range(n_res):
        m = cls == c
        if not m.any():
            continue
        b, aa = dsp.rbj("bandpass", float(fcs[c]), q * rng.uniform(0.8, 1.25))
        if st:
            for ch, g in ((0, gl), (1, gr)):
                imp = np.bincount(pos[m], weights=a[m] * g[m], minlength=n)
                out[:, ch] += signal.lfilter(b, aa, imp)
        else:
            out += signal.lfilter(b, aa, np.bincount(pos[m], weights=a[m], minlength=n))
    # limitar a la banda propia: los flancos de 2o orden dejarían pasar el 'clic' del impulso hasta Nyquist
    return dsp.sos_filter(out, _bp_sos(2, 0.8 * f_lo, min(1.2 * f_hi, 0.45 * SR)))


def _bursts(n: int, pos, rng, lo, hi, dur_lo, dur_hi, amp, pan=None, attack=0.0015, order=2):
    """Ráfagas de ruido pasabanda (crunch, golpe de agua...), cada una sintetizada por separado."""
    stereo_out = pan is not None
    out = np.zeros((n, 2)) if stereo_out else np.zeros(n)
    amp = np.broadcast_to(np.asarray(amp, np.float64), (len(pos),))
    pans = np.broadcast_to(np.asarray(pan if pan is not None else 0.0, np.float64), (len(pos),))
    for j, p0 in enumerate(np.asarray(pos, np.int64)):
        L = max(16, int(rng.uniform(dur_lo, dur_hi) * SR))
        flo = lo * np.exp(rng.uniform(-0.15, 0.15))
        fhi = max(flo * 1.3, hi * np.exp(rng.uniform(-0.15, 0.15)))
        x = dsp.sos_filter(rng.standard_normal(L + 64), _bp_sos(order, flo, fhi))[64:]
        u = np.arange(L) / L
        ka = max(2, int(attack * SR))
        env = (1 - u) ** rng.uniform(1.6, 3.0)
        env[:ka] *= np.sin(np.linspace(0, np.pi / 2, ka)) ** 2
        g = x * env
        g /= (np.abs(g).max() + 1e-12)
        if stereo_out:
            gl, gr = dsp.pan_gains(pans[j])
            dsp.mix_into(out, np.stack([g * gl, g * gr], axis=1), int(p0), amp[j])
        else:
            dsp.mix_into(out, g, int(p0), amp[j])
    return out


def _nb_tone(f, rng, nb_db=-14.0, bw=4.0, jitter=0.0006):
    """Tono 'no puro': seno con micro-jitter de pitch + ruido de banda angosta alrededor (bw Hz)."""
    f = np.asarray(f, np.float64)
    n = len(f)
    t = np.arange(n) / SR
    fj = f * (1.0 + jitter * _mod(t, rng, 1.5, 1.0, octaves=2))
    ph = TWO_PI * np.cumsum(fj) / SR + rng.uniform(0, TWO_PI)
    a, b = _bl_noise(n, rng, bw), _bl_noise(n, rng, bw)
    return np.sin(ph) + 10 ** (nb_db / 20) * (a * np.cos(ph) - b * np.sin(ph)) / np.sqrt(2)


def _res_tone(f, rng, q=10.0):
    """Ruido resonado en f (curva de Hz por sample): ruido de banda angosta de ancho ~f/q modulado en cuadratura
    sobre la fase de f (equivale a ruido por un resonador de Q=q que sigue a f). Potencia = la de un seno."""
    f = np.asarray(f, np.float64)
    n = len(f)
    ph = TWO_PI * np.cumsum(f) / SR + rng.uniform(0, TWO_PI)
    bw = max(1.0, float(np.mean(f)) / (2.0 * max(1.0, float(q))))
    a, b = _bl_noise(n, rng, bw), _bl_noise(n, rng, bw)
    return (a * np.cos(ph) - b * np.sin(ph)) / np.sqrt(2)


def _decor(x, rng, amount=0.8, ms=11.0):
    """Mono -> estéreo con reflexiones cortas decorrelacionadas (paneles/carrocería). corr ~ 1/(1+a^2)."""
    x = dsp.mono(x)
    L = max(8, int(ms * 1e-3 * SR))
    t = np.arange(L) / SR
    chans = []
    for _ in range(2):
        h = rng.standard_normal(L) * np.exp(-t / (ms * 1e-3 / 3.5))
        h[: int(0.0008 * SR)] = 0.0
        h /= np.sqrt((h ** 2).sum()) + 1e-12
        chans.append(x + amount * signal.oaconvolve(x, h)[: len(x)])
    return np.stack(chans, axis=1)


def _widen(x, rng, corr=0.5, drift=0.1):
    """Ensanche compatible con mono: S = w * Hilbert(M) (90 grados a toda frecuencia) => correlación L/R
    = (1 - w^2) / (1 + w^2) independiente del contenido (ideal para camas tonales), L + R = 2 M.
    w deriva lentamente (+-drift) para que la imagen respire."""
    x = dsp.stereo(x)
    m = 0.5 * (x[:, 0] + x[:, 1])
    s0 = 0.5 * (x[:, 0] - x[:, 1])
    c = float(np.clip(corr, 0.0, 0.98))
    w = np.sqrt((1 - c) / (1 + c)) * (1 + drift * _mod(np.arange(len(m)) / SR, rng, 0.07))
    sh = np.imag(signal.hilbert(m)) * w
    return np.stack([m + sh + s0, m - sh - s0], axis=1)


def _finish(y, hp_hz=120.0, fin=0.01, fout=0.05) -> np.ndarray:
    y = dsp.stereo(np.nan_to_num(np.asarray(y, np.float64)))
    if hp_hz and hp_hz > 0:
        y = dsp.hp(y, float(hp_hz), 4)       # 24 dB/oct
    y = dsp.fade(y, max(0.003, fin), max(0.003, fout))
    return np.nan_to_num(y).astype(np.float32)


def _space(y, preset, send_db, hp_send=150.0):
    if not preset or preset in ("none", "dry") or send_db is None or send_db <= -80:
        return dsp.stereo(y)
    return dsp.reverb(dsp.stereo(y), str(preset), float(send_db), dry=1.0, hp_send=hp_send)


def _surface(s):
    s = str(s or "dry").lower()
    return s if s in SURFACES else "dry"


def _persp(p):
    p = str(p or "close").lower()
    return p if p in PERSPECTIVES else "close"


# =====================================================================================================
# bloques: rodado, aero, motor EV
# =====================================================================================================

def _roll_power(F, vt, surface, persp, wet, m):
    """Densidad espectral (potencia, lineal) del rodado. F [nf, 1], vt y m[*] [1, T]."""
    lf = np.log2(F)
    vn = np.clip(vt / V_REF, 0.02, 5.0)
    fpk = (720.0 + 480.0 * np.clip((vt - 4.0) / 26.0, 0, 1)) * (1 + 0.07 * m["fpk"])
    wdt = 1.2
    if surface == "gravel":
        fpk = fpk * 0.8
        wdt = 1.4
    elif surface == "snow":
        fpk = fpk * 0.72
    P = np.exp(-0.5 * ((lf - np.log2(fpk)) / wdt) ** 2)
    P = P + 0.18 * _bump(lf, 230.0, 0.75)                                   # cavidad / estructura
    P = P + 0.05 * (0.6 + 0.4 * vn) * (F / 2500.0) ** -1.3 * _sig(F, 1800.0, 0.5)   # snap de tacos, air pumping
    ftr = vt / 0.03 * (1 + 0.03 * m["tr"])                                  # tread hum (Q~5, +-10 %)
    P = P + 0.22 * np.exp(-0.5 * ((F - ftr) / (0.1 * ftr + 8.0)) ** 2) * (vt > 0.5)
    if surface == "gravel":
        P = P + 0.45 * _bump(lf, 600.0, 0.55) + 0.08 * (F / 3000.0) ** -0.8 * _sig(F, 1500.0, 0.5)
    if surface == "snow":
        P = P / (1 + (F / (2500.0 * (1 + 0.06 * m["lp"]))) ** 4) + 0.25 * _bump(lf, 700.0, 0.6)
    if wet > 0:
        sz = _sig(F, 2500.0, 0.35) * (1 - _sig(F, 10500.0, 0.3)) * (F / 4000.0) ** -0.4
        P = P + wet * 0.9 * np.clip(vn, 0.15, 2.5) * sz * (1 + 0.25 * m["sz"])
        P = P + wet * 0.35 * _bump(lf, 380.0 * (1 + 0.05 * m["sw"]), 0.6) * (1 + 0.3 * m["sw"])
    if persp == "far":
        P = P / (1 + (F / (3000.0 * (1 + 0.08 * m["lp"]))) ** 4)
    elif persp == "onboard":
        P = P * (0.10 + _bump(lf, 300.0 * (1 + 0.06 * m["lp"]), 0.85)) / (1 + (F / 6000.0) ** 2)
    elif persp == "interior":
        P = P * (0.5 + 1.6 * _bump(lf, 240.0 * (1 + 0.06 * m["lp"]), 0.7))
    return P


_FREF = np.fft.rfftfreq(2048, 1 / SR)[:, None] + 1e-3
_ZM = {k: np.zeros((1, 1)) for k in ("fpk", "tr", "lp", "sz", "sw", "g")}
_PREF_ROLL = float(_roll_power(_FREF, np.full((1, 1), V_REF), "dry", "close", 0.0, _ZM).mean())


def _rot_am(v, rng, depth_db=1.5, radius=R_TIRE):
    """AM de rotación de rueda (desbalance/no-uniformidad): 1-2 dB, frecuencia y profundidad con jitter."""
    n = len(v)
    t = np.arange(n) / SR
    f = np.maximum(v, 0) / (TWO_PI * radius) * (1 + 0.05 * _mod(t, rng, 0.7))
    ph = TWO_PI * np.cumsum(f) / SR + rng.uniform(0, TWO_PI)
    d = depth_db * (0.7 + 0.3 * _mod(t, rng, 0.2))
    per = (0.75 * np.sin(ph) + 0.3 * np.sin(2 * ph + rng.uniform(0, TWO_PI))) * (0.65 + 0.35 * _mod(t, rng, 0.45))
    irr = 0.55 * _bl_noise(n, rng, max(1.0, float(np.mean(f)) * 1.2))      # textura irregular del pavimento
    return 10 ** (d * (per + irr) / 1.25 / 20)


def _tire_roll(v, rng, surface="dry", persp="close", wet=None, corr=None, particles=1.0, boost=None,
               am_db=1.5):
    """Rodado de neumático. v: velocidad (m/s) por sample. Nivel ~ (v/V_REF)^1.5 (=30 log10 v).
    Devuelve mono [n] o estéreo [n, 2] si corr != None. boost: multiplicador (curva) de densidad de
    partículas (deslizamiento lateral en curvas)."""
    v = np.asarray(v, np.float64)
    n = len(v)
    surface = _surface(surface)
    persp = _persp(persp)
    wet = (1.0 if surface == "wet" else 0.0) if wet is None else float(wet)
    ts = np.arange(n) / SR
    tc = np.arange(0.0, n / SR + 0.3, 0.01)
    mods = {k: _mod(tc, rng, r) for k, r in (("fpk", 0.25), ("tr", 0.4), ("lp", 0.15), ("sz", 0.6),
                                             ("sw", 0.35), ("g", 0.2))}

    def mag(t, f):
        F = f[:, None] + 1e-3
        vt = np.interp(t, ts, v)[None, :]
        m = {k: np.interp(t, tc, val)[None, :] for k, val in mods.items()}
        P = _roll_power(F, vt, surface, persp, wet, m)
        lvl = np.clip(vt / V_REF, 0, 5) ** 1.5 * 10 ** (1.5 * m["g"] / 20)
        return np.sqrt(P / _PREF_ROLL) * lvl

    y = _paint(n, rng, mag, corr=corr)
    am = _rot_am(v, rng, am_db)
    # macro-textura del pavimento (longitudes ~0.45 m -> ~v/0.45 Hz) y turbulencia del agua: fluctuación
    # rápida aleatoria de +-1-2 dB (rugosidad natural; evita envolventes "lisas" de ruido sintético)
    vm = max(1.0, float(np.mean(v)))
    tex_db = 1.2 + 0.8 * min(wet, 1.5) + (0.5 if surface in ("gravel", "snow") else 0.0)
    tex = 10 ** (tex_db * np.clip(_bl_noise(n, rng, float(np.clip(vm / 0.45, 8.0, 60.0))), -2.5, 2.5) / 20)
    am = am * tex
    y = y * (am[:, None] if y.ndim == 2 else am)
    base_rms = _rms(y)
    lvl_s = np.clip(v / V_REF, 0, 5) ** 1.5
    bst = np.ones(n) if boost is None else dsp.as_curve(boost, n)
    st = corr is not None

    def pans(k, spread=0.55):
        return rng.uniform(-spread, spread, k) if st else None

    layers = []
    # --- mojado: micro-burbujas (Minnaert, radios 0.3-1 mm -> 3-11 kHz), 2-6 k/s
    if wet > 0 and particles > 0:
        rate = wet * (2000.0 + 4000.0 * np.clip(v / 20.0, 0, 1)) * (1 + 0.3 * _mod(ts, rng, 0.8)) * (v > 0.3)
        b = _crackle(n, np.minimum(rate, 9000.0), rng, 3000, 11000, q=7.0, n_res=7, amp=lvl_s,
                     pan_spread=0.6 if st else None)
        b = dsp.hp(b, 2500, 2)
        layers.append(b * (0.32 * wet * particles * base_rms / _rms(b)))
    # --- grava: granos + crunches
    if surface == "gravel" and particles > 0:
        wf = 1.0 - 0.2 * min(wet, 1.0)
        rate = (300.0 + 1200.0 * np.clip(v / 14.0, 0, 1.0)) * (v > 0.3) * bst * (1 + 0.35 * _mod(ts, rng, 1.5))
        pos = _poisson_pos(rate, rng, n)
        k = len(pos)
        f = np.exp(rng.uniform(np.log(1500 * wf), np.log(6000 * wf), k))
        tau = rng.uniform(2e-3, 6e-3, k) * (1 - 0.3 * min(wet, 1.0))
        # cola pesada (Pareto): lecho denso de piedritas + crujidos sueltos que sobresalen
        a = np.minimum(rng.pareto(1.15, k) + 1.0, 30.0) * rng.lognormal(0, 0.25, k)
        g = _grains(n, pos, f, tau, a * lvl_s[pos], rng, pan=pans(k, 0.6))
        layers.append(g * (1.3 * particles * base_rms / _rms(g)))
        crate = (30.0 + 30.0 * np.clip(v / 14.0, 0, 1)) * (v > 0.3) * bst
        cpos = _poisson_pos(crate, rng, n)
        cr = _bursts(n, cpos, rng, 300, 900, 0.015, 0.04,
                     np.minimum(rng.pareto(1.5, len(cpos)) + 1.0, 8.0) * lvl_s[cpos],
                     pan=pans(len(cpos), 0.4))
        layers.append(cr * (0.7 * particles * base_rms / _rms(cr)))
    # --- nieve: granos de compactación + chirridos stick-slip ocasionales
    if surface == "snow" and particles > 0:
        rate = (200.0 + 700.0 * np.clip(v / 14.0, 0, 1.2)) * (v > 0.3) * bst * (1 + 0.3 * _mod(ts, rng, 1.0))
        pos = _poisson_pos(rate, rng, n)
        k = len(pos)
        g = _grains(n, pos, np.exp(rng.uniform(np.log(500), np.log(3000), k)), rng.uniform(1.5e-3, 5e-3, k),
                    rng.lognormal(0, 0.5, k) * lvl_s[pos], rng, pan=pans(k, 0.5))
        layers.append(g * (0.55 * particles * base_rms / _rms(g)))
        sq = np.zeros((n, 2)) if st else np.zeros(n)
        spos = _poisson_pos(0.35 * np.clip(v / 8.0, 0, 1.5) * bst, rng, n)
        for p0 in spos:
            L = int(rng.uniform(0.06, 0.18) * SR)
            f0 = rng.uniform(260, 420)
            fcur = f0 * (1 + rng.uniform(-0.25, 0.4) * np.linspace(0, 1, L))
            s = dsp.stick_slip(L, fcur, rng, jitter=0.12)
            s = dsp.bp(s, 700, 2200, 2) * np.sin(np.linspace(0, np.pi, L)) ** 1.5
            s *= lvl_s[p0] / (np.abs(s).max() + 1e-12)
            if st:
                gl, gr = dsp.pan_gains(rng.uniform(-0.4, 0.4))
                s = np.stack([s * gl, s * gr], axis=1)
            dsp.mix_into(sq, s, int(p0), 1.0)
        if np.abs(sq).max() > 0:
            layers.append(sq * (0.9 * particles * base_rms))
    for L_ in layers:
        if persp == "far":
            L_ = dsp.lp(L_, 3000, 4)
        elif persp == "onboard":
            L_ = 0.5 * dsp.lp(L_, 3500, 2)
        elif persp == "interior":
            L_ = 0.6 * L_
        y = y + (L_ if (L_.ndim == y.ndim) else (dsp.stereo(L_) if y.ndim == 2 else dsp.mono(L_)))
    if persp == "interior":
        y = dsp.through_glass(y)
    return y


def _aero_power(F, vt, mc, persp):
    lf = np.log2(F)
    fc = (300.0 + 15.0 * vt) * (1 + 0.08 * mc)
    P = np.exp(-0.5 * ((lf - np.log2(fc)) / 1.15) ** 2) + 0.06 * (F / (2.5 * fc)) ** -1.2 * _sig(F, 2 * fc, 0.5)
    if persp == "far":
        P = P / (1 + (F / 3000.0) ** 4)
    elif persp == "onboard":
        P = P + 0.5 * _bump(lf, 170.0, 0.6)          # buffeting del viento sobre el rig
    return P


_PREF_AERO = float(_aero_power(_FREF, np.full((1, 1), V_REF), np.zeros((1, 1)), "close").mean())


def _aero(v, rng, persp="close", corr=None):
    """Ruido aerodinámico: centroide ~ 300 + 15 v Hz, nivel 0.354 (v/V_REF)^3 (= tire a 100 km/h)."""
    v = np.asarray(v, np.float64)
    n = len(v)
    persp = _persp(persp)
    ts = np.arange(n) / SR
    tc = np.arange(0.0, n / SR + 0.3, 0.01)
    mc = _mod(tc, rng, 0.3)
    gust = _mod(tc, rng, 0.1, octaves=3)        # 0.1 / 0.2 / 0.4 Hz

    def mag(t, f):
        F = f[:, None] + 1e-3
        vt = np.interp(t, ts, v)[None, :]
        P = _aero_power(F, vt, np.interp(t, tc, mc)[None, :], persp)
        lvl = 0.354 * np.clip(vt / V_REF, 0, 5) ** 3 * 10 ** (2.0 * np.interp(t, tc, gust)[None, :] / 20)
        return np.sqrt(P / _PREF_AERO) * lvl

    y = _paint(n, rng, mag, corr=corr)
    if persp == "interior":
        y = dsp.through_glass(y)
    return y


def _ev(v, rng, amount=1.0, load=0.5, avas=1.0, inverter=1.0, mech=1.0, f_scale=1.0,
        avas_f0=None, f_sw=None):
    """Capa del motor eléctrico (mono). Niveles relativos al rodado a 50 km/h (RMS 1).
    amount escala órdenes + inversor (whine); mech = ruido mecánico/magnético del motor."""
    v = np.asarray(v, np.float64)
    n = len(v)
    t = np.arange(n) / SR
    vn = np.clip(v / V_REF, 0, 5)
    kmh = v * 3.6
    load = dsp.as_curve(load, n)
    avas_f0 = avas_f0 or _note_hz("Eb4")
    f_sw = f_sw or _note_hz("Bb8")
    fr = 150.0 * np.maximum(v, 0) / 45.0 * f_scale            # frecuencia de rotor (Hz)
    pj = 1.0 + 0.003 * _mod(t, rng, 0.6)                       # ripple de velocidad del rotor (+-0.3 %)
    on = _ss(v, 0.3, 1.5)
    tq_db = 6.0 * (load - 0.5)
    flick = 10 ** (0.6 * _mod(t, rng, 6.0, octaves=3) / 20)    # micro-fluctuación de carga
    y = np.zeros(n)
    if amount > 0:
        for order, ldb in ((8, -20.0), (16, -27.0), (24, -31.0), (48, -38.0)):
            fo = order * fr * pj
            a = (amount * 10 ** ((ldb + tq_db) / 20) * vn ** 1.2 * on * flick
                 * 10 ** (2.0 * _mod(t, rng, 0.25) / 20) * np.clip((17000 - fo) / 3000, 0, 1))
            if a.max() < 1e-7:
                continue
            y += a * _nb_tone(fo, rng, nb_db=-12, bw=3.0 + 0.004 * float(np.mean(fo)))
        # inversor: bandas laterales f_sw +- 2 f_elec (4 pares de polos -> 2 f_e = 8 f_r)
        if inverter > 0:
            fsw = f_sw * (1 + 0.0015 * _mod(t, rng, 2.0))
            fe2 = 8.0 * fr * pj
            cur = (0.35 + 0.65 * np.clip(load, 0, 2)) * (0.3 + 0.7 * np.clip(vn, 0, 1.5)) * _ss(v, 0.05, 0.8)
            inv = (10 ** (-45 / 20) * (_nb_tone(fsw + fe2, rng, -10, 6.0) + _nb_tone(np.maximum(fsw - fe2, 200), rng, -10, 6.0))
                   + 10 ** (-53 / 20) * _nb_tone(fsw, rng, -8, 8.0))
            y += inverter * amount * cur * flick * inv
    # ruido mecánico / magnético: bandas alrededor de los órdenes + piso ancho
    if mech > 0:
        tc = np.arange(0.0, n / SR + 0.3, 0.01)
        frc = np.interp(tc, t, fr)
        mm = _mod(tc, rng, 0.3)

        def mag(tt, f):
            F = f[:, None] + 1e-3
            fo8 = np.interp(tt, tc, frc)[None, :] * 8.0
            P = 0.25 * _bump(np.log2(F), 1500.0, 1.2)
            for k, w in ((1, 1.0), (2, 0.5), (3, 0.35)):
                fo = fo8 * k + 1.0
                P = P + w * np.exp(-0.5 * ((F - fo) / (0.07 * fo + 10.0)) ** 2)
            return np.sqrt(P / (P.mean(axis=0, keepdims=True) + 1e-12)) * (1 + 0.15 * np.interp(tt, tc, mm)[None, :])

        mn = _paint(n, rng, mag)
        y += mech * 0.03 * vn ** 1.2 * on * mn
    # AVAS (< 20 km/h): 3 parciales armónicos que suben con la velocidad + ruido tenue
    if avas > 0:
        g = avas * np.clip(1 - kmh / 20.0, 0, 1) ** 0.8
        if g.max() > 1e-4:
            f0 = avas_f0 * (1 + 0.008 * kmh) * (1 + 0.002 * _mod(t, rng, 0.2))
            br = 10 ** (1.0 * _mod(t, rng, 0.15) / 20)
            av = sum(10 ** (d / 20) * _nb_tone(f0 * k, rng, -18, 2.0) for k, d in ((1, 0.0), (2, -8.0), (3, -14.0)))
            av = av + 0.05 * dsp.bp(rng.standard_normal(n), 250, 1800, 2)
            y += 0.4 * g * br * av
    return y


def _source(v, rng, surface="dry", persp="close", ev=1.0, aero=1.0, wet=None, boost=None, load=0.5,
            avas=1.0, particles=1.0, corr=None, f_scale=1.0, am_db=1.5):
    y = _tire_roll(v, rng, surface, persp, wet=wet, boost=boost, particles=particles, corr=corr, am_db=am_db)
    if aero > 0:
        y = y + aero * _aero(v, rng, persp, corr=corr)
    if ev > 0:
        e = _ev(v, rng, amount=ev, load=load, avas=avas, f_scale=f_scale)
        y = y + (e[:, None] if y.ndim == 2 else e)
    return y


def _propagate(src, x, y, *, z=0.45, mic_h=1.1, ground=0.4, near=0.8, pan_scale=0.85, itd_ms=0.45, air=True):
    """Fuente móvil en trayectoria arbitraria (x lateral +der, y adelante, en m, por sample).
    Doppler por retardo variable, 1/r, reflejo de suelo (fuente imagen), absorción del aire, pan + ITD.
    Normalizado: ganancia ~1 en el punto más cercano. Devuelve (estéreo, r_directo)."""
    src = dsp.mono(src)
    n = len(src)
    rd = np.sqrt(x ** 2 + y ** 2 + (z - mic_h) ** 2)
    rg = np.sqrt(x ** 2 + y ** 2 + (z + mic_h) ** 2)
    idx = np.arange(n, dtype=np.float64)
    d = np.interp(idx - rd / C_SOUND * SR, idx, src, left=0.0, right=0.0)
    g = np.interp(idx - rg / C_SOUND * SR, idx, src, left=0.0, right=0.0)
    out = d / np.maximum(rd, near) + ground * g / np.maximum(rg, near)
    out *= max(float(rd.min()), near)
    if air:
        fc = np.clip(20000.0 / (1 + rd / 12.0) ** 0.75, 1500.0, 19500.0)
        out = dsp.tv_filter(out, fc, "lowpass", 0.6)
    p = np.clip(np.sin(np.arctan2(x, y)) * pan_scale, -1, 1)
    st = dsp.pan(out, p)
    dly = p * itd_ms * 1e-3 * SR
    st[:, 0] = np.interp(idx - np.maximum(dly, 0), idx, st[:, 0], left=0.0)
    st[:, 1] = np.interp(idx - np.maximum(-dly, 0), idx, st[:, 1], left=0.0)
    return st, rd


def _tail_fade(y, start, length):
    """Fade-out coseno desde `start` durante `length` samples, silencio después."""
    y = np.array(y, np.float64, copy=True)
    n = len(y)
    s = int(max(0, min(n, start)))
    L = int(max(1, length))
    w = np.zeros(n - s)
    k = min(L, n - s)
    w[:k] = np.cos(np.linspace(0, np.pi / 2, k)) ** 2
    y[s:] *= w[:, None] if y.ndim == 2 else w
    return y


def _key_scale(speed_ms, tune=True):
    """Factor de relación de reducción para que el orden 8 a la velocidad nominal caiga en Bb/Db/Eb/Ab."""
    if not tune or speed_ms < 1.0:
        return 1.0
    f8 = 8 * 150.0 * speed_ms / 45.0
    return float(np.clip(_snap(f8, _ROOT_PCS) / f8, 0.84, 1.19))


# =====================================================================================================
# recetas
# =====================================================================================================

def _straight_passby(dur, rng, *, speed_kmh, closest_m, direction, surface, ev, height_m, peak_pos, aero,
                     wetness, particles=1.0, ground=None, sizzle_extra=0.0, extra_src=None):
    """Núcleo de pass-by recto. Devuelve (estéreo seco, sync_sample, src, info)."""
    dur = max(0.6, float(dur))
    v_ms = max(1.0, float(speed_kmh) / 3.6)
    closest = max(0.5, float(closest_m))
    direction = 1 if float(direction) >= 0 else -1
    tpk = float(np.clip(peak_pos, 0.1, 0.9)) * dur
    x0 = v_ms * max(tpk, dur - tpk)
    pre = np.sqrt(x0 ** 2 + closest ** 2 + 4 * height_m ** 2) / C_SOUND + 0.06
    P = int(pre * SR)
    n = dsp.n_of(dur)
    N = n + P
    t = (np.arange(N) - P) / SR
    v = v_ms * (1 + 0.008 * _mod(t, rng, 0.3))
    surface = _surface(surface)
    wet = wetness if wetness is not None else (1.0 if surface == "wet" else 0.0)
    src = _source(v, rng, surface, "close", ev=ev, aero=aero, wet=wet + sizzle_extra, particles=particles,
                  f_scale=_key_scale(v_ms))
    if extra_src is not None:
        src = src + extra_src(t, v)
    out = dsp.passby(src, speed_ms=v_ms, closest_m=closest, t_closest=P / SR + tpk, direction=direction,
                     height_m=height_m, ground=_GROUND[surface] if ground is None else ground)
    out = out[P:]
    sync = int(round((tpk + closest / C_SOUND) * SR))
    info = dict(v_ms=v_ms, closest=closest, direction=direction, tpk=tpk, n=n, t=t[P:], src_rms=_rms(src))
    return out, sync, src, info


def _spray_tail(n, rng, *, tpk, v_ms, direction, amount):
    """Estela de agua de un auto sobre piso mojado: neblina HP 2.5-9 kHz + gotitas que caen, que quedan
    flotando detrás del auto después del paso más cercano (deriva hacia el lado por donde se aleja)."""
    t = np.arange(n) / SR
    tau = 0.25 + 0.25 * np.clip(v_ms / 14.0, 0, 1.5)
    env = _ss(t, tpk - 0.06, tpk + 0.12) * np.exp(-np.maximum(t - tpk - 0.12, 0) / tau)
    if env.max() <= 0:
        return np.zeros((n, 2))
    mist = dsp.decorrelated_stereo(lambda r: dsp.bp(r.standard_normal(n), 2500, 9000, 2), rng, 0.3)
    mist = mist * np.clip(1 + 0.5 * _bl_noise(n, rng, 30.0), 0.2, None)[:, None]
    mist /= _rms(mist)
    drops = _crackle(n, 900.0 * env * np.clip(v_ms / 10.0, 0.3, 1.5), rng, 3500, 9000, q=12.0, n_res=6,
                     pan_spread=0.7)
    y = (mist + 0.3 * drops / _rms(drops)) * env[:, None]
    gl, gr = dsp.pan_gains(direction * 0.35 * _ss(t, tpk, tpk + 0.6))
    return np.stack([y[:, 0] * gl, y[:, 1] * gr], axis=1) * 1.41 * amount


def _body_whoomph(n, rng, *, v_ms, closest, tpk, direction, amount):
    """Pulso de presión del cuerpo del auto al pasar muy cerca (80-250 Hz, envolvente ~1/r^2.5)."""
    t = np.arange(n) / SR
    x = v_ms * (t - tpk) * direction
    r = np.sqrt(x ** 2 + closest ** 2)
    env = (closest / r) ** 2.5
    nz = dsp.bp(rng.standard_normal(n), 80, 250, 2) * (1 + 0.2 * _mod(t, rng, 3.0))
    p = np.clip(np.arctan2(x, closest) / (np.pi / 2) * 0.8, -1, 1)
    return dsp.pan(nz * env * amount, p)


@recipe("veh.passby", family="vehicle", sync="peak", kind="event")
def passby(dur, rng, *, speed_kmh=50.0, closest_m=4.0, direction=1, surface="wet", ev=0.4, height_m=0.5,
           peak_pos=0.5, aero=1.0, wetness=None, body=0.5, space="open_exterior", send_db=-18.0,
           hp_hz=120.0, **_):
    """Pass-by EV: rodado + aero + motor EV -> dsp.passby (Doppler, suelo, aire, pan/ITD) + espacio.
    sync = paso más cercano (llegada del sonido). Extras: peak_pos (fracción de dur), aero, wetness,
    body (pulso de presión 80-250 Hz si closest < 6 m), space/send_db (IR), hp_hz."""
    out, sync, src, info = _straight_passby(dur, rng, speed_kmh=speed_kmh, closest_m=closest_m,
                                            direction=direction, surface=surface, ev=float(ev) / 0.25,
                                            height_m=height_m, peak_pos=peak_pos, aero=aero, wetness=wetness)
    n = info["n"]
    wet_amt = float(wetness) if wetness is not None else (1.0 if _surface(surface) == "wet" else 0.0)
    if wet_amt > 0:
        out = out + _spray_tail(n, rng, tpk=info["tpk"] + info["closest"] / C_SOUND, v_ms=info["v_ms"],
                                direction=info["direction"],
                                amount=0.22 * wet_amt * info["src_rms"] * min(1.0, 4.0 / info["closest"]))
    out = dsp.hp(out, hp_hz, 4) if hp_hz else out
    if body > 0 and info["closest"] < 6.0:
        out = out + _body_whoomph(n, rng, v_ms=info["v_ms"], closest=info["closest"], tpk=info["tpk"],
                                  direction=info["direction"],
                                  amount=float(body) * 0.45 * info["src_rms"] * min(1.5, 2.0 / info["closest"]) ** 0.5)
        out = dsp.hp(out, 70, 2)
    out = _tail_fade(out, n - int(0.25 * SR * (1 - peak_pos) * 2), int(0.25 * SR * (1 - peak_pos) * 2))
    out = _space(out, space, send_db)
    return Render(_finish(out, hp_hz=None, fin=0.03, fout=0.08), sync,
                  {"t_closest_s": round(sync / SR, 4), "speed_ms": round(info["v_ms"], 2),
                   "surface": _surface(surface), "space": space})


@recipe("veh.approach", family="vehicle", sync="end", kind="event")
def approach(dur, rng, *, speed_kmh=40.0, start_m=60.0, end_m=5.0, surface="dry", ev=0.4, lateral_m=1.2,
             height_m=0.45, tail_s=0.08, extra_rise_db=4.0, space="open_exterior", send_db=-20.0, hp_hz=120.0,
             wetness=None, **_):
    """Auto acercándose de frente (sin cruzar): Doppler hacia arriba, nivel creciente 1/r, barrido de peine
    por reflejo de suelo, absorción del aire que se abre, leve deriva de pan. Termina en end_m a la
    velocidad speed_kmh justo en `at` (sync = end: llegada del último sample del swell; luego tail_s de
    fade). Si start_m no es alcanzable a esa velocidad en dur, la velocidad inicial se ajusta dentro de
    0.85x-1.25x (regen / aceleración suave). extra_rise_db: licencia de diseño, rampa extra (dB) que exagera
    la subida hacia `at` (0 = sólo física: 1/r + suelo + aire)."""
    dur = max(0.3, float(dur))
    v1 = max(1.0, float(speed_kmh) / 3.6)
    end = max(1.0, float(end_m))
    D = max(0.0, float(start_m) - end)
    v0 = float(np.clip(2 * D / dur - v1, 0.85 * v1, 1.25 * v1))
    acc = (v1 - v0) / dur
    d_start = end + 0.5 * (v0 + v1) * dur
    pre = d_start / C_SOUND + 0.12
    P = int(pre * SR)
    n_main = dsp.n_of(dur)
    n_tail = int(max(0.02, tail_s) * SR)
    N = P + n_main + n_tail + int(0.03 * SR)
    t = (np.arange(N) - P) / SR
    v = np.where(t < 0, v0, np.where(t < dur, v0 + acc * np.clip(t, 0, dur), v1))
    v = v * (1 + 0.006 * _mod(t, rng, 0.4))
    s = np.cumsum(v) / SR
    yv = end + (s[P + n_main] - s)
    xl = float(lateral_m) * (1 + 0.15 * _mod(t, rng, 0.25))
    load = 0.3 if acc < -0.5 else 0.6
    surface = _surface(surface)
    src = _source(v, rng, surface, "close", ev=float(ev) / 0.25, aero=1.0, wet=wetness, load=load,
                  f_scale=_key_scale(v1))
    st, rd = _propagate(src, xl, yv, z=height_m, mic_h=1.1, ground=_GROUND[surface])
    st = st[P:]
    rd = rd[P:]
    sync = int(round((dur + rd[n_main] / C_SOUND) * SR))
    if extra_rise_db:
        u = np.clip(np.arange(len(st)) / max(1, sync), 0, 1)
        st = st * (10 ** (-float(extra_rise_db) * (1 - u ** 1.5) / 20))[:, None]
    st = dsp.hp(st, hp_hz, 4) if hp_hz else st
    st = _tail_fade(st, sync, n_tail)
    st = _space(st, space, send_db)
    return Render(_finish(st, hp_hz=None, fin=0.04, fout=0.005), sync,
                  {"start_m": round(d_start, 1), "end_m": end, "v0_kmh": round(v0 * 3.6, 1),
                   "v1_kmh": round(v1 * 3.6, 1), "end_s": round(sync / SR, 4)})


@recipe("veh.onboard_roll", family="vehicle", sync="start", kind="bed")
def onboard_roll(dur, rng, *, speed_kmh=50.0, surface="dry", perspective="onboard", ev=0.25, aero=1.0,
                 joints=0.12, variation=1.0, wetness=None, space=None, send_db=-18.0, tune=True, hp_hz=120.0, **_):
    """Rodado sostenido (cámara montada / interior / lejos). Velocidad con deriva lenta 1/f (+-3.5 %),
    textura de superficie que respira, juntas de asfalto ocasionales (eje delantero + trasero separados por
    batalla/v), aero según perspectiva y una pizca de motor EV."""
    dur = max(0.5, float(dur))
    n = dsp.n_of(dur)
    t = np.arange(n) / SR
    persp = _persp(perspective)
    surface = _surface(surface)
    v0 = max(0.5, float(speed_kmh) / 3.6)
    v = v0 * (1 + 0.035 * float(variation) * _mod(t, rng, 0.07) + 0.008 * _mod(t, rng, 0.6))
    roll = _tire_roll(v, rng, surface, persp, wet=wetness, corr=0.45, am_db=1.0)
    aw = {"onboard": 1.3, "interior": 0.5, "far": 0.6, "close": 1.0}[persp] * float(aero)
    y = roll + (aw * _aero(v, rng, persp, corr=0.25) if aw > 0 else 0.0)
    ew = {"onboard": 1.0, "interior": 2.2, "far": 0.5, "close": 1.0}[persp] * float(ev) / 0.25
    if ew > 0:
        e = _ev(v, rng, amount=ew, load=0.5, mech=1.0, f_scale=_key_scale(v0, bool(tune)))
        if persp == "interior":
            e = dsp.lp(e, 4000, 2)
        elif persp == "far":
            e = dsp.lp(e, 3000, 4)
        y = y + _decor(e, rng, 0.9)
    # juntas / parches del asfalto: dos golpes (eje delantero y trasero)
    if joints > 0 and surface in ("dry", "wet"):
        jpos = _poisson_pos(float(joints) * np.clip(v / V_REF, 0.2, 2), rng, n)
        th = np.zeros((n, 2))
        for p0 in jpos:
            gap = int(2.75 / max(v[p0], 1.0) * SR)
            for k, (p1, a) in enumerate(((p0, 1.0), (p0 + gap, 0.75 * rng.uniform(0.7, 1.1)))):
                L = int(rng.uniform(0.025, 0.045) * SR)
                b = dsp.bp(rng.standard_normal(L + 64), 90, 380, 2)[64:] * np.exp(-np.arange(L) / (0.012 * SR))
                b[: int(0.002 * SR)] *= np.linspace(0, 1, int(0.002 * SR))
                tk = int(0.003 * SR)
                b[:tk] += 0.25 * dsp.hp(rng.standard_normal(tk), 2000, 2) * np.linspace(1, 0, tk)
                b /= np.abs(b).max() + 1e-12
                if persp == "interior":
                    b = dsp.lp(b, 900, 2)
                elif persp in ("far", "onboard"):
                    b = dsp.lp(b, 2500, 2)
                gl, gr = dsp.pan_gains(rng.uniform(-0.3, 0.3))
                dsp.mix_into(th, np.stack([b * gl, b * gr], axis=1), int(p1), a)
        y = y + th * (0.9 * _rms(roll) * 2.2)
    if space:
        y = _space(y, space, send_db)[:n]
    return Render(_finish(y, hp_hz, fin=0.05, fout=0.08), 0,
                  {"perspective": persp, "surface": surface, "speed_kmh": speed_kmh})


@recipe("veh.wheel_spin", family="vehicle", sync="start", kind="event")
def wheel_spin(dur, rng, *, speed_kmh=40.0, disc_whir=0.5, darken_at=0.5, surface="dry", spokes=5,
               space="underpass_concrete", send_db=-24.0, hp_hz=120.0, darken_db=-10.0, darken_hz=500.0,
               darken_ramp_s=0.15, **_):
    """Primer plano de rueda: rodado cercano + whir de disco de freno (BP 2-5 kHz con AM de rotación,
    runout irregular) + swish de aire de los rayos de la llanta (AM a spokes*f_rot y f_rot). En darken_at
    (fracción de dur) el LPF barre 8 kHz -> darken_hz (500) en darken_ramp_s (0.15 s) y el nivel cae
    darken_db (-10 dB; con el LPF suma ~-20 dB de banda ancha). (Antes: 1.5 kHz en 0.45 s y -6 dB.)"""
    dur = max(0.4, float(dur))
    n = dsp.n_of(dur)
    t = np.arange(n) / SR
    v = max(1.0, float(speed_kmh) / 3.6) * (1 + 0.01 * _mod(t, rng, 0.4))
    f_rot = v / (TWO_PI * R_TIRE)
    roll = _tire_roll(v, rng, surface, "close", corr=0.55)
    rr = _rms(roll)
    tc = np.arange(0.0, dur + 0.3, 0.01)
    m1, m2 = _mod(tc, rng, 0.3), _mod(tc, rng, 0.5)

    def whir_mag(tt, f):
        F = f[:, None] + 1e-3
        lf = np.log2(F)
        a = np.interp(tt, tc, m1)[None, :]
        b = np.interp(tt, tc, m2)[None, :]
        P = (_bump(lf, 3200 * (1 + 0.06 * a), 0.55) + 0.45 * _bump(lf, 4600 * (1 + 0.05 * b), 0.3)
             + 0.25 * _bump(lf, 2200 * (1 - 0.04 * a), 0.35))
        return np.sqrt(P / P.mean(axis=0, keepdims=True))

    whir = _paint(n, rng, whir_mag, corr=0.6)
    am_d = _rot_am(v, rng, depth_db=4.0)
    whir = whir * am_d[:, None]
    whir *= float(disc_whir) * 0.55 * rr / _rms(whir)
    # rayos de la llanta cortando aire
    ph = TWO_PI * np.cumsum(f_rot * (1 + 0.015 * _mod(t, rng, 0.8))) / SR
    sp_am = 1 + 0.35 * np.sin(int(spokes) * ph + 0.3 * _bl_noise(n, rng, 3.0)) + 0.12 * np.sin(ph + 1.1)
    sw = dsp.decorrelated_stereo(lambda r: dsp.bp(r.standard_normal(n), 1000, 7000, 2), rng, 0.5)
    sw = sw * np.maximum(sp_am, 0)[:, None]
    sw *= 0.3 * rr / _rms(sw)
    y = roll + whir + sw
    # oscurecimiento (sigue a la imagen que va a negro): LPF 16k -> 8k (40 ms antes de darken) -> darken_hz en
    # darken_ramp_s, con darken_db de caída ancha. El cuerpo del rodado < 1.5 kHz es el que lleva el nivel, así
    # que la caída tiene que ser de banda ancha para que "apagarse" se note (~-20 dB total por defecto).
    td = float(np.clip(darken_at, 0, 1)) * dur
    ramp = float(np.clip(darken_ramp_s, 0.03, 1.0))
    s1 = _ss(t, td - 0.04, td)
    s2 = _ss(t, td, td + ramp)
    f_end = float(np.clip(darken_hz, 200.0, 8000.0))
    fc = np.exp(np.log(16000) + (np.log(8000) - np.log(16000)) * s1 + (np.log(f_end) - np.log(8000)) * s2)
    fc *= 1 + 0.05 * _mod(t, rng, 0.5)
    y = dsp.tv_filter(y, fc, "lowpass", 0.707, stages=2, block=16) * (10 ** (float(darken_db) * s2 / 20))[:, None]
    y = dsp.hp(y, hp_hz, 4) if hp_hz else y
    y = _tail_fade(y, n - int(0.06 * SR), int(0.06 * SR))
    y = _space(y, space, send_db)
    return Render(_finish(y, hp_hz=None, fin=0.01, fout=0.05), 0,
                  {"f_rot_hz": round(float(f_rot.mean()), 2), "darken_s": round(td, 3)})


@recipe("veh.ev_drive", family="vehicle", sync="start", kind="bed")
def ev_drive(dur, rng, *, speed_kmh=50.0, accel=0.0, whine=0.5, tune=True, avas=1.0, mech=1.0, inverter=1.0,
             width=0.9, hp_hz=120.0, **_):
    """Capa de motor eléctrico sola: órdenes 8/16/24/48 x f_rotor con jitter, silbido de inversor (Bb8 +-
    2 f_elec), ruido mecánico, AVAS bajo 20 km/h. accel = km/h ganados por segundo (sube v a lo largo de dur;
    <0 = regen). whine 0..1 escala lo tonal. tune: afina la reducción para que el orden 8 a la velocidad
    inicial caiga en Bb/Db/Eb/Ab (y sus quintas)."""
    dur = max(0.5, float(dur))
    n = dsp.n_of(dur)
    t = np.arange(n) / SR
    kmh = np.clip(float(speed_kmh) + float(accel) * t, 0.0, 200.0) * (1 + 0.012 * _mod(t, rng, 0.15))
    v = kmh / 3.6
    load = 0.5 + 0.35 * float(np.clip(float(accel) / 8.0, -1, 1.5)) + 0.08 * _mod(t, rng, 0.4)
    fs = _key_scale(max(1.0, float(speed_kmh) / 3.6), bool(tune))
    e = _ev(v, rng, amount=float(whine) / 0.5, load=load, avas=avas, inverter=inverter, mech=mech, f_scale=fs)
    y = _widen(_decor(e, rng, 0.12), rng, corr=float(np.clip(1.0 - 0.52 * float(width), 0.25, 0.95)))
    return Render(_finish(y, hp_hz, fin=0.05, fout=0.08), 0,
                  {"f8_start_hz": round(8 * 150.0 * float(speed_kmh) / 3.6 / 45.0 * fs, 1), "key_scale": round(fs, 4)})


@recipe("veh.avas_idle", family="vehicle", sync="start", kind="bed")
def avas_idle(dur, rng, *, level=0.5, note="Eb4", hum=0.5, breath_s=5.0, space="open_exterior", send_db=-16.0,
              hp_hz=120.0, standby=0.1, speed_kmh=None, tonal=0.3, **_):
    """EV detenido/listo: AVAS muy suave (3 parciales armónicos de `note`: Eb4-Eb5-Bb5 por defecto, 0/-8/-14 dB)
    con respiración lenta irregular y batido sutil, + zumbido eléctrico (Bb3 y armónicos) + portadora del
    inversor (Bb8) apenas audible + capa de reposo NO tonal (ventilador / bomba de refrigerante: siseo BP
    800-3000 Hz con AM 1/f lenta, y una portadora de inversor 26 dB debajo).
    level 0..1 = presencia del AVAS (peso 1.5*level: level=0 -> AVAS exactamente apagado).
    hum 0..1 = zumbido eléctrico tonal (Bb3). standby 0..1 = siseo de reposo (standby 1 = zumbido de hum 0.5
    +6 dB; el default 0.1 queda ~-30 dB bajo un AVAS de level 0.4). La cama se normaliza a RMS, así que lo que
    cuenta es la proporción: EV detenido, listo y silencioso (hiperreal) = level 0, hum 0.05-0.15,
    standby 0.4-0.8. speed_kmh (opcional): si se da, el AVAS es 0 a 0 km/h, sube a nivel pleno a 5 km/h, pleno
    hasta 20 km/h y se apaga a 24 (como la norma); sin speed_kmh suena pleno (comportamiento anterior).
    tonal 0..1 (default 0.3): <1 sintetiza AVAS y zumbido como ruido resonado (Q 8-15, deriva +-0.3 %) + silbido
    ancho de inversor 0.3-3 kHz, con los senos limpios ~15 dB debajo (tonal 0.3); tonal 1 = pila de senos original."""
    dur = max(0.5, float(dur))
    n = dsp.n_of(dur)
    t = np.arange(n) / SR
    f0 = _snap(_note_hz(note))
    lv = float(np.clip(level, 0.0, 1.0))
    # respiración: periodo ~breath_s con deriva + 1/f
    rate = 1.0 / max(1.0, float(breath_s)) * (1 + 0.3 * _mod(t, rng, 0.05))
    bph = TWO_PI * np.cumsum(rate) / SR + rng.uniform(0, TWO_PI)
    breath_db = 2.0 * (0.5 - 0.5 * np.cos(bph)) - 2.0 + 0.7 * _mod(t, rng, 0.12)
    br = 10 ** (breath_db / 20)
    fj = f0 * (1 + 0.003 * _mod(t, rng, 0.08))
    tn = float(np.clip(1.0 if tonal is None else tonal, 0.0, 1.0))
    legacy = tn >= 0.999
    # tonal < 1: cuerpo = ruido resonado (Q 8-15, deriva +-0.3 %) en las mismas frecuencias; los senos limpios
    # quedan tn^1.5 / sqrt(1 - tn^2) debajo (tonal 0.3 -> ~-15 dB). tonal 1 = pila de parciales original.
    g_sin = 1.0 if legacy else tn ** 1.5
    g_res = 0.0 if legacy else float(np.sqrt(max(0.0, 1.0 - tn * tn)))
    av = np.zeros(n)
    for k, d in ((1, 0.0), (2, -8.0), (3, -14.0)):
        a = 10 ** ((d + 1.5 * _mod(t, rng, 0.1 + 0.05 * k)) / 20)
        if legacy:
            tone = _nb_tone(fj * k, rng, -20, 1.5)
            beat = 0.35 * _nb_tone(fj * k + rng.uniform(0.25, 0.6) * k ** 0.5, rng, -20, 1.5)
            av += a * (tone + beat)
        else:
            fk = fj * k * (1 + 0.003 * _mod(t, rng, 0.35 + 0.1 * k))
            av += a * (g_sin * _nb_tone(fk, rng, -20, 1.5) + g_res * _res_tone(fk, rng, rng.uniform(8.0, 15.0)))
    nz = dsp.bp(rng.standard_normal(n), 300, 1500, 2) * (0.6 + 0.4 * br)
    av = av * br + 0.04 * nz
    if not legacy:
        # silbido ancho del inversor/motor en reposo (0.3-3 kHz, AM 1/f lenta): el AVAS real es ruido coloreado
        wh = dsp.bp(dsp.pink(n, rng), 300.0, 3000.0, 2)
        wh = wh / (np.sqrt(np.mean(wh ** 2)) + 1e-12) * 10 ** (2.0 * _mod(t, rng, 0.2) / 20)
        av = av + (1.0 - tn) * 0.32 * _rms(av) * wh * (0.7 + 0.3 * br)
    # zumbido eléctrico y portadora del inversor en reposo
    fh = _note_hz("Bb3") * (1 + 0.001 * _mod(t, rng, 0.1))
    if legacy:
        hm = sum(10 ** (d / 20) * _nb_tone(fh * k, rng, -16, 1.0) for k, d in ((1, 0.0), (2, -6.0), (3, -12.0)))
    else:
        hm = sum(10 ** (d / 20) * (g_sin * _nb_tone(fh * k, rng, -16, 1.0) + g_res * _res_tone(fh * k, rng, rng.uniform(10.0, 15.0)))
                 for k, d in ((1, 0.0), (2, -6.0), (3, -12.0)))
    hm *= 10 ** (1.0 * _mod(t, rng, 0.3) / 20)
    inv = _nb_tone(_note_hz("Bb8") * (1 + 0.001 * _mod(t, rng, 1.0)), rng, -8, 6.0) * 10 ** (1.5 * _mod(t, rng, 2.0) / 20)
    # capa de reposo no tonal: ventilador / bomba de refrigerante + portadora del inversor 26 dB debajo
    sb = float(max(0.0, standby or 0.0))
    stb = 0.0
    if sb > 0:
        fan = dsp.bp(dsp.pink(n, rng), 800.0, 3000.0, 2)
        fan = fan / (np.sqrt(np.mean(fan ** 2)) + 1e-12) * 10 ** (1.5 * _mod(t, rng, 0.15) / 20)
        car = _nb_tone(_note_hz("Bb8") * (1 + 0.001 * _mod(t, rng, 0.7)), rng, -8, 6.0)
        car = car / (np.sqrt(np.mean(car ** 2)) + 1e-12)
        stb = 0.18 * sb * (fan + 0.05 * car)
    w_av = 1.5 * lv
    if speed_kmh is not None:
        # AVAS real: mudo detenido, sube hasta nivel pleno a 5 km/h, pleno 5-20 km/h, se apaga por encima de 20
        vk = float(speed_kmh)
        w_av *= float(_ss(vk, 0.0, 5.0) * (1.0 - _ss(vk, 20.0, 24.0)))
    avas_on = w_av > 1e-6
    y = w_av * av + float(hum) * (0.22 * hm + 0.012 * inv) + stb
    y = _widen(_decor(y, rng, 0.12), rng, corr=0.52)
    y = _space(y, space, send_db)[:n]
    return Render(_finish(y, hp_hz, fin=0.08, fout=0.12), 0,
                  {"avas_f0_hz": round(f0, 2), "avas_on": bool(avas_on), "standby": sb})


@recipe("veh.wet_glide", family="vehicle", sync="peak", kind="event")
def wet_glide(dur, rng, *, speed_kmh=20.0, sizzle=0.6, closest_m=2.0, direction=1, peak_pos=0.5, ev=0.12,
              space="city_fog_street", send_db=-14.0, hp_hz=120.0, **_):
    """Deslizamiento lento sobre asfalto mojado en niebla: siseo de agua (sizzle 0..1), swish de
    desplazamiento, gotitas lanzadas por los tacos, apenas un susurro de motor EV. sync = paso más cercano."""
    sz = float(np.clip(sizzle, 0, 1.5))

    def droplets(t, v):
        N = len(t)
        rate = 180.0 * sz * np.clip(v / 6.0, 0, 2)
        pos = _poisson_pos(rate, rng, N)
        k = len(pos)
        g = _grains(N, pos, np.exp(rng.uniform(np.log(4000), np.log(9500), k)), rng.uniform(2e-4, 9e-4, k),
                    rng.lognormal(0, 0.5, k), rng, glide=0.15, attack=5e-5)
        return g

    out, sync, src, info = _straight_passby(dur, rng, speed_kmh=speed_kmh, closest_m=closest_m, direction=direction,
                                            surface="wet", ev=float(ev) / 0.25, height_m=0.4, peak_pos=peak_pos,
                                            aero=0.5, wetness=0.5 + 1.0 * sz, ground=0.68)
    n = info["n"]
    # gotitas: en una pasada aparte (también con Doppler/pan) para controlar su nivel
    t = info["t"]
    d_src = droplets(np.arange(n + 0) / SR, np.full(n, info["v_ms"]))
    d_src *= 0.18 * sz * info["src_rms"] / _rms(d_src)
    dd = dsp.passby(d_src, speed_ms=info["v_ms"], closest_m=info["closest"], t_closest=info["tpk"],
                    direction=info["direction"], height_m=0.3, ground=0.5)
    out = out + dd
    out = out + _spray_tail(n, rng, tpk=info["tpk"] + info["closest"] / C_SOUND, v_ms=info["v_ms"],
                            direction=info["direction"], amount=0.15 * sz * info["src_rms"])
    out = dsp.hp(out, hp_hz, 4) if hp_hz else out
    tail = int(0.3 * SR)
    out = _tail_fade(out, n - tail, tail)
    out = _space(out, space, send_db)
    return Render(_finish(out, None, fin=0.05, fout=0.1), sync, {"t_closest_s": round(sync / SR, 4)})


@recipe("veh.gravel_curve", family="vehicle", sync="peak", kind="event")
def gravel_curve(dur, rng, *, speed_kmh=25.0, wet=True, radius_m=14.0, closest_m=5.0, direction=1, peak_pos=0.5,
                 ev=0.3, slip=1.0, space="open_exterior", send_db=-16.0, hp_hz=120.0, **_):
    """Auto atravesando una curva de grava (cámara por fuera del ápice): granos ~ velocidad, más dispersión
    por deslizamiento lateral en el ápice, scrub del neumático, piedras contra el pasarrueda (plástico) y
    algún 'tink' metálico bajo el auto. wet: grava mojada (granos más cortos/oscuros + siseo). sync = ápice."""
    dur = max(0.6, float(dur))
    v_ms = max(1.0, float(speed_kmh) / 3.6)
    R = max(4.0, float(radius_m))
    d = max(1.0, float(closest_m))
    sgn = 1 if float(direction) >= 0 else -1
    tpk = float(np.clip(peak_pos, 0.1, 0.9)) * dur
    far = np.hypot(R * 2, d + R)
    pre = far / C_SOUND + 0.08
    P = int(pre * SR)
    n = dsp.n_of(dur)
    N = n + P
    t = (np.arange(N) - P) / SR
    slip_env = np.exp(-0.5 * ((t - tpk) / 0.35) ** 2)
    v = v_ms * (1 - 0.12 * np.exp(-0.5 * ((t - tpk) / 0.6) ** 2)) * (1 + 0.01 * _mod(t, rng, 0.5))
    s = np.cumsum(v) / SR
    s -= s[P + int(tpk * SR)]
    phi = np.clip(sgn * s / R, -np.pi * 0.95, np.pi * 0.95)
    x = R * np.sin(phi)
    y = d + R * (1 - np.cos(phi))
    wet_f = 0.3 if wet else 0.0
    boost = 1 + 1.2 * float(slip) * slip_env
    src = _source(v, rng, "gravel", "close", ev=float(ev) / 0.25, aero=0.6, wet=wet_f, boost=boost,
                  f_scale=_key_scale(v_ms))
    rs = _rms(src)
    # scrub lateral del neumático
    scrub = dsp.bp(rng.standard_normal(N), 900, 3200, 2) * slip_env * (1 + 0.4 * _bl_noise(N, rng, 25.0))
    src = src + scrub * (0.22 * float(slip) * rs / (_rms(scrub) + 1e-12))
    # piedras contra el pasarrueda (plástico) + tinks metálicos
    prate = (3.0 + 6.0 * slip_env) * np.clip(v / 7.0, 0, 1.5)
    pp = _poisson_pos(prate, rng, N)
    k = len(pp)
    tocks = _grains(N, pp, np.exp(rng.uniform(np.log(700), np.log(2200), k)), rng.uniform(3e-3, 8e-3, k),
                    rng.lognormal(0, 0.4, k), rng)
    tocks += _grains(N, pp + int(0.0004 * SR), np.exp(rng.uniform(np.log(1800), np.log(4200), k)),
                     rng.uniform(1.5e-3, 4e-3, k), 0.5 * rng.lognormal(0, 0.4, k), rng)
    mp = _poisson_pos(0.9 * np.clip(v / 7.0, 0, 1.5) * (1 + slip_env), rng, N)
    km = len(mp)
    f1 = np.exp(rng.uniform(np.log(2800), np.log(6500), km))
    tinks = _grains(N, mp, f1, rng.uniform(0.015, 0.04, km), rng.lognormal(0, 0.3, km), rng)
    tinks += _grains(N, mp, f1 * rng.uniform(2.3, 2.9, km), rng.uniform(0.006, 0.015, km), 0.4, rng)
    if np.abs(tocks).max() > 0:
        src = src + tocks * (0.9 * rs / (np.abs(tocks).max() + 1e-12)) * (1 - 0.3 * wet_f)
    if np.abs(tinks).max() > 0:
        src = src + tinks * (0.3 * rs / (np.abs(tinks).max() + 1e-12))
    st, rd = _propagate(src, x, y, z=0.4, mic_h=1.2, ground=_GROUND["gravel"])
    st = st[P:]
    rd = rd[P:]
    i_pk = int(round(tpk * SR))
    # piedritas lanzadas hacia afuera de la curva que caen alrededor de la cámara (después del ápice)
    kf = int(rng.integers(5, 13) * float(np.clip(slip, 0, 2)) * np.clip(v_ms / 7.0, 0.5, 1.5))
    if kf > 0:
        fp = np.clip((tpk + rng.uniform(0.12, 0.75, kf)) * SR, 0, n - 1).astype(np.int64)
        fpan = np.clip(-sgn * 0.3 + rng.uniform(-0.6, 0.6, kf), -0.9, 0.9)
        fa = rng.lognormal(0, 0.5, kf)
        ff = np.exp(rng.uniform(np.log(1300), np.log(4200), kf))
        fl = _grains(n, fp, ff, rng.uniform(2e-3, 5e-3, kf), fa, rng, pan=fpan)
        fl += _grains(n, fp, ff * rng.uniform(2.1, 2.7, kf), rng.uniform(1e-3, 2.5e-3, kf), 0.5 * fa, rng, pan=fpan)
        fl += 0.6 * _bursts(n, fp, rng, 900, 3500, 0.004, 0.012, fa, pan=fpan, attack=0.0005)
        st = st + fl * (0.22 * np.abs(st[i_pk - 2400:i_pk + 2400]).max() / (np.abs(fl).max() + 1e-12))
    sync = int(round((tpk + rd[min(i_pk, n - 1)] / C_SOUND) * SR))
    st = dsp.hp(st, hp_hz, 4) if hp_hz else st
    tail = int(0.25 * SR)
    st = _tail_fade(st, n - tail, tail)
    st = _space(st, space, send_db)
    return Render(_finish(st, None, fin=0.04, fout=0.1), sync, {"apex_s": round(sync / SR, 4), "radius_m": R})


@recipe("veh.snow_spray", family="vehicle", sync="transient", kind="event")
def snow_spray(dur, rng, *, intensity=1.0, lead_s=0.25, speed_kmh=35.0, direction=1, space="open_exterior",
               send_db=-20.0, hp_hz=120.0, **_):
    """Rueda lanzando nieve: rodado sobre nieve (LPF 2.5k) + crunch de compactación 0.5-3 kHz + spray
    turbulento HP 2-10 kHz (~0.4 s) + 'whoomph' de masa de nieve + partículas que caen (ticks 4-10 kHz) y
    terrones. sync = transiente (inicio del spray, a lead_s)."""
    dur = max(0.8, float(dur))
    n = dsp.n_of(dur)
    t = np.arange(n) / SR
    I = float(np.clip(intensity, 0.2, 2.0))
    sgn = 1 if float(direction) >= 0 else -1
    t0 = float(np.clip(lead_s, 0.05, 0.4 * dur))
    i0 = int(round(t0 * SR))
    v = max(2.0, float(speed_kmh) / 3.6) * (1 + 0.02 * _mod(t, rng, 0.5))
    # 1) rodado en nieve, el auto pasa: swell asimétrico centrado en el spray
    roll = _tire_roll(v, rng, "snow", "close", corr=0.5, particles=0.6)
    renv = np.where(t < t0, np.exp(-0.5 * ((t - t0) / 0.16) ** 2), np.exp(-0.5 * ((t - t0) / 0.45) ** 2))
    roll = roll * renv[:, None]
    # 2) crunch de compactación: arranca con la mordida de la rueda (pegado al spray) y se apaga
    gate = _ss(t, t0 - 0.015, t0 + 0.004)
    rate = I * gate * (900.0 * np.exp(-0.5 * ((t - t0 - 0.04) / 0.045) ** 2)
                       + 110.0 * np.exp(-0.5 * ((t - t0 - 0.1) / 0.3) ** 2))
    pos = _poisson_pos(rate, rng, n)
    k = len(pos)
    crunch = _grains(n, pos, np.exp(rng.uniform(np.log(500), np.log(3000), k)), rng.uniform(1e-3, 4e-3, k),
                     rng.lognormal(0, 0.5, k), rng, pan=rng.uniform(-0.35, 0.35, k))
    cpos = _poisson_pos(I * 45.0 * gate * np.exp(-0.5 * ((t - t0 - 0.05) / 0.07) ** 2), rng, n)
    crunch += 0.6 * _bursts(n, cpos, rng, 500, 2500, 0.01, 0.025, rng.lognormal(0, 0.4, len(cpos)),
                            pan=rng.uniform(-0.3, 0.3, len(cpos)))
    # 3) spray turbulento HP 2-10 kHz
    L = n - i0
    tt = np.arange(L) / SR
    att = np.clip(tt / 0.004, 0, 1) ** 2
    senv = att * (0.7 * np.exp(-tt / (0.16 * I ** 0.3)) + 0.3 * np.exp(-tt / 0.4))
    turb = np.clip(1 + 0.55 * _bl_noise(L, rng, 45.0), 0.15, None)
    raw = dsp.decorrelated_stereo(lambda r: r.standard_normal(L), rng, 0.3)
    raw = dsp.bp(raw, 2000, 10000, 2)
    fcs = np.exp(np.log(12000) + (np.log(6000) - np.log(12000)) * _ss(tt, 0.0, 0.45))
    raw = dsp.tv_filter(raw, fcs, "lowpass", 0.7)
    # cristales de hielo: chispeo denso 7-14 kHz que sigue a la envolvente del spray
    ice = _crackle(L, I * 2500.0 * senv, rng, 7000, 14000, q=9.0, n_res=6, pan_spread=0.7)
    raw = raw / (_rms(raw) + 1e-12) + ice * (0.28 / (_rms(ice) + 1e-12))
    spray_m = raw * (senv * turb)[:, None]
    pn = sgn * 0.55 * _ss(tt, 0.0, 0.4)
    gl, gr = dsp.pan_gains(pn)
    spray_m = np.stack([spray_m[:, 0] * gl * 1.41, spray_m[:, 1] * gr * 1.41], axis=1)
    spray = np.zeros((n, 2))
    spray[i0:] = spray_m
    # 4) whoomph de masa de nieve
    wh = dsp.bp(rng.standard_normal(L), 250, 800, 2) * np.clip(tt / 0.006, 0, 1) * np.exp(-tt / 0.07)
    whoomph = np.zeros((n, 2))
    whoomph[i0:] = dsp.pan(wh, 0.2 * sgn)
    # 5) partículas cayendo + terrones
    trate = I * 520.0 * _ss(t, t0 + 0.06, t0 + 0.16) * np.exp(-np.maximum(t - t0 - 0.12, 0) / 0.4)
    tp = _poisson_pos(trate, rng, n)
    kt = len(tp)
    ticks = _grains(n, tp, np.exp(rng.uniform(np.log(4000), np.log(10000), kt)), rng.uniform(2e-4, 8e-4, kt),
                    rng.lognormal(0, 0.5, kt), rng, pan=np.clip(sgn * 0.3 + rng.uniform(-0.6, 0.6, kt), -0.95, 0.95),
                    attack=5e-5)
    cl_pos = (np.sort(rng.uniform(t0 + 0.25, min(dur - 0.1, t0 + 0.95), max(2, int(5 * I)))) * SR).astype(int)
    clumps = _bursts(n, cl_pos, rng, 600, 1800, 0.012, 0.03, rng.uniform(0.4, 1.0, len(cl_pos)),
                     pan=rng.uniform(-0.7, 0.7, len(cl_pos)))
    pk = np.abs(spray).max() + 1e-12
    y = (spray / pk
         + whoomph * (0.35 / (np.abs(whoomph).max() + 1e-12))
         + crunch * (0.28 / (np.abs(crunch).max() + 1e-12))
         + roll * (0.02 / (_rms(roll) + 1e-12))
         + ticks * (0.2 / (np.abs(ticks).max() + 1e-12))
         + clumps * (0.12 / (np.abs(clumps).max() + 1e-12)))
    y = dsp.hp(y, hp_hz, 4) if hp_hz else y
    y = _tail_fade(y, n - int(0.2 * SR), int(0.2 * SR))
    y = _space(y, space, send_db)
    return Render(_finish(y, None, fin=0.03, fout=0.1), i0, {"spray_onset_s": round(t0, 4)})


@recipe("veh.water_splash", family="vehicle", sync="transient", kind="event")
def water_splash(dur, rng, *, intensity=1.0, space="tunnel", lead_s=0.12, wet_db=-12.0, direction=1,
                 speed_kmh=40.0, rear_wheel=True, hp_hz=100.0, **_):
    """Rueda atravesando agua: siseo mojado previo + slap 200-500 Hz (+ crack HP) + ráfaga HP 800 Hz-8 kHz
    (~0.4 s) + nube de burbujas Minnaert y gotas que vuelven a caer + salpicadura menor de la rueda trasera
    (batalla/v después), convolucionado en `space` (tunnel por defecto). sync = transiente (slap)."""
    dur = max(0.8, float(dur))
    n = dsp.n_of(dur)
    t = np.arange(n) / SR
    I = float(np.clip(intensity, 0.2, 2.0))
    sgn = 1 if float(direction) >= 0 else -1
    t0 = float(np.clip(lead_s, 0.03, 0.35 * dur))
    i0 = int(round(t0 * SR))
    v = max(2.0, float(speed_kmh) / 3.6)

    def splash(at, gain, rr):
        """Una salpicadura completa a partir del sample `at`."""
        L = n - at
        if L <= 16:
            return np.zeros((n, 2))
        tt = np.arange(L) / SR
        out = np.zeros((n, 2))
        # slap: golpe de agua 200-500 Hz + cuerpo 'plop' + crack HP corto
        sl = dsp.bp(rr.standard_normal(L), 200, 500, 2) * np.clip(tt / 0.0015, 0, 1) * np.exp(-tt / 0.03)
        pl = dsp.bp(rr.standard_normal(L), 140, 280, 2) * np.clip(tt / 0.004, 0, 1) * np.exp(-tt / 0.05)
        ck = dsp.hp(rr.standard_normal(L), 1500, 2) * np.clip(tt / 0.0008, 0, 1) * np.exp(-tt / 0.004)
        body = sl / (np.abs(sl).max() + 1e-12) + 0.5 * pl / (np.abs(pl).max() + 1e-12) + 0.45 * ck / (np.abs(ck).max() + 1e-12)
        out[at:] += dsp.pan(body, 0.1 * sgn)
        # ráfaga HP 800-8k (~0.4 s): lámina de agua que se rompe
        bl = 0.4 * I ** 0.3
        benv = np.clip(tt / 0.005, 0, 1) ** 2 * (0.6 * np.exp(-tt / (0.25 * bl)) + 0.4 * np.exp(-tt / (0.6 * bl)))
        turb = np.clip(1 + 0.5 * _bl_noise(L, rr, 30.0), 0.2, None)
        raw = dsp.decorrelated_stereo(lambda r: r.standard_normal(L), rr, 0.35)
        raw = dsp.bp(raw, 800, 8000, 2)
        raw = dsp.tv_filter(raw, np.exp(np.log(9000) + (np.log(4000) - np.log(9000)) * _ss(tt, 0, 0.5)), "lowpass", 0.7)
        burst = raw * (benv * turb)[:, None]
        burst *= 0.9 / (np.abs(burst).max() + 1e-12)
        gl, gr = dsp.pan_gains(sgn * 0.45 * _ss(tt, 0, 0.5))
        out[at:, 0] += burst[:, 0] * gl * 1.41
        out[at:, 1] += burst[:, 1] * gr * 1.41
        # burbujas (Minnaert: r 0.8-6 mm -> 0.55-4 kHz) en la masa de agua revuelta
        nb = int(rr.poisson(90 * I))
        bt = at + (np.abs(rr.exponential(0.12, nb)) * SR).astype(int) + int(0.01 * SR)
        rad = np.exp(rr.uniform(np.log(0.8e-3), np.log(6e-3), nb))
        fb = 3.26 / rad
        taub = np.clip(0.0025 * (1000.0 / fb) ** 0.5 * rr.uniform(0.7, 1.4, nb), 0.001, 0.012)
        bub = _grains(n, np.clip(bt, 0, n - 1), fb, taub, rr.lognormal(0, 0.4, nb) * (rad / 3e-3) ** 0.4, rr,
                      pan=np.clip(sgn * 0.2 + rr.uniform(-0.6, 0.6, nb), -0.9, 0.9), glide=rr.uniform(0.1, 0.35, nb))
        # gotas que vuelven a caer (impacto: tick + burbuja pequeña)
        nd = int(rr.poisson(160 * I))
        dt_ = at + (rr.uniform(0.12, 0.9, nd) ** 1.6 * SR * 0.9 + 0.12 * SR).astype(int)
        dt_ = np.clip(dt_, 0, n - 1)
        fd = np.exp(rr.uniform(np.log(1500), np.log(5500), nd))
        drops = _grains(n, dt_, fd, rr.uniform(1.5e-3, 5e-3, nd), rr.lognormal(0, 0.5, nd), rr,
                        pan=rr.uniform(-0.85, 0.85, nd), glide=rr.uniform(0.15, 0.5, nd))
        drops += 0.5 * _grains(n, dt_, np.exp(rr.uniform(np.log(6000), np.log(12000), nd)), rr.uniform(1.5e-4, 4e-4, nd),
                               rr.lognormal(0, 0.4, nd), rr, pan=rr.uniform(-0.85, 0.85, nd), attack=4e-5)
        out += bub * (0.5 / (np.abs(bub).max() + 1e-12))
        out += drops * (0.38 * min(I, 1.5) / (np.abs(drops).max() + 1e-12))
        return out * gain

    y = splash(i0, 1.0, rng)
    if rear_wheel:
        ir_ = i0 + int(2.75 / v * SR)
        y += splash(ir_, 0.5, rng)
    # siseo mojado: el auto rodando por agua antes / después
    roll = _tire_roll(np.full(n, v) * (1 + 0.02 * _mod(t, rng, 0.5)), rng, "wet", "close", wet=1.3, corr=0.4)
    renv = np.where(t < t0, 0.25 + 0.75 * _ss(t, 0, t0) ** 2, np.exp(-(t - t0) / 0.35))
    y += roll * renv[:, None] * (0.18 / (_rms(roll) + 1e-12))
    y = dsp.hp(y, hp_hz, 4) if hp_hz else y
    y = _tail_fade(y, n - int(0.15 * SR), int(0.15 * SR))
    if space and space not in ("none", "dry"):
        wet = dsp.convolve(y, dsp.ir_preset(str(space)), wet=10 ** (float(wet_db) / 20))
        wet[:n] += y
        y = wet
    return Render(_finish(y, None, fin=0.02, fout=0.15), i0, {"slap_s": round(t0, 4), "space": space})


@recipe("veh.tunnel_passby", family="vehicle", sync="peak", kind="event")
def tunnel_passby(dur, rng, *, speed_kmh=60.0, wet=True, closest_m=3.0, direction=1, ev=0.35, peak_pos=0.5,
                  width_m=9.0, height_m=5.5, send_db=-5.0, hp_hz=100.0, **_):
    """Pass-by dentro de un túnel: camino directo + fuentes imagen (pared cercana, pared lejana, techo),
    cada una con su Doppler/pan, piso mojado opcional, IR 'tunnel' (flutter de 41 ms integrado) y
    acumulación de graves 120-250 Hz propia del túnel. sync = paso más cercano."""
    surface = "wet" if wet else "dry"
    out, sync, src, info = _straight_passby(dur, rng, speed_kmh=speed_kmh, closest_m=closest_m,
                                            direction=direction, surface=surface, ev=float(ev) / 0.25,
                                            height_m=0.5, peak_pos=peak_pos, aero=1.0,
                                            wetness=1.0 if wet else 0.0, ground=0.6 if wet else 0.45)
    n = info["n"]
    d = info["closest"]
    wall_cam = 1.5
    # fuentes imagen: (distancia lateral efectiva, reflectancia, pan_scale)
    v_ms = info["v_ms"]
    tpk = info["tpk"]
    pre = np.sqrt((v_ms * max(tpk, dur - tpk)) ** 2 + 20 ** 2) / C_SOUND + 0.06
    P = int(pre * SR)
    # re-sintetizamos la fuente (no copia) con pre-roll para las imágenes, más oscura (paredes absorben HF)
    t = (np.arange(n + P) - P) / SR
    vv = v_ms * (1 + 0.008 * _mod(t, rng, 0.3))
    src_i = _source(vv, rng, surface, "close", ev=float(ev) / 0.25, aero=1.0, wet=1.0 if wet else 0.0,
                    particles=0.7, f_scale=_key_scale(v_ms))
    src_i = dsp.lp(src_i, 5000, 2)
    imgs = [(d + 2 * wall_cam, 0.55, 0.6),
            (max(d + 1, 2 * (float(width_m) - wall_cam) - d), 0.45, 0.75),
            (np.hypot(d, 2 * float(height_m) - 1.7), 0.4, 0.35)]
    for dist, refl, ps in imgs:
        im = dsp.passby(src_i, speed_ms=v_ms, closest_m=dist, t_closest=P / SR + tpk, direction=info["direction"],
                        height_m=0.5, ground=0.3, pan_scale=ps)[P:]
        out = out + im * refl * (d / dist)
    out = dsp.hp(out, hp_hz, 4) if hp_hz else out
    tail = int(0.3 * SR)
    out = _tail_fade(out, n - tail, tail)
    wetsig = dsp.convolve(out, dsp.ir_preset("tunnel"), wet=10 ** (float(send_db) / 20))
    wetsig = dsp.eq(wetsig, "peak", 170, 0.8, 3.5)
    wetsig = dsp.hp(wetsig, 90, 2)
    wetsig[:n] += out
    return Render(_finish(wetsig, None, fin=0.04, fout=0.2), sync,
                  {"t_closest_s": round(sync / SR, 4), "speed_ms": round(v_ms, 2)})


# =====================================================================================================
# audición de todo el módulo:  python -m sfx.recipes.vehicle
# =====================================================================================================

AUDITIONS = [
    # (receta, dur, params, at, gain, tag, seed)
    ("veh.wheel_spin", 1.55, {"speed_kmh": 40, "disc_whir": 0.5, "darken_at": 0.5}, 1.21, -10, "wheel_spin", 0),
    ("veh.approach", 0.8, {"speed_kmh": 40, "start_m": 60, "end_m": 5, "surface": "dry"}, 3.96, -10, "approach_avenue", 0),
    ("veh.wet_glide", 1.8, {"speed_kmh": 20, "sizzle": 0.6, "closest_m": 2.0}, 13.0, -8, "wet_glide", 0),
    ("veh.wet_glide", 1.8, {"speed_kmh": 20, "sizzle": 0.6, "closest_m": 2.0}, None, None, "wet_glide_s1", 1),
    ("veh.passby", 3.0, {"speed_kmh": 50, "closest_m": 4, "surface": "wet"}, 13.0, -10, "passby_wet", 0),
    ("veh.passby", 3.0, {"speed_kmh": 50, "closest_m": 4, "surface": "wet"}, None, None, "passby_wet_s1", 1),
    ("veh.gravel_curve", 1.4, {"speed_kmh": 25, "wet": True}, 16.0, -10, "gravel_curve", 0),
    ("veh.gravel_curve", 1.4, {"speed_kmh": 25, "wet": True}, None, None, "gravel_curve_s1", 1),
    ("veh.passby", 1.8, {"speed_kmh": 60, "closest_m": 3, "surface": "dry", "space": "rock_arch", "send_db": -10},
     16.5, -10, "passby_rock_arch", 0),
    ("veh.approach", 0.9, {"speed_kmh": 50, "start_m": 40, "end_m": 6}, 18.0, -10, "approach_headlights", 0),
    ("veh.approach", 0.6, {"speed_kmh": 70, "start_m": 30, "end_m": 4}, 25.46, -10, "approach_quick", 0),
    ("veh.approach", 1.2, {"speed_kmh": 50, "start_m": 40, "end_m": 5}, 30.29, -10, "approach_ex5", 0),
    ("veh.passby", 2.2, {"speed_kmh": 55, "closest_m": 5, "surface": "dry", "space": "forest", "send_db": -12},
     31.6, -10, "passby_forest", 0),
    ("veh.passby", 3.0, {"speed_kmh": 40, "closest_m": 3, "surface": "gravel", "space": "open_exterior"},
     None, None, "passby_gravel", 0),
    ("veh.passby", 3.0, {"speed_kmh": 40, "closest_m": 3, "surface": "snow"}, None, None, "passby_snow", 0),
    ("veh.onboard_roll", 1.6, {"speed_kmh": 45, "surface": "dry", "perspective": "onboard"}, 33.75, -16,
     "onboard_city", 0),
    ("veh.onboard_roll", 8.0, {"speed_kmh": 50, "surface": "dry", "perspective": "onboard"}, None, None,
     "onboard_long", 0),
    ("veh.onboard_roll", 8.0, {"speed_kmh": 70, "surface": "dry", "perspective": "interior"}, None, None,
     "interior_long", 0),
    ("veh.onboard_roll", 6.0, {"speed_kmh": 50, "surface": "wet", "perspective": "close"}, None, None,
     "close_wet_long", 0),
    ("veh.onboard_roll", 6.0, {"speed_kmh": 40, "surface": "wet", "perspective": "far", "space": "city_fog_street"},
     None, None, "far_wet_long", 0),
    ("veh.snow_spray", 1.6, {"intensity": 1.0}, 36.0, -8, "snow_spray", 0),
    ("veh.snow_spray", 1.6, {"intensity": 1.0}, None, None, "snow_spray_s1", 1),
    ("veh.tunnel_passby", 2.0, {"speed_kmh": 60, "wet": True}, 43.0, -10, "tunnel_passby", 0),
    ("veh.water_splash", 1.4, {"intensity": 1.0, "space": "tunnel"}, 43.0, -8, "water_splash", 0),
    ("veh.water_splash", 1.4, {"intensity": 1.0, "space": "tunnel"}, None, None, "water_splash_s1", 1),
    ("veh.ev_drive", 4.0, {"speed_kmh": 50, "accel": 0.0, "whine": 0.5}, 20.0, -22, "ev_drive_cruise", 0),
    ("veh.ev_drive", 4.0, {"speed_kmh": 20, "accel": 12.0, "whine": 0.7}, None, None, "ev_drive_accel", 0),
    ("veh.avas_idle", 4.0, {"level": 0.5}, 47.2, -16, "avas_idle", 0),
]


def _audition_all(only=None):
    import importlib
    import pkgutil
    import sys

    from .. import audition as au
    from .. import core

    # Ejecutado como __main__: retirar el registro duplicado e importar el módulo "real".
    for k in [k for k, v in core.RECIPES.items() if v["fn"].__module__ == "__main__"]:
        del core.RECIPES[k]
    importlib.import_module("sfx.recipes.vehicle")

    def _safe_load():
        from .. import recipes as pkg
        for m in pkgutil.iter_modules(pkg.__path__):
            try:
                importlib.import_module(f"{pkg.__name__}.{m.name}")
            except Exception as e:  # módulos ajenos rotos no deben impedir auditar éste
                print(f"[warn] no se pudo importar {m.name}: {e}", file=sys.stderr)
        return core.RECIPES

    au.load_all_recipes = _safe_load
    for name, dur, params, at, gain, tag, seed in AUDITIONS:
        if only and not any(o in tag or o == name for o in only):
            continue
        met = au.audition(name, dur, params, seed=seed, at=at, gain=gain, tag=tag)
        ctx = met.get("context", {}).get("sfx_vs_bed_db_by_band", {})
        print(f"{tag:22s} peak {met['peak_dbfs']:6.1f} rms {met['rms_dbfs']:6.1f} cen {met['centroid_hz']:6.0f} "
              f"lr {met.get('lr_corr')} sync {met['sync_s']} epk {met['energy_peak_s']} rise {met['sync_rise_db']} "
              f"clk {met['click_candidates']} ac {met.get('max_autocorr_0.1-5s')} dc {met['dc_db']}"
              + (f" | ctx hi {ctx.get('high5k-10k')} pres {ctx.get('pres2k-5k')} air {ctx.get('air10k+')}" if ctx else ""))


if __name__ == "__main__":
    import sys as _sys

    _audition_all(_sys.argv[1:] or None)
