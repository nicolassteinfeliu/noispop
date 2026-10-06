"""Familia DESIGNED (opción B "Cinemática / Sensorial"): sonido diseñado, misterioso, elegante, premium.

Referencia: films de lanzamiento de autos de alta gama. Nunca "trailer", nunca láseres sci-fi: aire, vidrio, luz
y una firma EV cálida ("EV hum"). Todo procedural (numpy/scipy), sin samples.

Principios
  * Capas separadas (transiente + cuerpo + textura + espacio) construidas por separado y combinadas al final.
  * Tonalidad: SOLO Bb Db Eb F Ab (+ octavas). `_note()` ajusta cualquier nota pedida a esa colección
    (única excepción: el add9 = C del pad Bbm(add9) de des.light_shaft). Los granos de "chispa" 6-14 kHz
    también se cuantizan a la colección (Ab8 Bb8 Db9 Eb9 F9 Ab9).
  * Tempo 118 BPM: negra 508 ms, corchea con punto 381 ms (ping-pong de los glints), semicorchea 127 ms.
  * FM de banda limitada (expansión de Bessel): las bandas laterales que superarían 19 kHz se descartan, así
    un glint F7 con ratio 3.5 e índice 4 no genera aliasing.
  * Nada estático: modulación 1/f acotada (`_mod`: paseo browniano + blanco, interpolado PCHIP, |m| <= 1) en
    ganancia (+-1-2 dB), corte (+-5-10 %) y pitch (+-0.1-0.3 %); cada evento se re-sintetiza desde el rng
    (detunes, decays, índices, tiempos, paneos), nunca se copia un buffer.
  * Espacio: IRs privadas generadas en STFT (`_smooth_ir`: RT dependiente de la frecuencia interpolado en log-f,
    sin las muescas de crossover que deja la suma LP/BP/HP de dsp.make_ir). "designed_hall" es una réplica
    con los mismos RT/predelay/corr que dsp.ir_preset("designed_hall") (5 s) para los momentos grandes y los
    envíos del catálogo; glass_room 1.8 s, air_hall 2 s, bloom_hall 3 s (muy decorrelada) para eventos breves.
    Envíos con HP 24 dB/oct (200-300 Hz: sin barro grave en las colas), colas recortadas con fade largo.
  * Campanas afinadas: parciales de campana (hum, tierce, quint, nominal...) sólo si caen en la colección +
    FM ratio 3 (bandas en octavas) para el brillo; las FM inarmónicas (ratio 3.5 vidrio) quedan para glints.
  * Ancho: los lados del bed están libres (side -14 dB) -> anchos que florecen, pares desafinados L/R,
    ping-pong; sin estéreo "fasey" en camas (correlación L/R 0.2-0.7).
  * Higiene: HP 120 Hz 24 dB/oct por defecto; cuerpos intencionales HP 70-90 Hz; sub de des.sub_impact sólo
    DC-block (fundamental <= 45 Hz, capas superiores con HP 140 Hz -> el contenido < 100 Hz es SOLO el seno).
    Bordes >= 3 ms. sync exacto: transient = primer sample del ataque (tras un pre-roll silencioso),
    peak = máximo de la envolvente de energía (RMS 40 ms) medido sobre la salida, end = último sample.

Audición de todo el módulo:  python -m sfx.recipes.designed [tag ...]
"""
from __future__ import annotations

import re

import numpy as np
from scipy import signal, special
from scipy.interpolate import PchipInterpolator

from .. import dsp
from ..core import SR, Render, recipe, stable_rng

TWO_PI = 2.0 * np.pi
BPM = 118.0
BEAT = 60.0 / BPM          # 0.508 s
DOT8 = 0.75 * BEAT         # 0.381 s
SIXTEENTH = 0.25 * BEAT    # 0.127 s

# =====================================================================================================
# notas (colección segura Bb Db Eb F Ab)
# =====================================================================================================

_PC = {"C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4, "E#": 5, "F": 5,
       "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}
_SAFE = (10, 1, 3, 5, 8)          # Bb Db Eb F Ab
_NOTE_RE = re.compile(r"^\s*([A-Ga-g])([#b]?)\s*(-?\d+)\s*$")


def _midi_hz(m) -> float:
    return 440.0 * 2.0 ** ((float(m) - 69.0) / 12.0)


def _note_midi(note, default="Bb4") -> float:
    """'Bb4' | 'A#4' | 466.16 (Hz) -> número MIDI (float)."""
    if note is None:
        note = default
    if isinstance(note, (int, float, np.integer, np.floating)):
        return 69.0 + 12.0 * np.log2(max(float(note), 1.0) / 440.0)
    m = _NOTE_RE.match(str(note))
    if m is None:
        try:
            return 69.0 + 12.0 * np.log2(max(float(note), 1.0) / 440.0)
        except ValueError:
            m = _NOTE_RE.match(default)
    name = m.group(1).upper() + m.group(2)
    return 12.0 * (int(m.group(3)) + 1) + _PC.get(name, 10)


def _snap(m: float, allow=_SAFE) -> int:
    """Nota MIDI más cercana dentro de la colección permitida."""
    r = int(round(m))
    cands = [r + d for d in range(-3, 4) if (r + d) % 12 in allow]
    return min(cands, key=lambda k: (abs(k - m), -k))


def _note(note, default="Bb4", allow=_SAFE) -> float:
    return _midi_hz(_snap(_note_midi(note, default), allow))


def _next_up(m: int, allow=_SAFE) -> int:
    k = int(m) + 1
    while k % 12 not in allow:
        k += 1
    return k


def _penta(lo: float, hi: float, allow=_SAFE) -> np.ndarray:
    return np.array([_midi_hz(m) for m in range(0, 136) if m % 12 in allow and lo <= _midi_hz(m) <= hi])


_SPARK_HZ = _penta(6000.0, 14000.0)      # Ab8 Bb8 Db9 Eb9 F9 Ab9
_DROP_HZ = _penta(1800.0, 4000.0)        # Bb6 Db7 Eb7 F7 Ab7 Bb7

# =====================================================================================================
# utilidades privadas
# =====================================================================================================


def _n(sec: float) -> int:
    return max(1, int(round(float(sec) * SR)))


def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


def _db(x):
    return 10.0 ** (np.asarray(x, np.float64) / 20.0)


def _ss(x, a, b):
    """Smoothstep 0->1 entre a y b."""
    u = np.clip((np.asarray(x, np.float64) - a) / (b - a + 1e-12), 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)


def _mod(n: int, rng, rate: float = 0.5, depth: float = 1.0, sr: float = SR) -> np.ndarray:
    """Modulador 1/f suave y acotado en [-depth, depth] (paseo browniano + blanco, PCHIP: sin sobrepicos).

    `rate` ~ frecuencia de los rasgos (Hz). Barato para señales largas (no usa convolución)."""
    n = int(n)
    k = max(6, int(n / sr * rate * 4) + 6)
    pts = np.cumsum(rng.standard_normal(k))
    pts = pts + 0.7 * rng.standard_normal(k) * (np.std(np.diff(pts)) + 1e-9)
    pts -= np.linspace(pts[0], pts[-1], k)
    pts -= pts.mean()
    pts /= np.abs(pts).max() + 1e-9
    if n < 2:
        return np.zeros(n)
    f = PchipInterpolator(np.linspace(0.0, 1.0, k), pts)
    if n > 8192 and k < n // 64:       # rasgos lentos: PCHIP a 1/16 de la tasa + interpolación lineal
        xs = np.linspace(0.0, 1.0, n // 16 + 2)
        return depth * np.interp(np.linspace(0.0, 1.0, n), xs, f(xs))
    return depth * f(np.linspace(0.0, 1.0, n))


def _attack(n: int, a_s: float) -> np.ndarray:
    """Rampa sin^2 0->1 en a_s segundos, 1 después."""
    env = np.ones(n)
    k = min(n, max(2, _n(a_s)))
    env[:k] = np.sin(np.linspace(0.0, 1.0, k) * np.pi / 2) ** 2
    return env


def _decay_env(n: int, tau: float, attack: float = 0.002) -> np.ndarray:
    return np.exp(-_t(n) / max(tau, 1e-4)) * _attack(n, attack)


def _ms(mid, side) -> np.ndarray:
    return np.stack([mid + side, mid - side], axis=1)


def _dnoise(n: int, rng, corr: float = 0.4, slope: float = -3.0) -> np.ndarray:
    """Ruido estéreo [n, 2] con correlación L/R ~ corr."""
    c, l, r = (dsp.colored(n, rng, slope) for _ in range(3))
    k, j = np.sqrt(max(corr, 0.0)), np.sqrt(max(1.0 - corr, 0.0))
    return np.stack([k * c + j * l, k * c + j * r], axis=1)


def _unit(x):
    return np.asarray(x, np.float64) / _rms(x)


def _balance(x: np.ndarray, p) -> np.ndarray:
    """Balance suave de una señal estéreo según p (-1..1, escalar o curva)."""
    x = dsp.stereo(x).copy()
    p = dsp.as_curve(p, len(x))
    x[:, 0] *= np.clip(1.0 - 0.8 * p, 0.0, 1.4)
    x[:, 1] *= np.clip(1.0 + 0.8 * p, 0.0, 1.4)
    return x


def _env_rms(x: np.ndarray, win: float = 0.04) -> np.ndarray:
    m = dsp.mono(x)
    h = max(3, _n(win))
    return np.sqrt(np.maximum(signal.fftconvolve(m * m, np.ones(h) / h, mode="same"), 0.0))


def _peak_near(x: np.ndarray, k: int, w: int, win: float = 0.04) -> int:
    """Sample del máximo de la envolvente de energía (RMS `win`) cerca de k (+-w)."""
    e = _env_rms(x, win)
    lo, hi = max(0, k - w), min(len(e), k + w + 1)
    if hi <= lo:
        return int(np.clip(k, 0, len(e) - 1))
    return lo + int(np.argmax(e[lo:hi]))


def _reshape(y: np.ndarray, target_db: np.ndarray, win: float = 0.08, amount: float = 0.85,
             keep_end: float = 0.06) -> np.ndarray:
    """Aplana la envolvente propia (RMS `win`, parcialmente) y le impone target_db (curva dB por sample).
    Los últimos keep_end s conservan su forma propia (el ataque invertido de un swell reverso)."""
    y = dsp.stereo(y)
    e = _env_rms(y, win) + 1e-9
    k = len(y) - _n(keep_end)
    if k > 0:
        e[k:] = e[k - 1]
    g = (e.max() / e) ** amount * _db(target_db)
    out = y * g[:, None]
    return out / (np.abs(out).max() + 1e-12)


# ------------------------------------------------------------------ FM de banda limitada

def _bessel_table(index: np.ndarray, ratio: float, fc_max: float, fmax: float = 19000.0):
    """Tabla [(k, J_k(I(t)))] para la expansión de Bessel; J se evalúa decimado e interpola (I es suave)."""
    n = len(index)
    I = np.maximum(index, 0.0)
    step = 32 if n > 4096 else 1
    xs = np.arange(0, n, step)
    Id = I[xs]
    full = np.arange(n)

    def ev(k):
        j = special.jv(k, Id)
        return j if step == 1 else np.interp(full, xs, j)

    table = [(0, ev(0))]
    kmax = int(np.ceil(I.max() + 5))
    for k in range(1, kmax + 1):
        jk = ev(k)
        if np.abs(jk).max() < 2e-4 and k > I.max():
            break
        table.append((k, jk))
    return table


def _fm_from_table(fc, ratio: float, table, n: int, phase_c: float = 0.0, phase_m: float = 0.0,
                   fmax: float = 19000.0) -> np.ndarray:
    """sum_k J_k sin(pc + k pm) por recurrencia compleja (e^{i(pc+k pm)} = e^{i pc} (e^{i pm})^k): un solo exp
    por operador en lugar de dos senos por banda lateral."""
    fcc = dsp.as_curve(fc, n)
    base = TWO_PI * np.cumsum(fcc) / SR
    ec = np.exp(1j * (base + phase_c))
    em = np.exp(1j * (ratio * base + phase_m))
    emc = np.conj(em)
    fhi = float(fcc.max())
    y = np.zeros(n)
    up, lo = ec.copy(), ec.copy()
    for k, jk in table:          # k consecutivos desde 0
        if k == 0:
            y += jk * ec.imag
            continue
        up *= em
        lo *= emc
        if fhi * (1.0 + k * ratio) < fmax:
            y += jk * up.imag
        if fhi * abs(1.0 - k * ratio) < fmax:
            y += (-1.0) ** k * jk * lo.imag
    return y


def _fm(fc, ratio: float, index, n: int, phase_c: float = 0.0, phase_m: float = 0.0) -> np.ndarray:
    """FM de 2 operadores sin aliasing: sin(pc + I sin(pm)) = sum_k J_k(I) sin(pc + k pm)."""
    I = dsp.as_curve(index, n)
    tab = _bessel_table(I, ratio, float(np.max(dsp.as_curve(fc, n))))
    return _fm_from_table(fc, ratio, tab, n, phase_c, phase_m)


def _fm_stereo(fc, n: int, rng, ratio: float, index, cents: float = 3.0, center: float = 0.6,
               side: float = 0.55) -> np.ndarray:
    """FM + copias desafinadas +-cents en L/R (batido lento y ancho)."""
    I = dsp.as_curve(index, n)
    fcc = dsp.as_curve(fc, n)
    tab = _bessel_table(I, ratio, float(fcc.max()))
    ph = rng.uniform(0, TWO_PI, 6)
    c = _fm_from_table(fcc, ratio, tab, n, ph[0], ph[1])
    lo = _fm_from_table(fcc * 2 ** (-cents / 1200), ratio, tab, n, ph[2], ph[3])
    hi = _fm_from_table(fcc * 2 ** (cents / 1200), ratio, tab, n, ph[4], ph[5])
    return np.stack([center * c + side * lo, center * c + side * hi], axis=1)


# ------------------------------------------------------------------ espacio

def _smooth_ir(rng, rt_low: float, rt_mid: float, rt_high: float, predelay_ms: float = 20.0, corr: float = 0.1,
               length_s: float | None = None, er_taps=None, er_gain_db: float = -8.0, damp_hz: float = 14000.0) -> np.ndarray:
    """IR estéreo sintética con decaimiento dependiente de la frecuencia aplicado en STFT (RT interpolado en
    log-f, sin bandas de crossover -> sin las muescas que dejan las sumas LP/BP/HP)."""
    length_s = length_s or max(0.3, 1.2 * max(rt_low, rt_mid, rt_high))
    n = int(length_s * SR)
    pre = int(predelay_ms * 1e-3 * SR)
    m = n - pre
    nper, hop = 1024, 256
    shared = rng.standard_normal(m + nper)
    chans = []
    for _ch in range(2):
        nz = np.sqrt(corr) * shared + np.sqrt(1.0 - corr) * rng.standard_normal(m + nper)
        f, tt, Z = signal.stft(nz, SR, nperseg=nper, noverlap=nper - hop)
        lf = np.log2(np.maximum(f, 30.0))
        rt = np.interp(lf, np.log2([150.0, 600.0, 2500.0, 7000.0, 18000.0]),
                       [rt_low, 0.5 * (rt_low + rt_mid), rt_mid, rt_high, 0.7 * rt_high])
        G = np.exp(-6.91 * tt[None, :] / rt[:, None]) / np.sqrt(1.0 + (f[:, None] / damp_hz) ** 2)
        _, y = signal.istft(Z * G, SR, nperseg=nper, noverlap=nper - hop)
        y = y[:m]
        t = np.arange(m) / SR
        y *= np.clip(t / (0.012 + 0.02 * rt_mid), 0.0, 1.0) ** 1.5
        ir = np.zeros(n)
        ir[pre:] = y
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-12
        for ms, gdb in er_taps or []:
            k = pre + int(ms * (1 + rng.uniform(-0.08, 0.08)) * 1e-3 * SR)
            if 0 <= k < n:
                ir[k] += 10 ** ((gdb + er_gain_db) / 20) * rng.choice([-1.0, 1.0]) * 0.5
        chans.append(ir)
    ir = np.stack(chans, axis=1)
    k = int(0.15 * n)
    ir[n - k:] *= (np.cos(np.linspace(0.0, 1.0, k) * np.pi / 2) ** 2)[:, None]
    return ir / (np.sqrt(np.sum(ir ** 2) / 2) + 1e-12)


_PRIV_IR = {
    # réplica de dsp.ir_preset("designed_hall") (mismos RT/predelay/corr) generada sin muescas de crossover
    "designed_hall": dict(rt_low=5.0, rt_mid=5.0, rt_high=3.5, predelay_ms=35, corr=0.05, length_s=4.5),
    "glass_room": dict(rt_low=1.3, rt_mid=1.8, rt_high=1.4, predelay_ms=14, corr=0.08,
                       er_taps=[(9, -7), (15, -9), (23, -11)]),
    "air_hall": dict(rt_low=1.6, rt_mid=2.0, rt_high=1.5, predelay_ms=22, corr=0.06),
    "bloom_hall": dict(rt_low=2.6, rt_mid=3.0, rt_high=2.4, predelay_ms=28, corr=0.0),
}
_IRC: dict = {}


def _ir(name: str) -> np.ndarray:
    if name not in _PRIV_IR:
        return dsp.ir_preset(name)
    if name not in _IRC:  # recurso fijo y determinista (como dsp.ir_preset), no depende del rng del evento
        _IRC[name] = _smooth_ir(stable_rng("designed-ir", name), **_PRIV_IR[name])
    return _IRC[name]


def _endfade(x, frac: float = 0.12, min_s: float = 0.02):
    """Fade coseno al final de una capa (nunca cortar una capa en seco)."""
    y = np.array(x, dtype=np.float64, copy=True)
    n = len(y)
    k = min(n, max(_n(min_s), int(frac * n)))
    w = np.cos(np.linspace(0.0, 1.0, k) * np.pi / 2) ** 2
    y[n - k:] *= w[:, None] if y.ndim == 2 else w
    return y


def _space(x, ir: str = "air_hall", send_db: float = -14.0, hp_send: float = 200.0, lp_send: float | None = None,
           dry: float = 1.0, hp_order: int = 4) -> np.ndarray:
    """dry + envío a IR (con cola). hp_send (24 dB/oct por defecto) y lp_send filtran sólo el envío."""
    x = _endfade(dsp.stereo(x), 0.0, 0.03)
    s = x
    if hp_send:
        s = dsp.hp(s, hp_send, hp_order)
    if lp_send:
        s = dsp.lp(s, lp_send, 2)
    wet = dsp.convolve(s, _ir(ir), wet=float(_db(send_db)))
    wet[:len(x)] += dry * x
    return wet


def _pingpong(x, delay: float = DOT8, fb: float = 0.35, lpf: float = 6000.0, floor_db: float = -48.0,
              first: int = 1) -> np.ndarray:
    """Delay ping-pong a tempo con LPF dentro del lazo (cada repetición más oscura)."""
    x = dsp.stereo(x)
    d = _n(delay)
    reps = max(1, int(np.ceil(floor_db / (20 * np.log10(max(fb, 1e-3))))))
    out = np.zeros((len(x) + d * reps, 2))
    out[:len(x)] += x
    sos = dsp.butter_sos(2, lpf, "lowpass")
    cur = dsp.mono(x)
    for r in range(1, reps + 1):
        cur = signal.sosfilt(sos, cur) * fb
        ch = (r + (0 if first > 0 else 1)) % 2
        out[r * d:r * d + len(cur), ch] += 0.92 * cur
        out[r * d:r * d + len(cur), 1 - ch] += 0.22 * cur
    return out


def _trim(x, keep: int, max_len: float | None = None, floor_db: float = -72.0, fade_frac: float = 0.35) -> np.ndarray:
    """Recorta la cola (bajo floor_db del pico o en max_len s), con fade coseno que nunca empieza antes de keep."""
    x = np.asarray(x, np.float64)
    a = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    pk = a.max() + 1e-12
    idx = np.nonzero(a > pk * 10 ** (floor_db / 20))[0]
    end = int(idx[-1] + 1) if len(idx) else len(x)
    end = max(end, keep)
    if max_len is not None:
        end = min(end, max(keep, _n(max_len)))
    end = min(end, len(x))
    y = x[:end].copy()
    k = int(max(_n(0.003), fade_frac * (end - keep))) if end - keep > _n(0.003) else _n(0.003)
    k = min(k, len(y))
    w = np.cos(np.linspace(0.0, 1.0, k) * np.pi / 2) ** 2
    y[len(y) - k:] *= w[:, None] if y.ndim == 2 else w
    return y


def _finish(x, hp_hz: float | None = 120.0, order: int = 4, fin: float = 0.003, fout: float = 0.003) -> np.ndarray:
    y = dsp.stereo(np.nan_to_num(np.asarray(x, np.float64)))
    if hp_hz:
        y = signal.sosfilt(dsp.butter_sos(order, hp_hz, "highpass"), y, axis=0)
    return dsp.fade(y, fin, fout)


# ------------------------------------------------------------------ capas compartidas

def _sparkle(n: int, rng, rate0: float, tau: float, t0: float = 0.0, pan_w: float = 0.9,
             dur_rng=(0.010, 0.030)) -> np.ndarray:
    """Chispas: senos cortos 6-14 kHz (cuantizados a la colección), Poisson con tasa decreciente."""
    out = np.zeros((n, 2))
    T = n / SR
    if rate0 <= 0 or T - t0 <= 0.005:
        return out
    times = dsp.poisson_times(T - t0, lambda tt: rate0 * np.exp(-(tt - t0) / max(tau, 1e-3)), rng, t0)
    for ts in times:
        f = rng.choice(_SPARK_HZ) * (1.0 + rng.uniform(-0.002, 0.002))
        gd = rng.uniform(*dur_rng)
        m = _n(gd)
        tt = _t(m)
        env = _attack(m, 0.0008) * np.exp(-tt / (gd / 3.0)) * (1.0 - _ss(tt, 0.8 * gd, gd))
        g = np.sin(TWO_PI * f * tt + rng.uniform(0, TWO_PI)) * env
        dsp.mix_into(out, dsp.pan(g, rng.uniform(-pan_w, pan_w)), int(ts * SR), float(_db(rng.uniform(-9, 0))))
    return out


def _glint_core(n: int, rng, f: float, ratio: float = 3.5, decay: float = 1.0, index: float = 4.0,
                cents: float = 3.0, tick: float = 0.12, idx_tau: float = 0.15, attack: float = 0.0012) -> np.ndarray:
    """Campana/vidrio FM: índice index*exp(-t/0.15)+0.3, decay tau, copias +-cents L/R, tick de vidrio."""
    t = _t(n)
    I = index * (1.0 + rng.uniform(-0.1, 0.1)) * np.exp(-t / idx_tau) + 0.3
    tau = decay * (1.0 + rng.uniform(-0.1, 0.1))
    amp = np.exp(-t / tau) * _attack(n, attack)
    fcur = f * (1.0 + 0.001 * _mod(n, rng, 1.5))
    st = _fm_stereo(fcur, n, rng, ratio, I, cents) * amp[:, None]
    if tick > 0:
        m = min(n, _n(0.004))
        tk = dsp.hp(rng.standard_normal(m), 5000, 4) * np.exp(-_t(m) / 0.0008) * _attack(m, 0.0003)
        st[:m] += tick * np.stack([tk, np.roll(tk, 3)], axis=1)
    return _endfade(st, 0.15)


def _sub_core(n: int, rng, f_start: float, f_end: float, decay: float, attack: float = 0.005,
              drive: float = 1.5, p_tau: float = 0.12, lp_hz: float | None = None) -> np.ndarray:
    """Seno con caída de pitch f = fe + (fs-fe) exp(-t/0.12), ataque 5 ms, decay, tanh drive. Mono."""
    t = _t(n)
    fs = f_start * (1.0 + rng.uniform(-0.03, 0.03))
    fe = f_end * (1.0 + rng.uniform(-0.01, 0.01))
    tp = p_tau * (1.0 + rng.uniform(-0.1, 0.1))
    f = (fe + (fs - fe) * np.exp(-t / tp)) * (1.0 + 0.002 * _mod(n, rng, 2.0))
    x = np.sin(TWO_PI * np.cumsum(f) / SR)
    tau = max(decay, 0.1) / 3.2 * (1.0 + rng.uniform(-0.08, 0.08))
    env = np.exp(-t / tau) * _attack(n, attack)
    t_end = min(n / SR, max(1.9 * decay, 0.3))
    env *= 1.0 - _ss(t, 0.7 * t_end, t_end)
    y = dsp.soft_clip(x * env, drive)
    if lp_hz:   # capas sub dentro de eventos del bus DES: sólo el fundamental (los armónicos de tanh 3f/5f
        y = signal.sosfilt(dsp.butter_sos(4, lp_hz, "lowpass"), y)   # caerían fuera de la colección)
    return _endfade(y, 0.0, 0.05)


_BODY_HZ = (155.56, 174.61, 207.65, 233.08, 277.18, 311.13, 349.23, 415.30)   # Eb3..Ab4 (colección)


def _body_modal(n: int, rng, k: int = 5, tau_rng=(0.05, 0.2), exc_ms: float = 5.0, freqs=_BODY_HZ) -> np.ndarray:
    """Cuerpo 150-420 Hz: banco modal (fase física sin(wt)) excitado por un golpe blando."""
    sel = rng.choice(len(freqs), size=min(k, len(freqs)), replace=False)
    fr = np.array(freqs)[sel] * (1.0 + rng.uniform(-0.015, 0.015, len(sel)))
    taus = rng.uniform(*tau_rng, len(sel))
    amps = rng.uniform(-10.0, 0.0, len(sel))
    y = dsp.modal(n, fr, taus, amps)
    y = signal.oaconvolve(y, dsp.soft_exciter(exc_ms / 1000.0))[:n]
    return y / (np.abs(y).max() + 1e-12)


def _impact_parts(n: int, rng, brightness: float = 0.5, low: float = 1.0):
    """Impacto blando SIN sub: (núcleo mono [cuerpo + thump + soporte 90-120 Hz + snap], aire estéreo)."""
    t = _t(n)
    b = float(np.clip(brightness, 0, 1))
    body = _body_modal(n, rng, 5, (0.06, 0.24), rng.uniform(5, 9))
    thump = dsp.bp(rng.standard_normal(n), 150, 420, 2) * _decay_env(n, rng.uniform(0.05, 0.09), 0.003)
    thump /= np.abs(thump).max() + 1e-12
    fl = 116.54 * (1 + 0.189 * np.exp(-t / 0.03)) * rng.uniform(0.995, 1.005)    # cae Db3 -> Bb2
    sup = np.sin(TWO_PI * np.cumsum(fl) / SR) * _decay_env(n, rng.uniform(0.09, 0.13), 0.004)
    m = min(n, _n(0.006))
    snap = np.zeros(n)
    snap[:m] = dsp.bp(rng.standard_normal(m), 1200, 3800, 2) * np.exp(-_t(m) / 0.0015) * _attack(m, 0.0004)
    snap /= np.abs(snap).max() + 1e-12
    core = 0.8 * body + 0.55 * thump + 0.5 * low * sup + (0.3 + 0.2 * b) * snap
    air = dsp.hp(_dnoise(n, rng, 0.3, -1.5), 2200, 2)
    air = dsp.lp(air, 5000 + 9000 * b, 2)
    ae = _attack(n, 0.003) * (0.7 * np.exp(-t / (0.06 + 0.06 * b)) + 0.3 * np.exp(-t / 0.35))
    air = air / (np.abs(air).max() + 1e-12) * ae[:, None] * (0.4 + 0.45 * b)
    return _endfade(core, 0.1), _endfade(air, 0.1)


def _bell(f: float, n: int, rng, index: float = 3.0, idx_tau: float = 0.25, decay: float = 2.2,
          strike: float = 1.0) -> np.ndarray:
    """Campana afinada en la tonalidad. Parciales de campana (hum 0.5, prime, tierce m3/M3, quint, nominal,
    12a, doble octava) con inarmonicidad leve (+-0.3 %) y decays propios, SÓLO los que caen en la colección;
    + FM ratio 3 (bandas en octavas) para el brillo del golpe; + golpe metálico inarmónico (FM 1.4) de ~25 ms.
    Pares +-2 cents L/R. Estéreo."""
    t = _t(n)
    m0 = _snap(_note_midi(f))
    st = np.zeros((n, 2))
    tierce = next((iv for iv in (3, 4) if (m0 + iv) % 12 in _SAFE), None)
    parts = [(-12, -6.0, 1.4), (0, 0.0, 1.0), (tierce, -4.0, 0.8), (7, -7.0, 0.6), (12, -3.0, 0.5),
             (19, -10.0, 0.35), (24, -12.0, 0.25)]
    for iv, gdb, dk in parts:
        if iv is None or (m0 + iv) % 12 not in _SAFE or f * 2 ** (iv / 12) > 15000:
            continue
        fr = f * 2 ** (iv / 12) * (1.0 + rng.uniform(-0.003, 0.003))
        env = np.exp(-t / (decay * dk * rng.uniform(0.9, 1.1))) * _attack(n, 0.0015)
        for side, cents in ((0, -2.0), (1, 2.0)):
            st[:, side] += float(_db(gdb)) * env * np.sin(TWO_PI * fr * 2 ** (cents / 1200) * t + rng.uniform(0, TWO_PI))
    I = 0.35 * index * (1 + rng.uniform(-0.1, 0.1)) * np.exp(-t / idx_tau) + 0.2   # J2 bajo: dominan 2f y 4f
    st += 0.5 * _fm_stereo(f * (1 + 0.0008 * _mod(n, rng, 1.0)), n, rng, 3.0, I, 2.0) * \
        (np.exp(-t / (0.6 * decay)) * _attack(n, 0.0015))[:, None]
    if strike > 0:
        k = min(n, _n(0.12))
        tk = _t(k)
        ms = _fm_stereo(f, k, rng, 1.4, 3.0 * np.exp(-tk / 0.02), 4.0) * (np.exp(-tk / 0.025) * _attack(k, 0.001))[:, None]
        st[:k] += float(strike) * float(_db(-14.0)) * ms
    return _endfade(st, 0.12)


def _pure_bell(f: float, n: int, rng, decay: float = 1.5, attack: float = 0.003,
               partials=((1.0, 0.0, 1.0), (2.0, -5.0, 0.6), (3.0, -11.0, 0.4), (4.0, -14.0, 0.3))) -> np.ndarray:
    """Campana 'pura' en la tonalidad: parciales armónicos (sólo los que caen en la colección) en pares
    desafinados +-2 cents L/R. Para resoluciones (sin bandas laterales inarmónicas)."""
    t = _t(n)
    m0 = _note_midi(f)
    y = np.zeros((n, 2))
    for r, gdb, dk in partials:
        if f * r > 15000 or _snap(m0 + 12 * np.log2(r)) != int(round(m0 + 12 * np.log2(r))):
            continue
        env = np.exp(-t / (decay * dk * rng.uniform(0.9, 1.1))) * _attack(n, attack)
        for side, cents in ((0, -2.0), (1, 2.0)):
            y[:, side] += float(_db(gdb)) * env * np.sin(TWO_PI * f * r * 2 ** (cents / 1200) * t + rng.uniform(0, TWO_PI))
    return _endfade(y, 0.12)


def _drop(rng, note: float, tau: float) -> np.ndarray:
    """Gota tonal (Minnaert): seno amortiguado con glissando ascendente que termina en `note` + tick blando."""
    m = _n(tau * 7)
    t = _t(m)
    f = note / 1.08 * (1.0 + 0.08 * (1.0 - np.exp(-t / (tau * 0.8))))
    y = np.sin(TWO_PI * np.cumsum(f) / SR) * np.exp(-t / tau) * _attack(m, 0.0006)
    k = min(m, _n(0.0015))
    tick = np.zeros(m)
    tick[:k] = dsp.hp(rng.standard_normal(k), 3000, 4) * np.linspace(1, 0, k)
    return dsp.fade(y + 0.12 * tick, 0.0005, 0.004)


def _drops(n: int, rng, rate0: float = 12.0, tau_rate: float = 0.5, t0: float = 0.03, level: float = 1.0) -> np.ndarray:
    """Gotas tonales (Minnaert, glissando ascendente que termina en una nota de la colección)."""
    out = np.zeros((n, 2))
    T = n / SR
    times = dsp.poisson_times(max(0.01, T - t0 - 0.2), lambda tt: rate0 * np.exp(-(tt - t0) / tau_rate), rng, t0)
    for ts in times:
        g = _drop(rng, rng.choice(_DROP_HZ), rng.uniform(0.018, 0.05))
        dsp.mix_into(out, dsp.pan(g, rng.uniform(-0.8, 0.8)), int(ts * SR), level * float(_db(rng.uniform(-9, 0))))
    return out


# =====================================================================================================
# des.whoosh
# =====================================================================================================

_WH = {
    #        centro (inicio, pico, final) Hz, Q, HP, IR, envío, tono, flanger, aire, ancho (ini, pico, fin), pendiente
    "air": dict(f=(1500, 5200, 2600), q=0.95, hp=1000, ir="air_hall", rev=-19, tone=0.0, comb=0.18, air=0.75,
                w=(0.35, 1.35, 1.0), slope=-1.5, a_pow=2.2, rel_k=4.5, note="F6"),
    "body": dict(f=(280, 1250, 400), q=1.1, hp=120, ir="air_hall", rev=-19, tone=0.12, comb=0.22, air=0.5,
                 w=(0.35, 1.4, 1.0), slope=-3.0, a_pow=2.0, rel_k=4.0, note="F5"),
    "tonal": dict(f=(550, 2300, 800), q=1.05, hp=120, ir="designed_hall", rev=-18, tone=1.0, comb=0.15, air=0.4,
                  w=(0.3, 1.25, 1.0), slope=-2.5, a_pow=2.0, rel_k=4.0, note="F5"),
    "spin": dict(f=(800, 3200, 1200), q=1.3, hp=150, ir="air_hall", rev=-20, tone=0.25, comb=0.45, air=0.45,
                 w=(0.4, 1.1, 0.9), slope=-2.0, a_pow=1.8, rel_k=3.5, note="Bb5"),
    "deep": dict(f=(110, 640, 170), q=0.95, hp=70, ir="designed_hall", rev=-16, tone=0.12, comb=0.12, air=0.2,
                 w=(0.3, 1.1, 0.85), slope=-4.0, a_pow=2.6, rel_k=3.0, note="Bb3"),
    "flutter": dict(f=(450, 1700, 650), q=1.0, hp=150, ir="air_hall", rev=-19, tone=0.0, comb=0.0, air=0.4,
                    w=(0.4, 1.25, 1.0), slope=-2.5, a_pow=2.0, rel_k=4.0, note="F5"),
}


def _swell_env(n: int, peak_pos: float = 0.65, a_pow: float = 2.2, rel_k: float = 4.0, rel_pow: float = 1.2,
               smooth_s: float = 0.012) -> np.ndarray:
    """Envolvente asimétrica: subida convexa (exp) hasta peak_pos, caída rápida, pico redondeado."""
    k = int(np.clip(peak_pos, 0.02, 0.98) * n)
    u = np.linspace(0.0, 1.0, k, endpoint=False)
    up = np.expm1(a_pow * u) / np.expm1(a_pow)
    v = np.linspace(0.0, 1.0, n - k)
    down = np.exp(-rel_k * v) * (1.0 - v) ** rel_pow
    env = np.concatenate([up, down])
    w = max(3, _n(smooth_s))
    if w < n // 4:
        ker = np.hanning(w)
        env = signal.fftconvolve(env, ker / ker.sum(), mode="same")
    return np.clip(env / (env.max() + 1e-12), 0.0, 1.0)


def _fc_curve(n: int, kp: int, f0: float, f1: float, f2: float, up_pow: float = 1.3, down_pow: float = 0.6) -> np.ndarray:
    kp = int(np.clip(kp, 1, n - 1))
    up = np.linspace(0.0, 1.0, kp, endpoint=False) ** up_pow
    down = np.linspace(0.0, 1.0, n - kp) ** down_pow
    lf = np.concatenate([np.log(f0) + (np.log(f1) - np.log(f0)) * up, np.log(f1) + (np.log(f2) - np.log(f1)) * down])
    return np.exp(lf)


def _whuff(rng, fc: float) -> np.ndarray:
    """Un aletazo: 'whuff' de ruido BP + crujido de plumas HF justo después del golpe de ala."""
    m = _n(0.11)
    t = _t(m)
    fc = fc * rng.uniform(0.85, 1.15)
    a_s = rng.uniform(0.010, 0.02)
    env = _ss(t, 0, a_s) * np.exp(-np.maximum(t - a_s, 0) / rng.uniform(0.022, 0.04))
    body = dsp.bp(rng.standard_normal(m), fc / 1.6, min(fc * 1.6, 20000), 2) * env
    fe = _ss(t, 0.008, 0.02) * np.exp(-np.maximum(t - 0.02, 0) / 0.025)
    crack = dsp.velvet(m, rng, rng.uniform(900, 2200))
    crack = dsp.hp(dsp.lp(crack, 9000, 2), 2800, 2) * fe
    g = body / (np.abs(body).max() + 1e-12) + 0.35 * crack / (np.abs(crack).max() + 1e-12)
    return dsp.fade(g, 0.002, 0.01)


def _wing_flutter(n: int, rng, env: np.ndarray, pan_c: np.ndarray, bs: float = 1.0, birds: int = 4,
                  rate=(4.5, 8.0)) -> np.ndarray:
    """Aleteo granular: varias 'alas' con su propia tasa (jitter 7 %), paneo y timbre, bajo la envolvente."""
    out = np.zeros((n, 2))
    T = n / SR
    for _b in range(birds):
        r = rng.uniform(*rate)
        p_off = rng.uniform(-0.4, 0.4)
        lvl = float(_db(rng.uniform(-5, 0)))
        fcb = rng.uniform(550, 1200) * bs
        t = rng.uniform(0, 1.0 / r)
        while t < T:
            i = int(t * SR)
            a = env[min(i, n - 1)]
            if a > 0.03:
                g = _whuff(rng, fcb)
                p = float(np.clip(pan_c[min(i, n - 1)] + p_off, -1, 1))
                dsp.mix_into(out, dsp.pan(g, p), i, lvl * a ** 1.2)
            t += (1.0 / r) * (1.0 + 0.07 * rng.standard_normal())
    return out / _rms(out) * _rms(env)


@recipe("des.whoosh", family="designed", sync="peak", kind="event")
def whoosh(dur, rng, *, style="air", direction=1, peak_pos=0.65, brightness=0.5, note=None, tone=None,
           comb=None, reverb_db=None, tail=1.0, rot_hz=9.0, **_):
    """Whoosh: ruido rosa -> pasabanda variable (~1 oct) con envolvente asimétrica, flanger 5->0.6->3 ms,
    componente tonal que cae (de la nota de la colección superior a `note`) en el pico, paneo según direction,
    ancho que florece en el pico, cola de reverb. style: air|body|tonal|spin|deep|flutter. sync = pico."""
    style = str(style) if str(style) in _WH else "air"
    P = _WH[style]
    dur = float(max(0.15, dur))
    n = _n(dur)
    kp = int(np.clip(peak_pos, 0.05, 0.95) * n)
    b = float(np.clip(brightness, 0.0, 1.0))
    bs = 2.0 ** ((b - 0.5) * 1.6)
    f0 = P["f"][0] * 2 ** ((b - 0.5) * 0.8)
    f1 = min(14000.0, P["f"][1] * bs)
    f2 = P["f"][2] * 2 ** ((b - 0.5) * 0.8)
    tt = (np.arange(n) - kp) / SR
    env = _swell_env(n, kp / n, P["a_pow"], P["rel_k"])
    fc = _fc_curve(n, kp, f0, f1, f2) * (1.0 + 0.07 * _mod(n, rng, 1.5))
    gm = _db(1.2 * _mod(n, rng, 3.0) + 0.6 * _mod(n, rng, 0.7))
    if style == "spin":   # corte modulado a la tasa de rotación (desacelera, con jitter)
        rate = float(rot_hz) * np.linspace(1.0, 0.7, n) * (1.0 + 0.06 * _mod(n, rng, 1.0))
        ph = TWO_PI * np.cumsum(rate) / SR + rng.uniform(0, TWO_PI)
        lobe = (0.5 * (1.0 + np.sin(ph))) ** 1.6
        fc = fc * 2.0 ** (0.9 * (lobe - 0.4))
        gm = gm * (0.7 + 0.4 * lobe)
    fc = np.clip(fc, 40.0, 17000.0)
    nz = np.stack([dsp.colored(n, rng, P["slope"]), dsp.colored(n, rng, P["slope"])], axis=1)
    nz = dsp.tv_filter(nz, fc, "bandpass", q=P["q"], stages=2)
    nz /= nz.std(axis=0, keepdims=True) + 1e-12
    mid = nz[:, 0] * env * gm
    side = nz[:, 1] * env * gm
    cm = P["comb"] if comb is None else float(comb)
    if cm > 0:
        dl = _fc_curve(n, kp, 0.0048, 0.0006, 0.0032, 1.0, 0.8) * (1.0 + 0.08 * _mod(n, rng, 1.0))
        mid = dsp.comb(mid, dl, fb=0.45, mix=cm)
        side = dsp.comb(side, dl * 1.13, fb=0.45, mix=0.8 * cm)
    if style == "flutter":
        mid, side = 0.4 * mid, 0.4 * side
    d = float(np.sign(direction)) if direction else 0.0
    pan_c = d * 0.85 * np.tanh(tt / (0.22 * dur)) if d else 0.06 * _mod(n, rng, 0.8)
    w0, wp, we = P["w"]
    bump = np.exp(-0.5 * (tt / (0.18 * dur)) ** 2)
    wc = np.where(tt < 0, w0 + (wp - w0) * bump, we + (wp - we) * bump)
    out = dsp.pan(mid, pan_c) + _ms(np.zeros(n), 0.5 * wc * side)
    # aire HF (detalle 4-14 kHz que se lee sobre el bed)
    ae = env ** 1.6 * gm
    air = dsp.hp(_dnoise(n, rng, 0.35, -1.0), min(4200.0 * bs, 12000.0), 4)
    air = _balance(_unit(air) * ae[:, None], 0.6 * pan_c)
    out += P["air"] * (0.4 + 0.8 * b) * 0.5 * air
    # componente tonal que cae en el pico (resonadores armónicos Q 40 sobre ruido)
    tn = P["tone"] if tone is None else float(tone)
    meta_note = None
    if tn > 0:
        m0 = _snap(_note_midi(note, P["note"]))
        fn = _midi_hz(m0)
        semis = _next_up(m0) - m0
        fall = 0.5 * (1.0 - np.tanh(tt / (0.1 * dur + 0.02)))
        ftone = fn * 2.0 ** (semis * fall / 12.0) * (1.0 + 0.0015 * _mod(n, rng, 2.0))
        ex = _dnoise(n, rng, 0.6, 0.0)
        ts = np.zeros((n, 2))
        for h, g in ((1, 1.0), (2, 0.5), (3, 0.28), (4, 0.2)):
            if fn * h * 2 ** (semis / 12) > 15000:
                break
            if h == 3 and (m0 + 19) % 12 not in _SAFE:     # 3er armónico de F = C: fuera de la colección
                continue
            ts += g * dsp.tv_filter(ex, ftone * h, "bandpass", q=40.0)
        ts = _unit(ts) * (env ** 1.4 * gm)[:, None]
        out += tn * 0.6 * _balance(ts, 0.7 * pan_c)
        meta_note = round(fn, 2)
    if style == "flutter":
        out += _wing_flutter(n, rng, env, dsp.as_curve(pan_c, n), bs)
    rev = P["rev"] if reverb_db is None else float(reverb_db)
    out = _space(out, P["ir"], rev, hp_send=300.0)
    out = _trim(out, n, max_len=dur + 0.25 + 0.6 * float(tail))
    out = _finish(out, P["hp"])
    sync = _peak_near(out, kp, int(0.12 * n))
    return Render(out, sync_offset=sync, meta={"style": style, "peak_s": round(sync / SR, 4),
                                               "fc_peak_hz": round(f1), "tone_hz": meta_note})


# =====================================================================================================
# des.air_suck
# =====================================================================================================

@recipe("des.air_suck", family="designed", sync="end", kind="event")
def air_suck(dur, rng, *, brightness=0.5, **_):
    """Whoosh reverso que 'aspira' hacia un corte a oscuro: banda de ruido que sube (350 Hz -> 5-9 kHz,
    aceleración) con crescendo lineal en dB, pre-eco de reverb invertida (air_hall) y ancho que se cierra al
    centro; termina exacto en sync = end (fade de 5 ms)."""
    dur = float(max(0.15, dur))
    n = _n(dur)
    t = _t(n)
    u = t / dur
    b = float(np.clip(brightness, 0, 1))
    lo = 350.0 * 2 ** ((b - 0.5) * 0.6)
    top = 6500.0 * 2 ** ((b - 0.5) * 1.4)
    fc = lo * (top / lo) ** (u ** 2.0) * (1.0 + 0.06 * _mod(n, rng, 2.0))
    nz = dsp.tv_filter(_dnoise(n, rng, 0.5, -2.0), fc, "bandpass", q=0.9, stages=2)
    env = _db(-34.0 * (1.0 - u) ** 1.3) * _ss(u, 0.0, 0.15) * _db(1.0 * _mod(n, rng, 4.0))
    direct = _unit(nz) * env[:, None]
    # pre-eco: ráfaga brillante en el instante del corte -> air_hall -> invertida (sube sola hacia el final)
    L = n + _n(0.03)
    k = _n(0.03)
    burst = np.zeros((L, 2))
    burst[:k] = dsp.hp(_dnoise(k, rng, 0.4, -1.0), 400, 2) * (np.exp(-_t(k) / 0.008) * _attack(k, 0.0005))[:, None]
    wet = dsp.convolve(burst, _ir("air_hall"), wet=1.0)[:n][::-1].copy()
    wet = _unit(wet) * (_ss(u, 0.0, 0.25) * (0.3 + 0.7 * u))[:, None]
    y = direct + 0.55 * wet
    y = dsp.width(y, 1.4 - 1.1 * u ** 2)
    y = _finish(y, 150.0, fin=0.01, fout=0.005)
    return Render(y, sync_offset=len(y) - 1, meta={"lo_hz": round(lo), "top_hz": round(top)})


# =====================================================================================================
# des.sub_impact / des.soft_impact
# =====================================================================================================

@recipe("des.sub_impact", family="designed", sync="transient", kind="event")
def sub_impact(dur, rng, *, f_start=85, f_end=38, decay=1.2, body=0.5, drive=1.5, hall_db=-14.0, transient=0.35, **_):
    """Impacto sub: seno con caída de pitch (fundamental <= 45 Hz, bajo el bombo), ataque 5 ms, tanh 1.5;
    transiente = ráfaga de ruido LP 2 kHz 30 ms; cuerpo modal 150-400 Hz (body); envío designed_hall con HP 200.
    Las capas superiores llevan HP 140 Hz: por debajo de 100 Hz sólo queda el seno (bus SUB limpio)."""
    f_end = float(min(f_end, 45.0))
    f_start = float(max(f_start, f_end + 5.0))
    decay = float(np.clip(decay, 0.3, 4.0))
    pre = _n(0.01)
    T = max(float(dur), 2.0 * decay) + 0.05
    m = _n(T)
    N = pre + m
    sub = _sub_core(m, rng, f_start, f_end, decay, 0.005, drive)
    t = _t(m)
    k = _n(0.03)
    burst = np.zeros(m)
    burst[:k] = rng.standard_normal(k) * np.exp(-_t(k) / 0.008) * _attack(k, 0.0005) * (1.0 - _ss(_t(k), 0.02, 0.03))
    burst = dsp.lp(burst, 2000, 2)
    burst /= np.abs(burst).max() + 1e-12
    bod = _body_modal(m, rng, 4, (0.06, 0.18), 4.0)
    thump = dsp.bp(rng.standard_normal(m), 150, 400, 2) * _decay_env(m, 0.06, 0.003)
    bod = 0.7 * bod + 0.3 * thump / (np.abs(thump).max() + 1e-12)
    hi = transient * burst + 0.55 * float(body) * bod
    hi = signal.sosfilt(dsp.butter_sos(4, 140, "highpass"), hi)
    x = np.zeros((N, 2))
    x[pre:] += sub[:, None]
    x[pre:] += np.stack([hi, np.concatenate([np.zeros(12), hi[:-12]])], axis=1)
    out = _space(x, "designed_hall", float(hall_db), hp_send=200.0)
    out = _trim(out, N, max_len=pre / SR + T + 1.5)
    out = _finish(out, 18.0, order=2, fin=0.002)
    return Render(out, sync_offset=pre, meta={"f_start": f_start, "f_end": f_end, "sub_end_hz": round(f_end, 1),
                                               "decay": decay, "sub_clean_below_hz": 140})


@recipe("des.soft_impact", family="designed", sync="transient", kind="event")
def soft_impact(dur, rng, *, brightness=0.5, tail=1.0, **_):
    """Impacto suave sin sub: cuerpo modal 150-420 Hz + thump + soporte 90-120 Hz + snap 1-4 kHz + aire HF +
    cola de designed_hall (tail = nivel/longitud de la cola). HP 75 Hz (cuerpo intencional)."""
    pre = _n(0.008)
    T = max(float(dur), 0.6)
    m = _n(T)
    N = pre + m
    core, air = _impact_parts(m, rng, brightness)
    x = np.zeros((N, 2))
    x[pre:] += 0.75 * core[:, None] * np.array([1.0, 0.97])
    x[pre:] += air
    tail = float(np.clip(tail, 0.0, 2.0))
    out = _space(x, "designed_hall", -9.0 + 5.0 * (tail - 1.0), hp_send=300.0)
    out = _trim(out, N, max_len=pre / SR + T + 0.4 + 1.6 * tail)
    out = _finish(out, 75.0)
    return Render(out, sync_offset=pre, meta={"brightness": brightness, "tail": tail})


# =====================================================================================================
# des.reverse_swell / des.riser
# =====================================================================================================

@recipe("des.reverse_swell", family="designed", sync="end", kind="event")
def reverse_swell(dur, rng, *, source="bell", note="Bb4", beats=None, brightness=0.5, wet_db=-1.0, **_):
    """Swell reverso: campana FM (nota) | golpe | ráfaga de ruido -> designed_hall -> invertido -> recortado a dur
    (o beats * 508 ms), terminando exacto en sync = end con fade de 5 ms."""
    if beats:
        dur = float(beats) * BEAT
    dur = float(dur) if dur and dur > 0.05 else 2 * BEAT
    n = _n(dur)
    L = n + _n(0.05)
    b = float(np.clip(brightness, 0, 1))
    f = _note(note, "Bb4")
    src_kind = str(source)
    if src_kind == "hit":
        core, air = _impact_parts(L, rng, b, low=0.6)
        bell = _bell(f, L, rng, 1.5 + 2.0 * b, 0.12, 0.9)
        src = core[:, None] * 0.9 + air * 1.2 + 0.35 * bell
    elif src_kind == "noise":
        t = _t(L)
        nz = dsp.bp(_dnoise(L, rng, 0.5, -2.0), 400, 9000, 2)
        src = _unit(nz) * (np.exp(-t / 0.12) * _attack(L, 0.001))[:, None]
        src += 0.25 * _bell(f, L, rng, 1.5, 0.08, 0.6, strike=0.5)
    else:
        src_kind = "bell"
        src = _bell(f, L, rng, 2.0 + 2.5 * b, 0.25, max(0.35, 0.7 * dur))
    src = dsp.hp(src, 120, 2)
    wet = dsp.convolve(src, _ir("designed_hall"), wet=float(_db(wet_db)))
    wet[:L] += 0.55 * src
    y = wet[:n][::-1].copy()
    u = np.linspace(0.0, 1.0, n)
    y = _reshape(y, -36.0 * (1.0 - u)) * _ss(u, 0.0, 0.04)[:, None]     # crescendo exponencial (lineal en dB)
    y = _finish(y, 120.0, fin=0.005, fout=0.005)
    return Render(y, sync_offset=len(y) - 1, meta={"source": src_kind, "note_hz": round(f, 2), "dur": round(dur, 4)})


@recipe("des.riser", family="designed", sync="end", kind="event")
def riser(dur, rng, *, start_hz=200, end_hz=8000, shepard=True, center="Bb5", octaves=None, brightness=0.5, **_):
    """Riser: ruido BP barrido start_hz -> end_hz (aceleración exponencial) + flanger que sube + aire HF
    creciente + glissando Shepard (senos a octavas bajo envolvente gaussiana centrada en Bb, que aterriza
    exacto en Bb al final). Amplitud creciente; sync = end."""
    dur = float(max(0.3, dur))
    n = _n(dur)
    t = _t(n)
    u = t / dur
    b = float(np.clip(brightness, 0, 1))
    s0, s1 = float(max(40.0, start_hz)), float(min(16000.0, end_hz))
    g = u ** 1.5
    fc = s0 * (s1 / s0) ** g * (1.0 + 0.05 * _mod(n, rng, 2.0))
    nz = dsp.tv_filter(_dnoise(n, rng, 0.0, -2.0), fc, "bandpass", q=2.0, stages=2)
    nz = _unit(nz)
    env = _ss(u, 0.0, 1.0) ** 0.6 * u ** 1.6
    trem_rate = (5.0 + 14.0 * u ** 2) * (1.0 + 0.1 * _mod(n, rng, 1.0))
    trem = 1.0 + 0.18 * u ** 2 * np.sin(TWO_PI * np.cumsum(trem_rate) / SR)
    e = env * trem * _db(0.8 * _mod(n, rng, 1.5))
    w = 0.25 + 0.75 * u ** 1.5
    mid = dsp.comb(nz[:, 0] * e, 0.004 * (0.1 / 0.004) ** g, fb=0.4, mix=0.25)
    noise = _ms(mid, 0.6 * w * nz[:, 1] * e)
    air = dsp.hp(_dnoise(n, rng, 0.3, -1.0), 6000, 4)
    air = _unit(air) * (u ** 3.0 * (0.4 + 0.8 * b))[:, None]
    out = noise + 0.3 * air
    meta = {"start_hz": s0, "end_hz": s1}
    if shepard:
        R = int(octaves) if octaves else max(1, int(round(dur / 1.3)))
        sgl = R * u ** 1.35
        c = np.log2(_note(center, "Bb5"))
        sig = 1.0
        sh = np.zeros((n, 2))
        for k in range(-4, 5):
            x = (k + sgl - R + 4.5) % 9.0 - 4.5
            fk = 2.0 ** (c + x)
            a = np.exp(-0.5 * (x / sig) ** 2)
            p = 0.35 * (-1) ** k
            for cents, side in ((-4.0, -1), (4.0, 1)):
                ph = TWO_PI * np.cumsum(fk * 2 ** (cents / 1200)) / SR + rng.uniform(0, TWO_PI)
                sh += 0.5 * dsp.pan(a * np.sin(ph), np.clip(p + 0.2 * side, -1, 1))
        sh = _unit(sh) * (u ** 1.6 * _ss(u, 0, 0.15) * _db(1.0 * _mod(n, rng, 3.0)))[:, None]
        out += 0.38 * sh
        meta.update(shepard_octaves=R, center_hz=round(2 ** c, 2))
    out = _finish(out, 120.0, fin=0.01, fout=0.005)
    return Render(out, sync_offset=len(out) - 1, meta=meta)


# =====================================================================================================
# des.glint / des.led_sweep / des.ui_tone
# =====================================================================================================

@recipe("des.glint", family="designed", sync="transient", kind="event")
def glint(dur, rng, *, note="F6", ratio=3.5, decay=1.0, sparkle=0.5, delay=True, index=4.0, space_db=-16.0, **_):
    """Brillo FM (vidrio ratio 3.5 / campana 1.4): índice 4 exp(-t/0.15)+0.3, decay tau, copias +-3 cents L/R,
    tick de vidrio, chispas 6-14 kHz (sparkle), ping-pong a tempo 381 ms fb 35 % LPF 6 kHz. sync = ataque."""
    f = _note(note, "F6")
    decay = float(np.clip(decay, 0.05, 4.0))
    pre = _n(0.004)
    T = max(float(dur), min(4.0, 3.2 * decay))
    m = _n(T)
    N = pre + m
    x = np.zeros((N, 2))
    x[pre:] += _glint_core(m, rng, f, float(ratio), decay, float(index))
    sp = float(np.clip(sparkle, 0.0, 1.5))
    if sp > 0:
        x[pre:] += 0.55 * sp * _sparkle(m, rng, 30.0 + 50.0 * sp, 0.25 + 0.25 * sp)
    if delay:
        x = _pingpong(x, DOT8, 0.35, 6000.0, first=1 if rng.random() < 0.5 else -1)
    x = _space(x, "glass_room", float(space_db), hp_send=300.0)
    x = _trim(x, N, max_len=pre / SR + T + (2.3 if delay else 0.0) + 1.0)
    x = _finish(x, 120.0, fin=0.002)
    return Render(x, sync_offset=pre, meta={"note_hz": round(f, 2), "ratio": ratio, "decay": decay})


@recipe("des.led_sweep", family="designed", sync="start", kind="event")
def led_sweep(dur, rng, *, count=10, pan_from=-0.8, pan_to=0.8, start_note="Bb5", fizz=0.5, grain_decay=0.26,
              accel=0.15, **_):
    """Tira LED encendiéndose: `count` granos de vidrio ascendentes por la colección (Bb5 Db6 Eb6 F6 Ab6 Bb6
    Db7 ...), onsets repartidos en dur (levemente acelerando), paneo pan_from -> pan_to, + fizz eléctrico
    finísimo que sigue el barrido. Delicado. sync = primer grano."""
    dur = float(max(0.2, dur))
    count = int(np.clip(count, 2, 24))
    mids = [_snap(_note_midi(start_note, "Bb5"))]
    while len(mids) < count:
        mids.append(_next_up(mids[-1]))
    freqs = np.array([_midi_hz(k) for k in mids])
    while freqs.max() > 9000:
        freqs = np.where(freqs > 9000, freqs / 2, freqs)
    pre = _n(0.003)
    span = 0.82 * dur
    uu = np.arange(count) / (count - 1)
    on = span * uu ** (1.0 + float(accel))
    jit = rng.normal(0, 0.07 * span / (count - 1), count)
    jit[0] = 0.0
    on = np.maximum.accumulate(np.clip(on + jit, 0.0, span))
    gd = float(np.clip(grain_decay, 0.08, 1.0))
    T = dur + 5 * gd + 0.1
    N = pre + _n(T)
    out = np.zeros((N, 2))
    pf, pt = float(pan_from), float(pan_to)
    for i, (fq, o) in enumerate(zip(freqs, on)):
        gl = _n(min(T - o, 4 * gd))
        dec = gd * rng.uniform(0.85, 1.15) * (1.0 - 0.3 * uu[i])
        g = _glint_core(gl, rng, fq, 3.5 if i % 3 else 3.0, dec, 2.2 * rng.uniform(0.85, 1.15), 3.0, 0.05, 0.06,
                        attack=0.003)
        lvl = float(_db(-4.0 + 4.0 * min(1.0, 2.0 * uu[i]) + rng.uniform(-1.2, 1.2)))
        p = float(np.clip(pf + (pt - pf) * uu[i] + rng.uniform(-0.05, 0.05), -1, 1))
        gm, gs = dsp.mono(g), 0.5 * (g[:, 0] - g[:, 1])
        st = dsp.pan(gm, p) + _ms(np.zeros(gl), 0.6 * gs)
        dsp.mix_into(out, st, pre + int(o * SR), lvl)
    # fizz eléctrico: crepitación Poisson (densidad que sigue la cabeza del barrido) + siseo HF
    fz = float(np.clip(fizz, 0.0, 1.5))
    if fz > 0:
        M = N - pre
        tt = _t(M)
        head = _ss(tt, 0.0, 0.04) * (1.0 - _ss(tt, span, span + 0.35))
        dens = 800.0 + 2500.0 * head * (0.6 + 0.4 * _mod(M, rng, 6.0))
        cr = dsp.velvet(M, rng, 3300.0) * (rng.random(M) < dens / 3300.0)
        cr = cr * np.abs(rng.standard_normal(M)) ** 1.5
        cr = dsp.hp(dsp.lp(cr, 12000, 2), 6000, 4)
        hs = dsp.hp(rng.standard_normal(M), 8000, 4)
        fzz = _unit(cr) + 0.6 * _unit(hs)
        fzz *= head * _db(1.5 * _mod(M, rng, 4.0))
        p_head = np.clip(pf + (pt - pf) * np.clip(tt / span, 0, 1), -1, 1)
        fst = dsp.pan(fzz, p_head) + _ms(np.zeros(M), 0.3 * fzz * _mod(M, rng, 3.0))
        out[pre:] += 0.06 * fz * fst
    out = _space(out, "glass_room", -15.0, hp_send=400.0)
    out = _trim(out, N, max_len=pre / SR + T + 1.0)
    out = _finish(out, 120.0, fin=0.002)
    return Render(out, sync_offset=pre, meta={"notes_hz": [round(float(f), 1) for f in freqs],
                                               "onsets_s": [round(float(o), 3) for o in on]})


@recipe("des.ui_tone", family="designed", sync="transient", kind="event")
def ui_tone(dur, rng, *, note="Eb6", decay=None, echo=True, **_):
    """Tono UI suave: seno + FM muy leve (ratio 3: bandas en octavas), ataque 2.5 ms, tick, eco de 1/16 (127 ms)
    a los lados y sala de vidrio corta."""
    f = _note(note, "Eb6")
    pre = _n(0.003)
    dur = float(max(0.1, dur))
    tau = float(decay) if decay else float(np.clip(0.22 * dur, 0.06, 0.3))
    m = _n(max(dur, 5 * tau))
    t = _t(m)
    tone = 0.75 * np.sin(TWO_PI * f * (1 + 0.0005 * _mod(m, rng, 2.0)) * t)
    tone += 0.45 * _fm(f, 3.0, 0.8 * np.exp(-t / 0.03) + 0.12, m, rng.uniform(0, TWO_PI))
    if 2 * f < 16000:
        tone += 0.08 * np.sin(TWO_PI * 2 * f * t + rng.uniform(0, TWO_PI)) * np.exp(-t / (0.4 * tau))
    tone *= np.exp(-t / (tau * rng.uniform(0.92, 1.08))) * _attack(m, 0.0025)
    tone = _endfade(tone, 0.1)
    k = _n(0.002)
    tick = np.zeros(m)
    tick[:k] = dsp.bp(rng.standard_normal(k), 3000, 7000, 2) * np.exp(-_t(k) / 0.0004) * _attack(k, 0.0002)
    tone += 0.06 * tick / (np.abs(tick).max() + 1e-12)
    x = np.zeros((pre + m, 2))
    x[pre:] += dsp.pan(tone, rng.uniform(-0.05, 0.05))
    if echo:
        d = _n(SIXTEENTH)
        side = 1 if rng.random() < 0.5 else -1
        e1 = dsp.lp(tone, 7000, 2)
        x = np.concatenate([x, np.zeros((2 * d, 2))])
        dsp.mix_into(x, dsp.pan(e1, 0.55 * side), pre + d, 0.22)
        dsp.mix_into(x, dsp.pan(dsp.lp(e1, 5000, 2), -0.55 * side), pre + 2 * d, 0.09)
    x = _space(x, "glass_room", -20.0, hp_send=400.0)
    x = _trim(x, pre + m, max_len=pre / SR + max(dur, 5 * tau) + 0.8)
    x = _finish(x, 120.0, fin=0.002)
    return Render(x, sync_offset=pre, meta={"note_hz": round(f, 2), "tau": round(tau, 3)})


# =====================================================================================================
# des.ev_motif (firma EV de la marca)
# =====================================================================================================

def _motif_core(dur: float, rng, f0: float, gesture: str = "swell", glide_at=None, glide_s=None,
                grain: float = 1.0, whistle_db: float = -36.0, presence: float = 1.0):
    """Stack aditivo en f0: parciales 1,2,3,4,6 a 0/-6/-9/-14/-20 dB, cada uno un par desafinado que bate a
    0.15-0.4 Hz (repartido L/R), vibrato 0.2 Hz +-3 cents, ruido de banda angosta (Q 30) en 2 y 4 (grano
    eléctrico), silbido 32*f0 (Bb7) a -36 dB. Devuelve (estéreo, n_total, info)."""
    gesture = gesture if gesture in ("swell", "rise", "resolve") else "swell"
    ga = gs = None
    if gesture == "rise":
        ga = float(glide_at) if glide_at is not None else float(np.clip(0.42 * dur, 0.35, 1.2))
        gs = float(glide_s) if glide_s is not None else float(min(0.8, max(0.3, 0.45 * dur)))
        T = max(dur, ga + gs + 0.5) + 0.4
    elif gesture == "resolve":
        ga = float(glide_at) if glide_at is not None else 0.38 * dur
        gs = float(glide_s) if glide_s is not None else float(min(0.55, max(0.2, 0.35 * dur)))
        T = max(dur, ga + gs + 0.4) + 1.4
    else:
        T = dur + 0.35
    N = _n(T)
    t = _t(N)
    prog = np.zeros(N)
    if gesture == "rise":
        u = np.clip((t - ga) / gs, 0, 1)
        prog = u * u * (3 - 2 * u)
    elif gesture == "resolve":
        u = np.clip((t - ga) / gs, 0, 1)
        prog = 1.0 - (1.0 - u) ** 2.5
    vib_rate = 0.2 * (1.0 + 0.15 * _mod(N, rng, 0.3))
    vib = 2.0 ** ((3.0 / 1200.0) * np.sin(TWO_PI * np.cumsum(vib_rate) / SR + rng.uniform(0, TWO_PI)))
    m0 = _snap(_note_midi(f0))
    semis = next(iv for iv in (7, 5, 8, 9, 4) if (m0 + iv) % 12 in _SAFE)   # Bb->F (quinta); F->Bb si la quinta cae fuera
    f = f0 * 2.0 ** (semis * prog / 12.0) * vib
    # envolvente por gesto
    if gesture == "swell":
        rs = min(float(np.clip(0.45 * dur, 0.6, 1.2)), 0.8 * dur)
        env = _ss(t, 0, rs) ** 1.4 * (1.0 - _ss(t, rs, T)) ** 1.1
        energy = env
    elif gesture == "rise":
        rs = min(float(np.clip(0.35 * dur, 0.35, 0.9)), ga)
        land = ga + gs
        env = _ss(t, 0, rs) ** 1.3 * (1.0 + 0.26 * prog) * (1.0 - _ss(t, land + 0.1, T)) ** 1.2
        energy = prog
    else:
        rs = min(0.3, 0.25 * dur)
        land = ga + gs
        bloom = _ss(t, ga + 0.6 * gs, land + 0.35)
        env = _ss(t, 0, rs) * (1.0 + 0.41 * bloom) * np.exp(-np.maximum(t - (land + 0.35), 0) / 0.9)
        env *= 1.0 - _ss(t, T - 0.3, T)
        energy = bloom
    out = np.zeros((N, 2))
    pres = float(max(presence, 0.0))
    parts = [(1, 0.0), (2, -6.0), (3, -9.0), (4, -14.0), (6, -20.0)]
    if pres > 0:   # 'presencia' de inversor: octavas 8 y 16 (siempre en la colección), legibles sobre el bed
        parts += [(8, -22.0 + 20 * np.log10(pres)), (16, -28.0 + 20 * np.log10(pres))]
    for i, (r, a) in enumerate(parts):
        if f0 * r * 2 ** (semis / 12) > 15000:
            continue
        a = a + rng.uniform(-0.6, 0.6)
        w, ins = 1.0, 1.0
        if r in (3, 6):   # voicing seguro: el 3er armónico se apaga (-14 dB) cuando cae fuera de la colección (3*F = C)
            ia = 1.0 if (m0 + 19) % 12 in _SAFE else 0.0
            ib = 1.0 if (m0 + semis + 19) % 12 in _SAFE else 0.0
            ins = ia + (ib - ia) * prog
            w = 0.2 + 0.8 * ins
        if r >= 3:
            w = w * (1.0 + 0.8 * energy * ins)                     # brillo con la energía del gesto (+5 dB)
        beat = rng.uniform(0.15, 0.4)
        ph = rng.uniform(0, TWO_PI, 2)
        p1 = np.sin(TWO_PI * np.cumsum(f * r) / SR + ph[0])
        p2 = np.sin(TWO_PI * np.cumsum(f * r + beat) / SR + ph[1])
        g = float(_db(a)) * w * (1.0 + 0.04 * _mod(N, rng, 0.5))
        sp = min(0.8, 0.45 + 0.05 * i)                             # pares repartidos L/R: batido espacial
        out += 0.5 * g[:, None] * (dsp.pan(p1, -sp) + dsp.pan(p2, sp))
    # grano eléctrico: ruido de banda angosta (Q 30) siguiendo los parciales 2 y 4
    if grain > 0:
        for r, gdb in ((2, -20.0), (4, -25.0)):
            nb = dsp.tv_filter(_dnoise(N, rng, 0.5, 0.0), f * r, "bandpass", q=30.0, block=128, stages=2)
            nb = _unit(nb) * (1.0 + 0.3 * _mod(N, rng, 6.0))[:, None]
            out += grain * float(_db(gdb)) * nb
    # silbido Bb7 (32 * f0)
    fw = f * 32.0
    if fw.max() < 16000:
        wh = np.sin(TWO_PI * np.cumsum(fw * (1.0 + 0.0006 * _mod(N, rng, 1.0))) / SR + rng.uniform(0, TWO_PI))
        out += float(_db(whistle_db)) * dsp.pan(wh * (1.0 + 0.2 * _mod(N, rng, 0.8)), rng.uniform(-0.35, 0.35))
    out *= env[:, None]
    info = {"gesture": gesture, "glide_at": ga, "glide_s": gs, "T": T, "glide_semitones": semis}
    return out, N, info


@recipe("des.ev_motif", family="designed", sync="start", kind="event")
def ev_motif(dur, rng, *, gesture="swell", root="Bb2", glide_at=None, glide_s=None, grain=1.0, whistle_db=-36.0,
             presence=1.0, space_db=None, **_):
    """Firma EV ("EV hum"): stack aditivo cálido en Bb2 con batidos lentos, grano eléctrico y silbido Bb7.
    gesture: swell (sube 0.6-1.2 s y cae suave) | rise (swell + glide Bb->F, una quinta en ~0.8 s, como una
    aceleración) | resolve (sostenido, se asienta en F con bloom largo). HPF 90 Hz. sync = inicio."""
    dur = float(max(0.3, dur))
    f0 = _note(root, "Bb2")
    x, N, info = _motif_core(dur, rng, f0, str(gesture), glide_at, glide_s, float(grain), float(whistle_db),
                             float(presence))
    if info["gesture"] == "resolve":
        x = _space(x, "designed_hall", -13.0 if space_db is None else float(space_db), hp_send=200.0)
    else:
        x = _space(x, "air_hall", -18.0 if space_db is None else float(space_db), hp_send=200.0)
    x = _trim(x, N, max_len=info["T"] + 1.2)
    x = _finish(x, 90.0, fin=0.005)
    info.update(root_hz=round(f0, 2), target_hz=round(f0 * 2 ** (info["glide_semitones"] / 12), 2))
    return Render(x, sync_offset=0, meta=info)


# =====================================================================================================
# des.light_shaft / des.spatial_bloom
# =====================================================================================================

_SHAFT_VOICES = (   # Bbm(add9) abierto: Bb3 F4 Bb4 Db5 F5 Bb5 + C6 (add9, única excepción). (Hz, dB, onset s, índice FM)
    (233.08, -9.0, 0.00, 0.5), (349.23, -4.0, 0.08, 0.55), (466.16, 0.0, 0.14, 0.6), (554.37, -3.0, 0.2, 0.5),
    (698.46, -4.5, 0.26, 0.55), (932.33, -9.0, 0.34, 0.5), (1046.50, -11.0, 0.42, 0.25),
)


@recipe("des.light_shaft", family="designed", sync="transient", kind="event")
def light_shaft(dur, rng, *, sweep_s=0.6, f_top=9000.0, f_bot=1500.0, pad=1.0, sparkle=0.4, **_):
    """Haz de luz cenital: barrido de ruido descendente 9 -> 1.5 kHz en 0.6 s (ancho que se cierra al centro)
    + destello HF + pad vítreo Bbm(add9) con filtro que se abre lento + chispas leves + designed_hall.
    sync = aparición del haz (ataque del barrido)."""
    dur = float(max(0.6, dur))
    pre = _n(0.005)
    T = dur + 0.3
    m = _n(T)
    N = pre + m
    t = _t(m)
    sw = float(max(0.15, sweep_s))
    u = np.clip(t / sw, 0, 1)
    gsw = 1.0 - (1.0 - u) ** 2
    fc = float(f_top) * (float(f_bot) / float(f_top)) ** gsw * (1.0 + 0.05 * _mod(m, rng, 3.0))
    nz = dsp.tv_filter(_dnoise(m, rng, 0.2, -1.0), fc, "bandpass", q=1.8, stages=2)
    se = _attack(m, 0.004) * (0.7 * np.exp(-t / (0.55 * sw)) + 0.3 * np.exp(-t / (1.4 * sw)))
    nz = _unit(nz) * (se * _db(1.0 * _mod(m, rng, 5.0)))[:, None]
    nz = dsp.width(nz, 1.4 - 0.9 * u)
    flash = dsp.hp(_dnoise(m, rng, 0.3, 0.0), 9000, 4)
    flash = _unit(flash) * (_attack(m, 0.002) * np.exp(-t / 0.05))[:, None]
    x = np.zeros((N, 2))
    x[pre:] += nz + 0.35 * flash
    # pad vítreo Bbm(add9)
    if pad > 0:
        pd = np.zeros((m, 2))
        rel = 1.0 - _ss(t, dur - 0.1, T)
        for f_nom, gdb, on, idx in _SHAFT_VOICES:
            fq = f_nom * (1.0 + 0.0008 * _mod(m, rng, 0.25))
            on = on * rng.uniform(0.8, 1.2)
            ev = _ss(t, on, on + rng.uniform(0.4, 0.6)) * rel
            I1 = np.minimum(idx * (0.45 + 1.0 * _ss(t, 0.0, dur)) * (1.0 + 0.2 * _mod(m, rng, 0.4)), 0.62)  # se abre
            v = _fm_stereo(fq, m, rng, 3.0, I1, 4.0, 0.5, 0.5)          # ratio 3: bandas en octavas (2f, 4f)
            if f_nom > 450:                                             # brillo vítreo inarmónico, muy bajo
                v += 0.1 * _fm_stereo(fq, m, rng, 3.5, 0.15, 6.0, 0.5, 0.5)
            pd += float(_db(gdb)) * v * ev[:, None]
        pfc = 900.0 * (7000.0 / 900.0) ** _ss(t, 0.0, dur) * (1.0 + 0.08 * _mod(m, rng, 0.5))
        pd = dsp.tv_filter(pd, pfc, "lowpass", q=0.8, stages=2, block=128)
        x[pre:] += 0.3 * float(pad) * _unit(pd) * _rms(nz[: _n(sw)])
    sp = float(sparkle)
    if sp > 0:
        x[pre:] += 0.9 * sp * _rms(nz[: _n(sw)]) * _sparkle(m, rng, 30.0 * sp, 0.6 * dur, 0.02)
    x = _space(x, "designed_hall", -10.0, hp_send=200.0)
    x = _trim(x, N, max_len=pre / SR + T + 2.0)
    x = _finish(x, 120.0, fin=0.002)
    return Render(x, sync_offset=pre, meta={"sweep_s": sw, "f_top": f_top, "f_bot": f_bot})


@recipe("des.spatial_bloom", family="designed", sync="transient", kind="event")
def spatial_bloom(dur, rng, *, note="F3", brightness=0.5, chord=0.5, **_):
    """Pulso filtrado de parlante (thump afinado del cono + click blando + empuje de aire) que florece en un burst
    de reverb estéreo muy ancho: reflexiones tempranas que se abren hacia los lados, cola bloom_hall cuyo filtro
    (0.9 -> 9 kHz) y ancho (0.5 -> 1.6) se abren en ~0.4 s, y un brillo de acorde Bbm (octavas puras) que
    asoma dentro del bloom. sync = pulso."""
    pre = _n(0.006)
    T = max(float(dur), 0.8)
    m = _n(T)
    N = pre + m
    t = _t(m)
    b = float(np.clip(brightness, 0, 1))
    f = _note(note, "F3")
    fp = f * (1.0 + 0.12 * np.exp(-t / 0.02)) * rng.uniform(0.995, 1.005)
    thump = np.sin(TWO_PI * np.cumsum(fp) / SR) * _decay_env(m, 0.045 * rng.uniform(0.9, 1.1), 0.0015)
    thump += 0.35 * np.sin(TWO_PI * np.cumsum(2 * fp) / SR) * _decay_env(m, 0.03, 0.0015)
    k = _n(0.008)
    click = np.zeros(m)
    click[:k] = dsp.bp(rng.standard_normal(k), 1500, 4000, 2) * np.exp(-_t(k) / 0.0012) * _attack(k, 0.0004)
    push = dsp.tv_filter(rng.standard_normal(m), 600.0 * (6000.0 / 600.0) ** _ss(t, 0.0, 0.12), "lowpass", q=0.7)
    push = push * _decay_env(m, 0.06, 0.004)
    pulse = (thump / (np.abs(thump).max() + 1e-12) + 0.15 * click / (np.abs(click).max() + 1e-12)
             + 0.35 * push / (np.abs(push).max() + 1e-12))
    pulse = _endfade(dsp.lp(pulse, 2500 + 5000 * b, 2), 0.2)
    x = np.zeros((N, 2))
    x[pre:] += pulse[:, None]
    # reflexiones tempranas que se abren hacia afuera (cada una más oscura)
    er = np.zeros((m, 2))
    for i, ms in enumerate((9, 14, 21, 29, 38, 50, 64, 81, 101)):
        p = (0.25 + 0.75 * i / 8) * (-1) ** i
        d = _n(ms * rng.uniform(0.93, 1.07) / 1000.0)
        dsp.mix_into(er, dsp.pan(dsp.lp(pulse, 4500 - 300 * i, 2), p), d, float(_db(-4.0 - 1.6 * i)))
    x[pre:] += 0.8 * _endfade(er, 0.2)
    # brillo de acorde Bbm que asoma dentro del bloom (ratio 3 -> bandas en octavas)
    if chord > 0:
        ch = np.zeros((m, 2))
        for fq, gdb in ((466.16, 0.0), (554.37, -3.0), (698.46, -2.0), (932.33, -6.0), (1396.91, -9.0)):
            ev = _ss(t, 0.03, 0.03 + rng.uniform(0.12, 0.22)) * np.exp(-np.maximum(t - 0.2, 0) / 0.4)
            ch += float(_db(gdb)) * _fm_stereo(fq, m, rng, 3.0, 0.5 * ev + 0.1, 5.0) * ev[:, None]
        x[pre:] += float(chord) * 0.18 * _endfade(ch, 0.2)
    # soplo de aire HF que sólo alimenta la reverb: el bloom se abre en 2-12 kHz (lo que se lee sobre el bed)
    puff = dsp.hp(_dnoise(m, rng, 0.2, -1.0), 2500, 2) * (_attack(m, 0.004) * np.exp(-t / 0.07))[:, None]
    send = x.copy()
    send[pre:] += (0.25 + 0.3 * b) * puff / (np.abs(puff).max() + 1e-12)
    # burst de reverb: filtro y ancho que se abren
    wet = dsp.convolve(dsp.hp(send, 250, 4), _ir("bloom_hall"), wet=float(_db(-1.0)))
    W = len(wet)
    tw = _t(W)
    wfc = 900.0 * (12000.0 / 900.0) ** _ss(tw, pre / SR, pre / SR + 0.4)
    wet = dsp.tv_filter(wet, wfc, "lowpass", q=0.7, block=128)
    wet = dsp.width(wet, 0.5 + 1.1 * _ss(tw, pre / SR, pre / SR + 0.45))
    wet[:N] += x
    out = _trim(wet, N, max_len=pre / SR + T + 1.6)
    out = _finish(out, 90.0, fin=0.002)
    return Render(out, sync_offset=pre, meta={"note_hz": round(f, 2)})


# =====================================================================================================
# camas: des.mist_texture / des.drone
# =====================================================================================================

@recipe("des.mist_texture", family="designed", sync="start", kind="bed")
def mist_texture(dur, rng, *, brightness=0.5, drift=0.5, corr=0.4, peaks=4, **_):
    """Niebla diseñada: ruido pintado en STFT 3-10 kHz (brightness desplaza la banda) con 3-6 picos espectrales
    que derivan y respiran lentamente (drift) con energía por cuadro compensada (el color se mueve, el nivel
    no) + deriva de ganancia 1/f +-0.7 dB; estéreo ancho (correlación ~corr)."""
    dur = float(max(0.3, dur))
    n = _n(dur)
    b = float(np.clip(brightness, 0, 1))
    dr = float(np.clip(drift, 0, 1))
    lo = 3000.0 * 2 ** ((b - 0.5) * 1.2)
    hi = min(15000.0, 10000.0 * 2 ** ((b - 0.5) * 1.0))
    llo, lhi = np.log2(lo), np.log2(hi)
    cn = max(16, int(dur * 100))
    ct = np.linspace(0.0, dur, cn)
    sr_c = cn / dur
    K = int(np.clip(peaks, 1, 8))
    cen, wid, gai = [], [], []
    for _k in range(K):
        c0 = rng.uniform(llo + 0.15, lhi - 0.15)
        c = c0 + (0.2 + 0.6 * dr) * _mod(cn, rng, 0.04 + 0.25 * dr, 1.0, sr_c)
        cen.append(np.clip(c, llo - 0.3, lhi + 0.3))
        wid.append(rng.uniform(0.22, 0.45) * (1.0 + 0.25 * _mod(cn, rng, 0.1, 1.0, sr_c)))
        gai.append(_db(rng.uniform(3.0, 7.0) + 2.5 * _mod(cn, rng, 0.1 + 0.3 * dr, 1.0, sr_c)) - 1.0)
    gmod = _db(0.7 * _mod(cn, rng, 0.15, 1.0, sr_c))

    def mag(tt, ff):
        lf = np.log2(np.maximum(ff, 20.0))[:, None]
        base = _ss(lf, llo - 0.8, llo + 0.1) * (1.0 - _ss(lf, lhi - 0.1, lhi + 0.9))
        G = 0.5 * np.ones((len(ff), len(tt)))
        for c, w, g in zip(cen, wid, gai):
            ck = np.interp(tt, ct, c)[None, :]
            wk = np.interp(tt, ct, w)[None, :]
            gk = np.interp(tt, ct, g)[None, :]
            G = G + gk * np.exp(-0.5 * ((lf - ck) / wk) ** 2)
        tilt = 2.0 ** (-np.maximum(lf - 13.0, 0.0) * 0.5)        # -3 dB/oct sobre 8 kHz
        M = base * G * tilt
        e = np.sqrt((M ** 2).sum(axis=0, keepdims=True))           # el timbre se mueve, el nivel no:
        M = M / (e / e.mean())                                     # sólo la deriva acotada gmod (+-0.7 dB)
        return M * np.interp(tt, ct, gmod)[None, :]

    common, left, right = (dsp.spectral_paint(n, rng, mag) for _ in range(3))
    k, j = np.sqrt(np.clip(corr, 0, 1)), np.sqrt(1.0 - np.clip(corr, 0, 1))
    x = np.stack([k * common + j * left, k * common + j * right], axis=1)
    x = _finish(x, 120.0, fin=0.02, fout=0.02)
    return Render(x, sync_offset=0, meta={"band_hz": [round(lo), round(hi)], "peaks": K})


@recipe("des.drone", family="designed", sync="start", kind="bed")
def drone(dur, rng, *, note="Bb1", brightness=0.3, sub=0.4, motion=0.5, hp_hz=70.0, **_):
    """Dron muy discreto en `note`: parciales de la colección (1,2,3,4,6,8,12,16) en pares desafinados que baten
    0.06-0.45 Hz (sin periodicidad: derivas de ganancia independientes), filtro LP que se mueve lento,
    respiración de ruido muy baja. HP 70 Hz por defecto: el fundamental Bb1 queda implícito (no pelea con
    el bombo); bajar hp_hz/subir `sub` en el remate sin música."""
    dur = float(max(0.3, dur))
    n = _n(dur)
    f0 = _note(note, "Bb1")
    b = float(np.clip(brightness, 0, 1))
    mo = float(np.clip(motion, 0, 1))
    fp = f0 * (1.0 + 0.0008 * _mod(n, rng, 0.2))
    tilt = (b - 0.3) * 10.0
    y = np.zeros((n, 2))
    for r, a in zip((1, 2, 3, 4, 6, 8, 12, 16), (0.0, -3.0, -6.0, -7.0, -11.0, -13.0, -19.0, -23.0)):
        if f0 * r > 8000:
            continue
        a = a + tilt * np.log2(r) / 4.0 + ((float(sub) - 0.4) * 15.0 if r == 1 else 0.0)
        beat = rng.uniform(0.06, 0.45) * (0.6 + 0.8 * mo)
        ph = rng.uniform(0, TWO_PI, 2)
        p1 = np.sin(TWO_PI * np.cumsum(fp * r) / SR + ph[0])
        p2 = np.sin(TWO_PI * np.cumsum(fp * r + beat * (1.0 + 0.2 * _mod(n, rng, 0.1))) / SR + ph[1])
        am = _db(1.2 * mo * _mod(n, rng, 0.15))
        if r <= 2:   # graves casi centrados (compatibles en mono), batido poco profundo
            sp, gb = rng.uniform(0.15, 0.3), 0.45
        else:        # parciales altos: pares abiertos L/R -> el batido se vuelve movimiento en los lados
            sp, gb = min(0.9, 0.5 + 0.06 * r ** 0.5 + rng.uniform(0, 0.15)), 0.8
        side = 1.0 if rng.random() < 0.5 else -1.0
        y += float(_db(a)) * 0.6 * am[:, None] * (dsp.pan(p1, -side * sp) + gb * dsp.pan(p2, side * sp))
    nz = dsp.bp(_dnoise(n, rng, 0.25, -3.0), 2.5 * f0, 10 * f0 + 400 * b, 2)
    y += _unit(nz) * _rms(y) * float(_db(-22.0 + 8.0 * b)) * (1.0 + 0.3 * _mod(n, rng, 0.5))[:, None]
    fc = (260.0 + 2400.0 * b ** 1.3) * 2.0 ** (0.55 * mo * _mod(n, rng, 0.08) + 0.25 * _mod(n, rng, 0.3))
    y = dsp.tv_filter(y, fc, "lowpass", q=0.9, stages=2, block=256)
    y = _finish(y, float(hp_hz) if hp_hz else None, fin=0.05, fout=0.05)
    return Render(y, sync_offset=0, meta={"note_hz": round(f0, 2), "hp_hz": hp_hz})


# =====================================================================================================
# des.logo_signature / des.awakening
# =====================================================================================================

@recipe("des.logo_signature", family="designed", sync="transient", kind="event")
def logo_signature(dur, rng, *, sub=0.6, shimmer=1.0, resolve_at=None, **_):
    """Firma del logo (~2.5 s): impacto suave + sub bloom en Bb1 + racimo de brillos F6/Bb6/Db7 (rasgueo
    0/45/95 ms, eco a tempo) + shimmer reverso (vidrio Bb6/F7/Bb7 por designed_hall, invertido, crescendo
    lineal en dB) que desemboca en una campana pura Bb5/Bb6 en resolve_at (por defecto 2 negras = 1.017 s):
    la firma resuelve en la tónica. sync = impacto."""
    dur = float(max(1.2, dur))
    ra = float(resolve_at) if resolve_at else 2 * BEAT
    pre = _n(0.01)
    T = dur + 0.6
    m = _n(T)
    N = pre + m
    x = np.zeros((N, 2))
    # 1) impacto suave (sin sub)
    core, air = _impact_parts(m, rng, 0.6)
    x[pre:] += 0.7 * core[:, None] + 0.9 * air
    # 2) sub bloom Bb1 (asienta desde arriba, ataque blando, corto)
    sb = _sub_core(m, rng, 66.0, 58.27, 0.9, 0.03, 1.3, 0.15, lp_hz=90.0)
    x[pre:] += 0.32 * float(sub) * sb[:, None]
    # 3) racimo de brillos
    cl = np.zeros((m, 2))
    for note, off, dec, lv in (("F6", 0.0, 1.3, 0.0), ("Bb6", 0.045, 1.5, -2.0), ("Db7", 0.095, 1.1, -4.0)):
        o = _n(off * rng.uniform(0.85, 1.15))
        cl[o:] += float(_db(lv)) * _glint_core(m - o, rng, _note(note), 3.5, dec, 3.5)
    cl += 0.3 * _sparkle(m, rng, 40.0, 0.4)
    cl = _endfade(_pingpong(cl, DOT8, 0.3, 6000.0)[:m], 0.15)
    x[pre:] += 0.42 * float(shimmer) * cl
    # 4) shimmer reverso hacia la resolución
    rn = min(_n(ra), m)
    src = np.zeros((rn + _n(0.05), 2))
    for fq, gdb in ((1864.66, 0.0), (2793.83, -4.0), (3729.31, -7.0)):
        src += float(_db(gdb)) * _pure_bell(fq, len(src), rng, 1.0, 0.002, ((1.0, 0.0, 1.0), (2.0, -9.0, 0.5)))
    rev = dsp.convolve(dsp.hp(src, 300, 2), _ir("designed_hall"), wet=1.0)[:rn][::-1].copy()
    u = np.linspace(0.0, 1.0, rn)
    rev = _reshape(rev, -30.0 * (1.0 - u)) * _ss(u, 0.0, 0.05)[:, None]
    rev = rev / _rms(rev[-_n(0.25):])                    # RMS 1 en el último cuarto de segundo
    rev = dsp.fade(rev, 0.005, 0.004)
    x[pre:pre + rn] += 0.35 * float(shimmer) * _rms(cl[: _n(0.3)]) * rev
    # 5) resolución: campana pura Bb5 + brillo Bb6
    ro = pre + rn
    if ro < N - _n(0.1):
        res = _pure_bell(932.33, N - ro, rng, 1.4, 0.004) + 0.45 * _glint_core(N - ro, rng, 1864.66, 3.5, 1.2, 2.0, attack=0.004)
        x[ro:] += 0.3 * float(shimmer) * res
    out = _space(x, "designed_hall", -13.0, hp_send=300.0)
    out = _trim(out, N, max_len=pre / SR + T + 1.0)
    out = _finish(out, 25.0, order=2, fin=0.002)
    return Render(out, sync_offset=pre, meta={"resolve_at_s": round(ra, 4)})


@recipe("des.awakening", family="designed", sync="transient", kind="event")
def awakening(dur, rng, *, sub=0.7, glass=1.0, drops=0.7, motif=0.6, **_):
    """Despertar del EX2 (remate, sin música): bloom grave tipo sub_impact que asienta en F1 (43.65 Hz) +
    bloom FM vítreo (Bb5/F6, índice que florece) + gotas tonales Minnaert en la colección + motivo EV que
    resuelve Bb -> F (llega a F en ~0.55 s y florece hasta el corte). sync = faros (ataque)."""
    dur = float(max(0.6, dur))
    pre = _n(0.01)
    T = dur + 1.2
    m = _n(T)
    N = pre + m
    t = _t(m)
    x = np.zeros((N, 2))
    # 1) bloom grave
    lo = _sub_core(m, rng, 72.0, 43.65, 1.1, 0.012, 1.5, 0.15, lp_hz=80.0)
    x[pre:] += 0.7 * float(sub) * lo[:, None]
    # 2) bloom FM vítreo: índice que florece (sube 60 ms, decae)
    gl = np.zeros((m, 2))
    I = 3.0 * _ss(t, 0.0, 0.06) * np.exp(-np.maximum(t - 0.06, 0) / 0.35) + 0.4
    for fq, gdb in ((932.33, 0.0), (1396.91, -3.0), (2793.83, -10.0)):
        gl += float(_db(gdb)) * _fm_stereo(fq * (1 + 0.0008 * _mod(m, rng, 1.0)), m, rng, 3.5, I, 3.0)
    gl *= (_attack(m, 0.008) * np.exp(-t / 0.9))[:, None]
    x[pre:] += 0.32 * float(glass) * _endfade(gl, 0.15)
    # 3) gotas tonales
    if drops > 0:
        x[pre:] += 0.35 * float(drops) * _drops(m, rng, 13.0, 0.45, 0.04)
    # 4) motivo que resuelve Bb -> F
    if motif > 0:
        mo, Nm, _info = _motif_core(dur, rng, 116.54, "resolve", glide_at=0.18, glide_s=0.38)
        mo = dsp.hp(mo, 90, 4)
        L = min(Nm, m)
        x[pre:pre + L] += 0.5 * float(motif) * _endfade(mo[:L], 0.1)
    out = _space(x, "designed_hall", -12.0, hp_send=200.0)
    out = _trim(out, N, max_len=pre / SR + T + 0.5)
    out = _finish(out, 22.0, order=2, fin=0.002)
    return Render(out, sync_offset=pre, meta={"resolve": "Bb->F", "sub_end_hz": 43.65})


# =====================================================================================================
# des.breath_designed / des.wind_swell
# =====================================================================================================

@recipe("des.breath_designed", family="designed", sync="peak", kind="event")
def breath_designed(dur, rng, *, pitch=0.82, blur=0.6, peak_pos=0.35, size=1.0, **_):
    """Respiración mítica: turbulencia (ruido) por formantes de tracto grande (F1-F4 que derivan), aleteo nasal
    irregular, calidez de pecho; bajada de pitch por re-muestreo (pitch), difuminada (smear decorrelado +
    designed_hall). sync = máximo de energía."""
    dur = float(max(0.3, dur))
    pitch = float(np.clip(pitch, 0.55, 1.0))
    ms = _n(dur * pitch)
    t = _t(ms)
    pk = float(np.clip(peak_pos, 0.1, 0.8)) * dur * pitch
    env = _ss(t, 0.0, pk) ** 1.5 * np.exp(-np.maximum(t - pk, 0) / (0.28 * dur * pitch))
    env *= 1.0 - _ss(t, 0.85 * ms / SR, ms / SR)
    fl_rate = 21.0 * (1.0 + 0.2 * _mod(ms, rng, 1.0))
    flutter = 1.0 + 0.12 * np.sin(TWO_PI * np.cumsum(fl_rate) / SR) * (0.5 + 0.5 * _mod(ms, rng, 2.0))
    src = 0.7 * dsp.colored(ms, rng, -1.0) + 0.3 * rng.standard_normal(ms)
    sz = float(np.clip(size, 0.6, 1.6))
    form = np.zeros(ms)
    for F, B, gdb in ((420.0, 140.0, 0.0), (1100.0, 220.0, -2.0), (2400.0, 320.0, -6.0), (3600.0, 450.0, -10.0)):
        Fc = F / sz * (1.0 + 0.04 * _mod(ms, rng, 0.8))
        form += float(_db(gdb)) * dsp.tv_filter(src, Fc, "bandpass", q=F / B, block=128)
    hiss = dsp.hp(rng.standard_normal(ms), 3000, 2)
    chest = dsp.lp(dsp.brown(ms, rng), 350, 2)
    x = (_unit(form) + 0.35 * _unit(hiss) + 0.12 * _unit(chest)) * env * flutter
    y = signal.resample_poly(x, 100, int(round(100 * pitch)))
    k = _n(0.09)
    tk = _t(k)
    sm = np.stack([rng.standard_normal(k), rng.standard_normal(k)], 1) * np.exp(-tk / 0.025)[:, None]
    sm /= np.sqrt((sm ** 2).sum(axis=0, keepdims=True)) + 1e-12
    st = np.stack([signal.oaconvolve(y, sm[:, 0]), signal.oaconvolve(y, sm[:, 1])], 1)
    bl = float(np.clip(blur, 0, 1))
    st[:len(y)] += (1.0 - 0.6 * bl) * y[:, None]
    out = _space(st, "designed_hall", -10.0 + 8.0 * bl, hp_send=200.0)
    kp = int(pk / pitch * SR)
    out = _trim(out, len(y), max_len=len(y) / SR + 1.6)
    out = _finish(out, 120.0, fin=0.005)
    sync = _peak_near(out, kp, int(0.25 * len(y)))
    return Render(out, sync_offset=sync, meta={"pitch": pitch, "peak_s": round(sync / SR, 4)})


@recipe("des.wind_swell", family="designed", sync="peak", kind="event")
def wind_swell(dur, rng, *, brightness=0.5, peak_pos=0.55, whistle=0.5, **_):
    """Swell de viento diseñado y ancho: ruido estéreo decorrelado con pasabanda que sigue la 'velocidad' del
    aire, siseo HF ~ v^2, ráfagas 1/f, y silbidos eólicos sutiles afinados a la colección (Q 45) cuyo nivel
    sigue la velocidad. sync = pico."""
    dur = float(max(0.4, dur))
    n = _n(dur)
    b = float(np.clip(brightness, 0, 1))
    kp = int(np.clip(peak_pos, 0.1, 0.9) * n)
    env = _swell_env(n, kp / n, 1.6, 2.2, 1.0, 0.05)
    gust = _db(1.8 * _mod(n, rng, 2.0) + 1.0 * _mod(n, rng, 0.6))
    v = 0.35 + 0.65 * env
    fc = (300.0 + 900.0 * b) * v ** 1.2 * 2.0 ** (0.15 * _mod(n, rng, 1.0))
    body = dsp.tv_filter(_dnoise(n, rng, 0.35, -3.0), fc, "bandpass", q=0.7, block=128)
    body = _unit(body) * (env * gust)[:, None]
    hiss = dsp.hp(_dnoise(n, rng, 0.3, -1.5), 2500 + 3000 * b, 2)
    hiss = _unit(hiss) * (env ** 2 * gust)[:, None]
    out = body + (0.25 + 0.3 * b) * hiss
    wh = float(np.clip(whistle, 0, 1.5))
    if wh > 0:
        pool = _penta(1000.0 * 2 ** (b - 0.5), 2600.0 * 2 ** (b - 0.5))
        sel = rng.choice(pool, size=min(3, len(pool)), replace=False)
        for fq in sel:
            thr = rng.uniform(0.35, 0.6)
            amp = _ss(env * (1.0 + 0.15 * _mod(n, rng, 3.0)), thr, 1.0)
            w = dsp.tv_filter(rng.standard_normal(n), fq * (1.0 + 0.004 * _mod(n, rng, 0.7)), "bandpass", q=45.0,
                              block=128)
            out += 0.22 * wh * dsp.pan(_unit(w) * amp, rng.uniform(-0.6, 0.6))
    out = _space(out, "air_hall", -14.0, hp_send=200.0)
    out = _trim(out, n, max_len=dur + 1.2)
    out = _finish(out, 120.0, fin=0.01)
    sync = _peak_near(out, kp, int(0.15 * n), 0.08)
    return Render(out, sync_offset=sync, meta={"peak_s": round(sync / SR, 4)})


# =====================================================================================================
# audición de todo el módulo:  python -m sfx.recipes.designed [tag ...]
# =====================================================================================================

AUDITIONS = [
    # (receta, dur, params, at, gain, tag, seed)
    ("des.whoosh", 0.7, {"style": "air", "direction": 1, "peak_pos": 0.7, "brightness": 0.6}, 2.75, -9, "whoosh_air", 0),
    ("des.whoosh", 0.7, {"style": "air", "direction": 1, "peak_pos": 0.7, "brightness": 0.6}, None, None, "whoosh_air_s1", 1),
    ("des.whoosh", 0.6, {"style": "air", "direction": -1, "peak_pos": 0.65, "brightness": 0.7}, 35.75, -12, "whoosh_air_snow", 0),
    ("des.whoosh", 1.2, {"style": "body", "direction": 1, "peak_pos": 0.6, "brightness": 0.4}, 12.875, -12, "whoosh_body", 0),
    ("des.whoosh", 0.9, {"style": "tonal", "direction": 1, "peak_pos": 0.5, "brightness": 0.45}, 34.917, -10, "whoosh_tonal", 0),
    ("des.whoosh", 0.9, {"style": "spin", "direction": 1, "peak_pos": 0.4, "brightness": 0.5}, 1.583, -14, "whoosh_spin", 0),
    ("des.whoosh", 1.4, {"style": "deep", "direction": 1, "peak_pos": 0.55, "brightness": 0.3}, 16.5, -10, "whoosh_deep", 0),
    ("des.whoosh", 1.1, {"style": "flutter", "direction": 1, "peak_pos": 0.5, "brightness": 0.5}, 37.333, -12, "whoosh_flutter", 0),
    ("des.air_suck", 0.55, {"brightness": 0.4}, 2.25, -12, "air_suck", 0),
    ("des.sub_impact", 1.6, {"f_start": 80, "f_end": 38, "decay": 1.3, "body": 0.4}, 3.958, -8, "sub_impact", 0),
    ("des.sub_impact", 2.4, {"f_start": 80, "f_end": 34, "decay": 2.0, "body": 0.5}, 44.042, -8, "sub_impact_logo", 1),
    ("des.soft_impact", 1.5, {"brightness": 0.5, "tail": 1.2}, 13.292, -7, "soft_impact", 0),
    ("des.soft_impact", 0.8, {"brightness": 0.3, "tail": 0.5}, None, None, "soft_impact_s1", 1),
    ("des.reverse_swell", 1.0, {"source": "bell", "note": "Bb4"}, 1.208, -10, "reverse_swell_bell", 0),
    ("des.reverse_swell", 1.1, {"source": "noise", "note": "Bb4"}, 23.625, -10, "reverse_swell_noise", 0),
    ("des.reverse_swell", 1.017, {"source": "hit", "note": "F4"}, None, None, "reverse_swell_hit", 0),
    ("des.riser", 1.45, {"start_hz": 200, "end_hz": 7000, "shepard": True}, 43.917, -12, "riser", 0),
    ("des.glint", 1.2, {"note": "F6", "ratio": 3.5, "decay": 1.2, "sparkle": 0.5, "delay": True}, 4.167, -12, "glint_F6", 0),
    ("des.glint", 1.2, {"note": "F6", "ratio": 3.5, "decay": 1.2, "sparkle": 0.5, "delay": True}, None, None, "glint_F6_s1", 1),
    ("des.glint", 1.4, {"note": "Db7", "ratio": 3.5, "decay": 1.3, "sparkle": 0.8, "delay": True}, 18.0, -13, "glint_Db7", 0),
    ("des.glint", 1.0, {"note": "F7", "ratio": 3.5, "decay": 0.8, "sparkle": 0.9, "delay": True}, 35.833, -14, "glint_F7_snow", 0),
    ("des.glint", 1.5, {"note": "Bb5", "ratio": 1.4, "decay": 1.2, "sparkle": 0.2, "delay": False}, None, None, "glint_bell", 0),
    ("des.led_sweep", 1.05, {"count": 10, "pan_from": -0.8, "pan_to": 0.8}, 26.333, -10, "led_sweep", 0),
    ("des.led_sweep", 1.05, {"count": 10, "pan_from": -0.8, "pan_to": 0.8}, None, None, "led_sweep_s1", 1),
    ("des.ev_motif", 1.3, {"gesture": "swell", "root": "Bb2"}, 0.12, -17, "ev_motif_swell", 0),
    ("des.ev_motif", 2.3, {"gesture": "rise", "root": "Bb2"}, 3.958, -12, "ev_motif_rise", 0),
    ("des.ev_motif", 2.4, {"gesture": "rise", "root": "Bb2"}, None, None, "ev_motif_rise_s1", 1),
    ("des.ev_motif", 1.2, {"gesture": "resolve", "root": "Bb2"}, 48.583, -10, "ev_motif_resolve", 0),
    ("des.light_shaft", 2.0, {}, 23.625, -8, "light_shaft", 0),
    ("des.light_shaft", 2.0, {}, None, None, "light_shaft_s1", 1),
    ("des.mist_texture", 1.6, {"brightness": 0.45, "drift": 0.5}, 0.0, -13, "mist_open", 0),
    ("des.mist_texture", 6.7, {"brightness": 0.5, "drift": 0.6}, 8.0, -19, "mist_long", 0),
    ("des.mist_texture", 3.2, {"brightness": 0.75, "drift": 0.4}, 46.583, -16, "mist_stinger", 1),
    ("des.drone", 3.2, {"note": "Bb1", "brightness": 0.25}, 6.5, -21, "drone_pov", 0),
    ("des.drone", 2.9, {"note": "Bb1", "brightness": 0.3}, 46.833, -17, "drone_stinger", 1),
    ("des.spatial_bloom", 1.2, {}, 27.458, -12, "spatial_bloom", 0),
    ("des.spatial_bloom", 1.2, {}, None, None, "spatial_bloom_s1", 1),
    ("des.logo_signature", 2.5, {}, 44.042, -6, "logo_signature", 0),
    ("des.logo_signature", 2.5, {}, None, None, "logo_signature_s1", 1),
    ("des.awakening", 1.2, {}, 48.583, -4, "awakening", 0),
    ("des.awakening", 1.2, {}, None, None, "awakening_s1", 1),
    ("des.ui_tone", 0.6, {"note": "Eb7"}, 31.208, -16, "ui_tone_Eb7", 0),
    ("des.ui_tone", 0.8, {"note": "Ab6"}, 39.083, -17, "ui_tone_Ab6", 1),
    ("des.breath_designed", 1.0, {}, 10.667, -9, "breath", 0),
    ("des.breath_designed", 1.0, {}, None, None, "breath_s1", 1),
    ("des.wind_swell", 1.6, {"brightness": 0.45}, 18.917, -12, "wind_swell", 0),
    ("des.wind_swell", 1.2, {"brightness": 0.5}, 30.625, -10, "wind_swell_lake", 1),
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
    importlib.import_module("sfx.recipes.designed")

    def _safe_load():
        from .. import recipes as pkg
        for mm in pkgutil.iter_modules(pkg.__path__):
            try:
                importlib.import_module(f"{pkg.__name__}.{mm.name}")
            except Exception as e:  # módulos ajenos rotos no deben impedir auditar éste
                print(f"[warn] no se pudo importar {mm.name}: {e}", file=sys.stderr)
        return core.RECIPES

    au.load_all_recipes = _safe_load
    for name, dur, params, at, gain, tag, seed in AUDITIONS:
        if only and not any(o in tag or o == name for o in only):
            continue
        met = au.audition(name, dur, params, seed=seed, at=at, gain=gain, tag=tag)
        ctx = met.get("context", {}).get("sfx_vs_bed_db_by_band", {})
        print(f"{tag:24s} pk {met['peak_dbfs']:6.1f} rms {met['rms_dbfs']:6.1f} cen {met['centroid_hz']:6.0f} "
              f"lr {met.get('lr_corr')} sync {met['sync_s']} epk {met['energy_peak_s']} rise {met['sync_rise_db']} "
              f"clk {met['click_candidates']} {met['click_times_s'][:5]} dc {met['dc_db']} "
              f"ac {met.get('max_autocorr_0.1-5s')}"
              + (f" | ctx pres {ctx.get('pres2k-5k')} hi {ctx.get('high5k-10k')} air {ctx.get('air10k+')}"
                 f" mid {ctx.get('mid500-2k')} low {ctx.get('low60-150')} sub {ctx.get('sub<60')}" if ctx else ""),
              flush=True)


if __name__ == "__main__":
    import sys as _sys

    _audition_all(_sys.argv[1:] or None)
