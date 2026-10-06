"""Creature family: giant pandas (steps, breath, paw on glass, crowd, fur), geese, city sparrows.

Design notes (foley thinking, layer by layer):
  * Pandas are ~100 kg plantigrade animals with soft furry pads. They never vocalize in this spot:
    only steps, breath, sniffs and fur. Every footfall / breath is re-synthesized from the rng.
  * Footfall = heel/pad thud (damped sine 70-120 Hz with settling pitch + flesh noise body, soft attack)
    + pad "pat" (resonant BP noise 400-1500 Hz) + surface layer (wet: velvet tack + Minnaert micro-splash
    + film hiss + sticky peel at lift-off; dry: stochastic grit particles + pad scuff + toe scuff at
    lift-off) + occasional claw tick (tiny modal 3-5 kHz) + fur shake (granular hair friction 2.5-8 kHz).
  * Breath = source-filter: turbulent noise through drifting formants (~400 / 1200 / 2500 Hz) + chest
    component (150-300 Hz) + nostril air; sniff = short nasal inhalations whose turbulence rises in pitch;
    huff = snort burst with irregular nostril flutter (40-80 Hz) + chest.
  * Paw on glass (from inside) = soft exciter into laminated-windshield modes (85-410 Hz + weak upper
    modes) + stick-slip squeak (pulse train 300-900 Hz gliding, BP 1-4 kHz) + fur on glass + sticky
    release + sniff through the glass, all in the small cabin.
  * Fur / grit / feathers = stochastic particles: Poisson micro-events with lognormal weights, low-passed
    (zero-phase) into a shot-noise amplitude that modulates fresh noise. The low-pass sets the granularity:
    ~55-110 Hz for soft fur (swish, no crackle), 150-260 Hz for feathers, 250-380 Hz for grit. Then a
    drifting band-pass. Every event therefore has unique micro-structure.
  * Geese: per-bird wingbeat whuffs + feather rustle (3-4 Hz, own phase/rate drift), distance envelope
    over a staggered V; sparse far honks (polyBLEP pulse with rise-fall contour peaking on a key note,
    formants 1 / 2.5 kHz, light tanh) in a valley space; optional muffling by the sunroof glass.
  * Sparrows: FM sweeps 4-7 kHz (cheep / down / up / chevron / trill) with syrinx flutter, 2nd harmonic,
    occasional second syrinx voice and breath noise, in short phrases (a bird mostly repeats its own call),
    2-3 birds spread across the street space.
  * Hygiene: 120 Hz 24 dB/oct high-pass by default, 70 Hz on intentional bodies/thuds; fades >= 3 ms;
    all randomness from `rng`; sync offsets exact (steps: first contact; glass: contact transient).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import signal

from .. import dsp
from ..core import SR, Render, recipe

FAM = "creature"
TWO_PI = 2.0 * np.pi


# ====================================================================== small helpers

def _db(x):
    return 10.0 ** (np.asarray(x, dtype=np.float64) / 20.0)


def _n(s) -> int:
    return max(1, int(round(float(s) * SR)))


def _pk(x) -> float:
    return float(np.abs(x).max()) + 1e-12


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2))) + 1e-12


def _unit(x):
    """Peak-normalize a layer (layers are balanced in dB afterwards)."""
    return np.asarray(x, np.float64) / _pk(x)


@lru_cache(maxsize=1024)
def _sos(order, fc, kind):
    return dsp.butter_sos(order, list(fc) if isinstance(fc, tuple) else fc, kind)


def _hp(x, fc=120.0, order=4):
    return signal.sosfilt(_sos(order, round(float(fc), 1), "highpass"), x, axis=0)


def _lp(x, fc, order=2):
    return signal.sosfilt(_sos(order, round(float(fc), -1), "lowpass"), x, axis=0)


def _bp(x, lo, hi, order=2):
    band = (round(float(lo), -1), round(float(min(hi, SR * 0.45)), -1))
    return signal.sosfilt(_sos(order, band, "bandpass"), x, axis=0)


def _rbp(x, fc, q):
    """Constant-peak (0 dB) resonant band-pass."""
    b, a = dsp.rbj("bandpass", fc, q)
    return signal.lfilter(b, a, x, axis=0)


def _add(dst, src, t_s, gain=1.0):
    """Mix src into dst at time t_s (seconds)."""
    dsp.mix_into(dst, src, int(round(t_s * SR)), gain)
    return dst


def _env_ar(n, attack, tau, shape=1.0):
    """Raised-cosine attack (s) then exponential decay (tau, s)."""
    t = np.arange(n) / SR
    attack = max(attack, 1.0 / SR)
    e = np.exp(-np.maximum(t - attack, 0.0) / max(tau, 1e-5))
    up = t < attack
    e[up] = (0.5 - 0.5 * np.cos(np.pi * t[up] / attack)) ** shape
    return e


def _env_asym(n, peak_frac=0.25, a_pow=1.4, r_pow=2.0):
    """Asymmetric 0 -> 1 -> 0 envelope with smooth ends (breath, swells)."""
    k = int(np.clip(peak_frac, 0.02, 0.98) * n)
    k = max(2, min(n - 2, k))
    x = np.linspace(0.0, 1.0, k, endpoint=False)
    up = (0.5 - 0.5 * np.cos(np.pi * x)) ** a_pow
    y = np.linspace(0.0, 1.0, n - k)
    down = (1.0 - y) ** r_pow * (0.5 + 0.5 * np.cos(np.pi * y)) ** 0.5
    return np.concatenate([up, down])


def _walk_ctrl(m, rng, rate, kr):
    """Smooth drift-free random walk at control rate kr (m points), normalized to |max| = 1."""
    k = max(4, int(m / kr * rate * 8) + 4)
    pts = np.cumsum(rng.standard_normal(k))
    pts -= np.linspace(pts[0], pts[-1], k)
    y = np.interp(np.linspace(0, 1, m), np.linspace(0, 1, k), pts)
    w = max(3, int(kr / (rate * 6)))
    if w < m:
        ker = np.hanning(w)
        y = np.convolve(y, ker / ker.sum(), mode="same")
    return y / (np.abs(y).max() + 1e-12)


def _lfn(n, rng, rate_hz=1.0, depth=1.0):
    """Bounded 1/f-like modulator in [-depth, depth]: 3 octaves of smooth random walks built at control
    rate and interpolated (cheap for long beds)."""
    kr = max(64.0, 20.0 * rate_hz * 8.3)
    m = int(n / SR * kr) + 8
    y = (_walk_ctrl(m, rng, rate_hz, kr) + 0.5 * _walk_ctrl(m, rng, rate_hz * 2.9, kr)
         + 0.25 * _walk_ctrl(m, rng, rate_hz * 8.3, kr))
    y /= (np.abs(y).max() + 1e-12)
    return depth * np.interp(np.arange(n) * ((m - 1) / max(n - 1, 1)), np.arange(m), y)


def _fade(x, fin=0.004, fout=0.01):
    return dsp.fade(x, fin, fout)


def _st(x):
    return dsp.stereo(x)


# ====================================================================== granular particles

def _shot_env(n, rng, rate, fcut=80.0, sigma=0.8):
    """Smooth shot-noise envelope (mean ~1): Poisson hits with lognormal weights, zero-phase low-passed.
    fcut sets the granularity (60-100 Hz = soft swish, 200-400 Hz = gritty)."""
    rate = dsp.as_curve(rate, n)
    hits = np.nonzero(rng.random(n) < np.clip(rate / SR, 0.0, 0.5))[0]
    imp = np.zeros(n)
    if len(hits):
        imp[hits] = rng.lognormal(0.0, sigma, len(hits))
    if n > 30:
        imp = signal.sosfiltfilt(_sos(2, round(float(fcut), 1), "lowpass"), imp)
    e = np.maximum(imp, 0.0)
    return e / (e.mean() + 1e-12)


def _fur(n, rng, env, rate=8000.0, lo=2500.0, hi=8000.0, sigma=0.5, drift=0.18, fcut=70.0):
    """Fur friction: dense hair-on-hair micro-events -> smooth shot-noise amplitude (soft, swishy; no
    crackle), drifting band-pass, shaped by `env` (amplitude, rate floor 35 %)."""
    env = np.clip(np.asarray(env, np.float64), 0.0, None)
    en = env / (env.max() + 1e-12)
    g = rng.standard_normal(n) * _shot_env(n, rng, rate * (0.35 + 0.65 * en), fcut, sigma)
    fc = np.sqrt(lo * hi) * (1.0 + _lfn(n, rng, 4.0, drift))
    y = dsp.tv_filter(g, fc, "bandpass", q=0.75, block=128 if n < SR else 384)  # drift is slow (4 Hz)
    y = _bp(y, lo, hi, 2)
    return y * en


def _bus_comp(x, over_db=9.0, ratio=3.0, smooth_hz=25.0):
    """Gentle look-ahead bus compressor for beds: zero-phase envelope of |x|, threshold `over_db` above
    the bus RMS, soft ratio. Keeps a sparse bed calm without touching its texture."""
    x = np.asarray(x, np.float64)
    mag = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    env = signal.sosfiltfilt(_sos(2, float(smooth_hz), "lowpass"), mag)
    env = np.maximum(env, 1e-12)
    thr = _rms(mag) * _db(over_db)
    g = np.where(env > thr, (thr / env) ** (1.0 - 1.0 / ratio), 1.0)
    return x * (g[:, None] if x.ndim == 2 else g)


def _peak_soft(x, over_db=13.0):
    """Transparent tanh peak-rounding `over_db` above the RMS (only rare noise crests are touched)."""
    c = _rms(x) * _db(over_db)
    return c * np.tanh(np.asarray(x, np.float64) / c)


# ====================================================================== space / distance

_DIST = {  # send dB, LP on detail (Hz, None = open), low-body trim dB
    "close": (-24.0, None, 0.0),
    "mid": (-13.0, 11000.0, -1.0),
    "far": (-9.0, 5000.0, -5.0),
}


def _space(x, preset, send_db, hp_send=160.0):
    if not preset or preset == "none":
        return _st(x)
    return dsp.reverb(_st(x), preset, send_db, dry=1.0, hp_send=hp_send)


def _finish(y, fin=0.003, fout=0.02, keep=0, floor_db=-80.0):
    """Trim the inaudible tail (below floor_db re peak, never before sample `keep`), fade both edges."""
    y = np.nan_to_num(np.asarray(y, np.float64))
    e = np.abs(y).max(axis=1) if y.ndim == 2 else np.abs(y)
    above = np.nonzero(e > _pk(e) * _db(floor_db))[0]
    end = max(int(keep), (int(above[-1]) + _n(0.02)) if len(above) else len(y))
    y = y[: min(len(y), end)]
    return dsp.fade(y, fin, fout)


# ====================================================================== panda footfall

def _thud(rng, weight=1.0, fore=False):
    """Heel/pad thud: soft-attack damped sine 70-120 Hz with settling pitch + inharmonic flesh mode
    + low-passed flesh-compression noise."""
    f0 = rng.uniform(84.0, 112.0) * (1.0 - 0.08 * (weight - 1.0)) * (1.07 if fore else 1.0)
    f0 = float(np.clip(f0, 72.0, 122.0))
    tau = rng.uniform(0.016, 0.026) * (0.85 + 0.15 * weight)
    att = rng.uniform(0.004, 0.008) if fore else rng.uniform(0.005, 0.010)
    m = _n(att + 8.0 * tau + 0.01)
    t = np.arange(m) / SR
    f = f0 * (1.0 + rng.uniform(0.03, 0.08) * np.exp(-t / 0.015))
    ph = TWO_PI * np.cumsum(f) / SR
    s = np.sin(ph) * _env_ar(m, att, tau)
    s += rng.uniform(0.2, 0.35) * np.sin(ph * rng.uniform(2.25, 2.75) + rng.uniform(0, TWO_PI)) * \
        _env_ar(m, att * 0.8, tau * 0.45)
    # flesh compression noise: carries the "thup" (200-450 Hz) that survives on small speakers
    nb = _lp(rng.standard_normal(m), rng.uniform(320.0, 480.0), 2) * _env_ar(m, att * 0.7, tau * 0.7)
    s += rng.uniform(0.55, 0.75) * nb / _pk(nb)
    return _unit(s)


def _pat(rng):
    """Pad 'pat': resonant BP noise 400-1500 Hz, 15-30 ms."""
    plen = rng.uniform(0.015, 0.03)
    m = _n(plen * 3.0)
    x = _rbp(rng.standard_normal(m), rng.uniform(520.0, 1000.0), rng.uniform(0.9, 1.5))
    x = _bp(x, 400.0, 1500.0, 2) * _env_ar(m, rng.uniform(0.001, 0.0025), plen / 3.0)
    return _unit(x)


def _tack(rng, lo=2000.0, hi=6000.0, length=None, density=None, pops=None):
    """Wet tack: water film sealing under the pad. Dense random-amplitude velvet (sticky hiss) plus
    1-3 discrete sticky pops; band-limited, 20-40 ms."""
    tl = length or rng.uniform(0.02, 0.04)
    m = _n(tl * 2.5)
    v = dsp.velvet(m, rng, density or rng.uniform(12000.0, 20000.0)) * rng.lognormal(0.0, 0.4, m)
    k = int(rng.integers(1, 4)) if pops is None else int(pops)
    for _ in range(k):
        i = int(rng.uniform(0.0, 0.6) * tl * SR)
        v[i: i + 3] += rng.choice([-1.0, 1.0]) * rng.uniform(2.0, 4.0) * np.array([0.5, 1.0, 0.5])
    v = _bp(v, lo, hi, 2) * _env_ar(m, 0.0015, tl / 3.0)
    return _unit(v)


def _drop(rng, f_lo=2600.0, f_hi=6000.0):
    """Micro-splash droplet (Minnaert bubble of a ~0.5-1.2 mm drop)."""
    m = _n(0.045)
    b = dsp.bubble(rng.uniform(f_lo, f_hi), rng.uniform(0.003, 0.008), m, glide=rng.uniform(0.08, 0.25), rng=rng)
    return _unit(_fade(b, 0.0005, 0.005))


def _grit(rng, length, rate=(6000.0, 12000.0), pops=None):
    """Dry grit crushed under a soft pad: dense shot-noise texture (granularity ~300 Hz) 1.8-7 kHz,
    plus 0-2 slightly bigger grains. The fur/flesh of the pad keeps it soft (no sharp crackle)."""
    m = _n(length * 2.0)
    e = _env_ar(m, 0.003, length / 3.0)
    g = rng.standard_normal(m) * _shot_env(m, rng, rng.uniform(*rate), rng.uniform(250.0, 380.0), 0.7) * e
    k = int(rng.integers(0, 3)) if pops is None else int(pops)
    for _ in range(k):
        i = int(rng.uniform(0.05, 0.8) * length * SR)
        ln = _n(rng.uniform(0.0008, 0.002))
        g[i: i + ln] += rng.standard_normal(min(ln, m - i)) * rng.uniform(1.5, 3.0) * e[i]
    g = _lp(_bp(g, 1800.0, 8000.0, 2), 7000.0, 2)
    return _unit(_fade(g, 0.0, length * 0.5))


def _scuff(rng, length, f_from=(1100.0, 1600.0), f_to=(1800.0, 2800.0)):
    """Pad sliding on rough asphalt: noise through a sweeping band-pass."""
    m = _n(length * 2.2)
    fc = np.geomspace(rng.uniform(*f_from), rng.uniform(*f_to), m)
    x = dsp.tv_filter(rng.standard_normal(m), fc, "bandpass", q=rng.uniform(0.8, 1.3), block=64)
    x = _bp(x, 800.0, 4500.0, 2) * _env_ar(m, length * 0.25, length / 3.0)
    return _unit(_fade(x, 0.0, length * 0.6))


def _claw(rng):
    """Claw tick: tiny 2-mode resonance 3-5 kHz, ~3 ms."""
    m = _n(0.008)
    cf = rng.uniform(3000.0, 5000.0)
    exc = np.hanning(7)
    y = dsp.modal(m, [cf, cf * rng.uniform(1.35, 1.6)], [rng.uniform(0.0006, 0.0015), rng.uniform(0.0004, 0.001)],
                  [0.0, rng.uniform(-8.0, -4.0)], rng, exciter=exc)
    return _unit(_fade(y, 0.0003, 0.002))


def _footfall(rng, *, weight=1.0, fore=False, wet=True, stance=0.75, claw_p=0.35, fur_db=-27.0):
    """One footfall with its own lift-off. Contact (thud onset) at sample 0.
    Returns (low_mono, detail_mono, fur_stereo)."""
    L = stance + 0.35
    n = _n(L)
    low = np.zeros(n)
    det = np.zeros(n)
    wg = float(weight)
    # --- heel / pad thud (body)
    _add(low, _thud(rng, wg, fore), 0.0, wg)
    # --- pad pat (hind: heel first then pad roll; fore: pad lands with the contact)
    pad_t = rng.uniform(0.0, 0.006) if fore else rng.uniform(0.012, 0.03)
    _add(det, _pat(rng), pad_t, _db(rng.uniform(-9.0, -6.0)) * wg ** 0.5)
    lift_t = stance * rng.uniform(0.85, 1.0)
    if wet:
        _add(det, _tack(rng), pad_t + rng.uniform(0.0, 0.004), _db(rng.uniform(-14.0, -10.0)))
        for _ in range(int(rng.integers(1, 4))):
            _add(det, _drop(rng), pad_t + rng.uniform(0.006, 0.05), _db(rng.uniform(-29.0, -21.0)))
        hm = _n(0.11)
        h = _bp(rng.standard_normal(hm), 4000.0, 11000.0, 2) * _env_ar(hm, 0.004, rng.uniform(0.012, 0.02))
        _add(det, _unit(_fade(h, 0.0, 0.03)), pad_t, _db(rng.uniform(-25.0, -20.0)))
        # sticky peel of the pad leaving the wet film
        pl = rng.uniform(0.04, 0.08)
        pm = _n(pl * 1.6)
        v = dsp.velvet(pm, rng, rng.uniform(1500.0, 3500.0)) * rng.lognormal(0.0, 0.7, pm)
        v = _bp(v, 1500.0, 5000.0, 2) * _env_asym(pm, rng.uniform(0.3, 0.5), 1.2, 1.5)
        _add(det, _unit(v), lift_t, _db(rng.uniform(-25.0, -20.0)))
        if rng.random() < 0.5:
            _add(det, _drop(rng, 2000.0, 4500.0), lift_t + rng.uniform(0.02, 0.06), _db(rng.uniform(-28.0, -22.0)))
    else:
        gl = rng.uniform(0.03, 0.07)
        _add(det, _grit(rng, gl), pad_t + rng.uniform(0.0, 0.004), _db(rng.uniform(-15.0, -11.0)))
        sl = rng.uniform(0.04, 0.09)
        _add(det, _scuff(rng, sl), pad_t + rng.uniform(0.003, 0.012), _db(rng.uniform(-19.0, -15.0)))
        # toe scuff at lift-off
        ll = rng.uniform(0.06, 0.12)
        _add(det, _grit(rng, ll, (900.0, 2200.0)), lift_t, _db(rng.uniform(-25.0, -20.0)))
        _add(det, _scuff(rng, ll, (1600.0, 2400.0), (900.0, 1400.0)), lift_t + 0.005, _db(rng.uniform(-25.0, -20.0)))
    # --- claws
    if rng.random() < claw_p:
        t0 = pad_t + rng.uniform(0.002, 0.025)
        for j in range(int(rng.integers(1, 3))):
            _add(det, _claw(rng), t0 + j * rng.uniform(0.006, 0.02), _db(rng.uniform(-24.0, -19.0)))
    if rng.random() < claw_p * 0.5:
        _add(det, _claw(rng), lift_t + rng.uniform(0.0, 0.03), _db(rng.uniform(-28.0, -23.0)))
    # --- fur shake (body mass moving with the step)
    fl = rng.uniform(0.25, 0.4)
    fm = _n(fl)
    fenv = dsp.swell(fm, rng.uniform(0.25, 0.4), 1.5, 2.0)
    fur = np.stack([_fur(fm, rng, fenv, rate=rng.uniform(5000.0, 9000.0)),
                    _fur(fm, rng, fenv, rate=rng.uniform(5000.0, 9000.0))], axis=1)
    fur_st = np.zeros((n, 2))
    _add(fur_st, fur / _pk(fur), rng.uniform(0.01, 0.04), _db(fur_db + rng.uniform(-3.0, 2.0)))
    return low, det, fur_st


def _gait_times(steps, gait_s, rng, lateral=0.12, jitter_s=0.015):
    """Lateral-sequence walk: LH, LF, RH, RF... same-side hind->fore couplet slightly closer."""
    t, out = 0.0, []
    for i in range(int(steps)):
        out.append(t)
        frac = (1.0 - lateral) if i % 2 == 0 else (1.0 + lateral)
        t += gait_s * frac
    out = np.array(out)
    if len(out) > 1:
        out[1:] += np.clip(rng.normal(0.0, jitter_s / 2.0, len(out) - 1), -jitter_s, jitter_s)
    return np.sort(out)


_FEET = ["LH", "LF", "RH", "RF"]


@recipe("cre.panda_steps", family=FAM, sync="start", kind="event")
def panda_steps(dur, rng, *, steps=4, gait_s=0.3, surface="wet_asphalt", weight=1.0, step_times=None,
                distance="mid", space="auto", side_spread=0.14, claws=0.35, fur=1.0, body_db=0.0, detail_db=0.0,
                **_):
    """Giant panda footsteps. sync = first contact (thud onset).
    step_times: list of seconds relative to the first contact (overrides steps/gait_s).
    distance: close|mid|far. space: auto (wet -> city_fog_street, dry -> city_day_street) | preset | none.
    body_db / detail_db: level of the heel thud vs. the pad/surface/claw/fur detail (e.g. body_db=-6 under
    dense music, where the 70-150 Hz thud is masked anyway and only the detail reads)."""
    wet = "wet" in str(surface)
    if step_times is not None and len(step_times):
        times = np.sort(np.asarray(step_times, np.float64))
        times = times - times[0]
    else:
        times = _gait_times(max(1, int(steps)), float(gait_s), rng)
        times = times[times < max(float(dur) - 0.02, 0.0) + 1e-9] if dur else times
        if len(times) == 0:
            times = np.array([0.0])
    # stance phase ~ 62 % of the stride (stride = 4 contacts)
    stride = 4.0 * (float(np.median(np.diff(times))) if len(times) > 1 else float(gait_s))
    stance = float(np.clip(0.62 * stride, 0.25, 1.2))
    send_db, det_lp, low_trim = _DIST.get(str(distance), _DIST["mid"])
    preset = space
    if space == "auto":
        preset = "city_fog_street" if wet else "city_day_street"

    pre = 0.0
    total = times[-1] + stance + 0.5
    n = _n(max(total, float(dur) + 0.1))
    low = np.zeros((n, 2))
    det = np.zeros((n, 2))
    furb = np.zeros((n, 2))
    # bounded 1/f gait unevenness on step level (+-1.5 dB)
    lvl = _lfn(max(8, len(times) * 64), rng, 1.0, 1.5)[:: 64][: len(times)] if len(times) > 1 else np.zeros(1)
    feet = []
    for i, t in enumerate(times):
        foot = _FEET[i % 4]
        fore = foot.endswith("F")
        side = -1.0 if foot.startswith("L") else 1.0
        w = float(weight) * (0.82 if fore else 1.0) * rng.uniform(0.9, 1.1) * _db(lvl[i])
        lo_m, de_m, fu_s = _footfall(rng, weight=w, fore=fore, wet=wet, stance=stance,
                                     claw_p=float(claws) * (1.4 if fore else 0.6),
                                     fur_db=-27.0 + 20 * np.log10(max(float(fur), 1e-3)))
        p = side * float(side_spread) * rng.uniform(0.7, 1.3)
        _add(low, dsp.pan(lo_m, p * 0.5), pre + t)
        _add(det, dsp.pan(de_m, p), pre + t)
        _add(furb, fu_s, pre + t)
        feet.append({"t": round(float(t), 4), "foot": foot, "w": round(w, 2)})
    low = _hp(low, 70.0, 4) * _db(low_trim + float(body_db))
    det = _hp(det + furb, 120.0, 4) * _db(float(detail_db))
    if det_lp:
        det = _lp(det, det_lp, 2)
    y = _space(low + det, preset, send_db)
    y = _finish(y, 0.003, 0.03)
    return Render(y, sync_offset=_n(pre) if pre else 0,
                  meta={"contacts": feet, "stance_s": round(stance, 3), "space": preset, "distance": distance})


# ====================================================================== panda breath

def _formant_noise(n, rng, formants, drift=0.06, slope=-1.5, rate=3.0):
    src = dsp.colored(n, rng, slope)
    y = np.zeros(n)
    for fc, q, gdb in formants:
        fcurve = fc * (1.0 + _lfn(n, rng, rate, drift))
        y += _db(gdb) * dsp.tv_filter(src, fcurve, "bandpass", q=q, block=128)
    return y


def _flutter(n, rng, f_lo, f_hi, depth, decay_tau=None):
    """Irregular AM (nostril / lip flutter): jittered-period raised-cosine dips, never periodic."""
    f = rng.uniform(f_lo, f_hi) * (1.0 + _lfn(n, rng, 6.0, 0.12))
    ph = np.cumsum(f) / SR
    cyc = np.floor(ph).astype(int)
    dj = rng.uniform(0.5, 1.0, cyc.max() + 2)[cyc]  # per-cycle depth jitter
    am = 1.0 - depth * dj * (0.5 + 0.5 * np.cos(TWO_PI * ph))
    if decay_tau:
        d = np.exp(-np.arange(n) / SR / decay_tau)
        am = 1.0 - (1.0 - am) * d
    return am


def _exhale(rng, length=0.55, close=True):
    """Slow warm exhale through the nose: formant noise + chest + nostril air."""
    n = _n(length)
    env = _env_asym(n, rng.uniform(0.18, 0.3), rng.uniform(1.2, 1.8), rng.uniform(1.6, 2.4))
    env *= _db(_lfn(n, rng, 5.0, 1.0))
    F = [(rng.uniform(370.0, 430.0), rng.uniform(2.0, 3.0), 0.0),
         (rng.uniform(1100.0, 1300.0), rng.uniform(2.5, 3.5), rng.uniform(-6.0, -4.0)),
         (rng.uniform(2350.0, 2650.0), rng.uniform(3.0, 4.0), rng.uniform(-11.0, -8.0))]
    form = _formant_noise(n, rng, F)
    form /= _rms(form)
    chest_fc = rng.uniform(170.0, 260.0) * (1.0 + _lfn(n, rng, 2.0, 0.1))
    chest = dsp.tv_filter(dsp.colored(n, rng, -3.0), chest_fc, "bandpass", q=1.2, block=128)
    chest *= _flutter(n, rng, 16.0, 28.0, 0.35)
    chest /= _rms(chest)
    air = _bp(rng.standard_normal(n), 3000.0, 9000.0, 2)
    air /= _rms(air)
    y = form + (0.8 if close else 0.35) * chest * _db(rng.uniform(-2.0, 1.0)) + \
        0.28 * air * env ** 0.6 * _db(rng.uniform(-2.0, 2.0))
    y = y * env
    # a few wet nostril micro-crackles, only while air flows (scaled by the flow envelope)
    k = int(rng.integers(0, 4 if close else 2))
    ref = _rms(y)
    for _ in range(k):
        c = _tack(rng, 1500.0, 5000.0, rng.uniform(0.004, 0.01), rng.uniform(3000.0, 8000.0), pops=1)
        tc = rng.uniform(0.05, 0.7) * length
        flow = float(env[min(n - 1, _n(tc))])
        _add(y, c * ref * 2.5 * flow, tc, _db(rng.uniform(-8.0, -2.0)))
    return y


def _sniff_one(rng, length, close=True):
    n = _n(length)
    c0 = rng.uniform(1300.0, 2000.0)
    fc = np.geomspace(c0, c0 * rng.uniform(1.15, 1.4), n) * (1.0 + _lfn(n, rng, 12.0, 0.05))
    x = dsp.tv_filter(rng.standard_normal(n), fc, "bandpass", q=rng.uniform(1.2, 2.0), block=64)
    x /= _rms(x)
    air = _bp(rng.standard_normal(n), 3500.0, 8500.0, 2)
    x += 0.45 * air / _rms(air)
    if close:
        lowm = _bp(rng.standard_normal(n), 450.0, 950.0, 2)
        x += 0.35 * lowm / _rms(lowm)
    x = dsp.eq(x, "peak", rng.uniform(900.0, 1200.0), 4.0, 3.0)
    env = _env_asym(n, rng.uniform(0.3, 0.45), 1.3, 1.4)
    return x * env


def _sniffs(rng, close=True, count=None, exhale_after=None):
    k = int(count) if count else int(rng.integers(2, 4))
    lens = rng.uniform(0.07, 0.14, k)
    gaps = rng.uniform(0.04, 0.09, k)
    tot = float(lens.sum() + gaps.sum()) + 0.45
    y = np.zeros(_n(tot))
    t = 0.0
    strength = 1.0
    for i in range(k):
        _add(y, _sniff_one(rng, lens[i], close), t, strength * _db(rng.uniform(-1.5, 1.5)))
        t += lens[i] + gaps[i]
        strength *= rng.uniform(0.82, 1.05)
    if exhale_after is None:
        exhale_after = rng.random() < 0.6
    if exhale_after:
        ex = _exhale(rng, rng.uniform(0.18, 0.3), close)
        _add(y, ex / _pk(ex) * _pk(y), t + rng.uniform(0.0, 0.05), _db(rng.uniform(-10.0, -7.0)))
    return y


def _huff(rng, close=True):
    """Short snort: sharp turbulent burst 1-3 kHz with irregular nostril flutter + chest."""
    L = rng.uniform(0.16, 0.32)
    rel = rng.uniform(0.12, 0.2)
    n = _n(L + rel)
    att = rng.uniform(0.004, 0.009)
    tau = rng.uniform(0.05, 0.09)
    env = _env_ar(n, att, tau)
    env += 0.18 * _env_ar(n, att, tau * 3.0)
    # breath runs out: smooth release to zero over the last `rel` seconds
    k = _n(rel)
    env[-k:] *= 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, k))
    turb = _rbp(rng.standard_normal(n), rng.uniform(1400.0, 2200.0), rng.uniform(0.9, 1.3))
    turb = _bp(turb, 900.0, 3200.0, 2)
    turb /= _rms(turb)
    air = _bp(rng.standard_normal(n), 3000.0, 8000.0, 2)
    turb += 0.35 * air / _rms(air)
    turb *= _flutter(n, rng, 40.0, 80.0, rng.uniform(0.5, 0.8), decay_tau=rng.uniform(0.06, 0.12))
    chest = _lp(_hp(rng.standard_normal(n), 75.0, 2), rng.uniform(180.0, 250.0), 2)
    chest = chest / _rms(chest) * _env_ar(n, att * 1.4, rng.uniform(0.04, 0.07))
    y = turb * env + (0.9 if close else 0.4) * chest * _db(rng.uniform(-3.0, 0.0))
    return y


_BREATH_SPACE = {True: ("city_fog_street", -24.0, None), False: ("city_fog_street", -12.0, 6500.0)}


@recipe("cre.panda_breath", family=FAM, sync="start", kind="event")
def panda_breath(dur, rng, *, type="exhale", close=True, length=None, count=None, space="city_fog_street",
                 send_db=None, **_):
    """Panda breath (no vocalization). type: exhale | sniff | huff. close=True: proximity (more low-mid,
    drier). length (s) overrides the exhale length (default 0.45-0.7 s, capped by dur)."""
    close = bool(close)
    kind = str(type)
    if kind == "sniff":
        y = _sniffs(rng, close, count)
    elif kind == "huff":
        y = _huff(rng, close)
    else:
        L = float(length) if length else min(rng.uniform(0.45, 0.7), max(0.3, float(dur) * 0.95))
        y = _exhale(rng, L, close)
    _, sd, lpf = _BREATH_SPACE[close]
    if send_db is not None:
        sd = float(send_db)
    y = _hp(y, 110.0 if close else 140.0, 4)
    if lpf:
        y = _lp(y, lpf, 2)
    # point source (an animal's nose) placed in its space; width comes from the room, not from delays
    st = _space(y, space, sd)
    st = _finish(st, 0.003, 0.02)
    return Render(st, sync_offset=0, meta={"type": kind, "close": close})


# ====================================================================== paw on glass

_GLASS_LOW = [85.0, 140.0, 210.0, 290.0, 410.0]
_GLASS_HIGH = [560.0, 735.0, 940.0, 1220.0, 1580.0, 2050.0]


def _glass_hit(rng, exc_ms=10.0, n_s=0.9, bright=0.0, damp=1.0):
    """Laminated windshield panel struck by a soft exciter. damp < 1 shortens the low panel modes (a soft pad
    still pressed on the glass absorbs them; the panel re-rings only when the pad leaves)."""
    m = _n(n_s)
    fl = [f * (1.0 + rng.uniform(-0.04, 0.04)) for f in _GLASS_LOW]
    # laminated glass (PVB interlayer) is strongly damped: tau 20-35 ms on the low panel modes (T60 < 0.25 s;
    # a soft paw on a windshield thuds and dies, it does not ring)
    dm = float(np.clip(damp, 0.2, 1.0))
    tl = [tau * dm * rng.uniform(0.85, 1.15) for tau in (0.035, 0.032, 0.028, 0.024, 0.02)]
    al = [a + rng.uniform(-2.0, 2.0) for a in (-4.0, 0.0, -1.0, -3.0, -5.0)]
    fh = [f * (1.0 + rng.uniform(-0.05, 0.05)) for f in _GLASS_HIGH]
    th = [tau * rng.uniform(0.8, 1.2) for tau in (0.045, 0.038, 0.03, 0.025, 0.02, 0.015)]
    ah = [a + bright + rng.uniform(-3.0, 2.0) for a in (-12.0, -13.0, -15.0, -17.0, -19.0, -22.0)]
    k = max(8, int(exc_ms * 1e-3 * SR))
    exc = np.sin(np.linspace(0, np.pi, k)) ** 1.5
    exc += 0.08 * rng.standard_normal(k) * np.hanning(k)  # pad texture
    exc /= exc.sum()
    y = dsp.modal(m, fl + fh, tl + th, al + ah, rng, exciter=exc)
    return _unit(_fade(y, 0.0, min(0.25, n_s * 0.4)))


def _glass_tick(rng):
    """Claw tip touching the glass: tiny high-mode ring (2-6 kHz, tau 3-8 ms)."""
    m = _n(0.04)
    f0 = rng.uniform(1700.0, 2100.0)
    fr = [f0, f0 * rng.uniform(1.55, 1.7), f0 * rng.uniform(2.3, 2.6), f0 * rng.uniform(3.2, 3.6)]
    taus = [rng.uniform(0.004, 0.008), rng.uniform(0.003, 0.006), rng.uniform(0.002, 0.005), rng.uniform(0.0015, 0.004)]
    amps = [0.0, rng.uniform(-4.0, -1.0), rng.uniform(-7.0, -3.0), rng.uniform(-10.0, -6.0)]
    y = dsp.modal(m, fr, taus, amps, rng, exciter=np.hanning(5))
    return _unit(_fade(y, 0.0002, 0.01))


@recipe("cre.paw_on_glass", family=FAM, sync="transient", kind="event")
def paw_on_glass(dur, rng, *, press_ms=220, squeak=0.4, sniff=True, inside=True, fur=1.0, body_db=0.0,
                 claws=None, claw_db=0.0, contact_damp=0.55, **_):
    """Paw pressed against the windshield, heard from inside the car (inside=True).
    sync = contact transient (onset of the pad exciter). body_db trims the low glass thump vs. the
    contact detail (claw ticks, squeak, fur) - e.g. -4 under dense music + VO.
    claws = number of claw-tip glass ticks (default random 1-3), claw_db = their level offset (bright 2-7 kHz
    detail that survives VO carving; push it without raising the body). contact_damp scales the low panel
    decay while the pad is pressed (0.55: thud of ~0.1 s); the release re-rings undamped.
    Inside perspective: gentle 1-pole LP 10 kHz and -2 dB at 8 kHz (the glass radiates the contact detail
    with little loss above 5 kHz, which is the only band VO carving leaves free)."""
    press = float(np.clip(press_ms, 60.0, 900.0)) / 1000.0
    pre = 0.05
    tot = pre + press + 0.9
    n = _n(max(tot, float(dur) + 0.2))
    body = np.zeros(n)   # structure-borne, low (HP 70)
    det = np.zeros(n)    # contact noises radiated by the glass
    air = np.zeros(n)    # airborne exterior sounds (through glass if inside)
    c = pre
    # --- contact thump
    hit = _glass_hit(rng, rng.uniform(8.0, 14.0), 1.0, 0.0 if inside else 4.0, damp=contact_damp)
    _add(body, hit, c, _db(-2.0))
    # claw tips touching the glass just after the pad (1-3 tiny glassy ticks)
    nc = int(rng.integers(1, 4))
    if claws is not None:
        nc = int(np.clip(claws, 0, 6))
    for j in range(nc):
        _add(det, _glass_tick(rng), c + rng.uniform(0.006, 0.035) + 0.012 * j,
             _db(rng.uniform(-17.0, -12.0) + float(claw_db)))
    # pad slap itself (soft skin on glass)
    pm = _n(0.06)
    slap = _bp(rng.standard_normal(pm), 300.0, 1400.0, 2) * _env_ar(pm, 0.002, 0.012)
    _add(det, _unit(_fade(slap, 0.0, 0.02)), c, _db(-11.0 if inside else -7.0))
    # --- stick-slip squeak as the pad presses/slides
    sq = float(np.clip(squeak, 0.0, 1.0))
    if sq > 0.01:
        L = float(np.clip((0.1 + 0.15 * sq) * rng.uniform(0.9, 1.1), 0.1, max(0.1, min(0.25, press))))
        m = _n(L)
        fa, fb = rng.uniform(300.0, 450.0), rng.uniform(600.0, 900.0)
        x = np.linspace(0, 1, m)
        fcur = fa + (fb - fa) * (x ** rng.uniform(0.6, 1.4))
        fcur *= 1.0 + _lfn(m, rng, 10.0, 0.08)
        s = dsp.stick_slip(m, fcur, rng, jitter=0.05, sharp=0.0015)
        s = _bp(s, 1000.0, 4000.0, 2)
        for f, g in ((rng.uniform(1300, 1500), 6.0), (rng.uniform(2000, 2300), 5.0), (rng.uniform(2900, 3300), 4.0)):
            s = dsp.eq(s, "peak", f, 6.0, g)
        senv = _env_asym(m, rng.uniform(0.3, 0.6), 1.2, 1.2) * _db(_lfn(m, rng, 15.0, 2.0))
        _add(det, _unit(s * senv), c + rng.uniform(0.03, 0.07), _db(-15.0 + 12.0 * sq))
    # --- fur against the glass during the press
    fl = press + 0.16
    fm = _n(fl)
    fenv = _env_asym(fm, rng.uniform(0.2, 0.35), 1.0, 1.5)
    furx = _fur(fm, rng, fenv, rate=rng.uniform(6000.0, 10000.0), lo=3000.0, hi=8000.0, fcut=110.0)
    _add(det, _unit(furx), c - 0.01, _db(-15.0) * float(fur))
    # skin creak while pressing (low friction noise)
    cm = _n(press)
    cr = _bp(rng.standard_normal(cm), 500.0, 2200.0, 2) * _env_asym(cm, 0.4, 1.5, 1.5) * \
        _db(_lfn(cm, rng, 12.0, 3.0))
    _add(det, _unit(cr), c + 0.02, _db(-24.0))
    # --- sticky release when the pad leaves the glass
    rel = c + press * rng.uniform(0.95, 1.1)
    _add(body, _glass_hit(rng, rng.uniform(3.0, 5.0), 0.5, 3.0), rel, _db(rng.uniform(-17.0, -13.0)))
    _add(det, _tack(rng, 1000.0, 4000.0, rng.uniform(0.02, 0.04), rng.uniform(1500.0, 3000.0)), rel,
         _db(rng.uniform(-20.0, -16.0)))
    # --- sniff (exterior, through the glass)
    if sniff:
        sn = _sniffs(rng, True, None, exhale_after=False)
        if inside:
            sn = dsp.through_glass(sn)
        _add(air, _unit(sn), rel + rng.uniform(0.08, 0.2), _db(-12.0 if inside else -8.0))
    # --- assembly
    body = _hp(body, 70.0, 4) * _db(float(body_db))
    det = _hp(det, 120.0, 4)
    if inside:
        # glass panel radiation: gentle top roll-off only (the old -4 dB shelf at 5 kHz hid the hero detail)
        det = dsp.eq(dsp.one_pole_lp(det, 10000.0), "peak", 8000.0, 0.8, -2.0)
    air = _hp(air, 120.0, 4)
    p = rng.uniform(-0.12, 0.12)
    y = dsp.pan(body, p * 0.3) + dsp.pan(det, p) + dsp.pan(air, p * 0.6)
    preset, sd = ("cabin_small", -9.0) if inside else ("city_fog_street", -14.0)
    y = _space(y, preset, sd, hp_send=90.0)
    y = _finish(y, 0.003, 0.03)
    return Render(y, sync_offset=_n(pre), meta={"contact_s": pre, "release_s": round(rel, 3), "inside": inside})


# ====================================================================== fur rustle

def _fur_event(rng, L, intensity=0.5, bright=0.5):
    """A short fur movement = 2-4 overlapping strokes (hair sliding over hair), each with its own band,
    envelope and granularity, plus a soft low-mid swish of the fur mass. Stereo from partly shared
    strokes (natural width, no delays)."""
    n = _n(L)
    y = np.zeros((n, 2))
    k = int(rng.integers(2, 5))
    lo0 = 1800.0 + 1500.0 * bright
    hi0 = 6000.0 + 4000.0 * bright
    tot_env = np.zeros(n)
    for i in range(k):
        t0 = 0.0 if i == 0 else rng.uniform(0.0, 0.6) * L
        sl = max(0.06, rng.uniform(0.35, 0.8) * (L - t0))
        m = _n(sl)
        env = _env_asym(m, rng.uniform(0.2, 0.55), rng.uniform(1.0, 1.6), rng.uniform(1.2, 2.0))
        env *= _db(_lfn(m, rng, 10.0, 2.0))
        sh = rng.uniform(0.85, 1.2)
        lo, hi = lo0 * sh, min(hi0 * sh, 15000.0)
        rate = 5000.0 + 7000.0 * intensity
        fcut = 50.0 + 90.0 * intensity * rng.uniform(0.7, 1.3)
        g = _db(rng.uniform(-5.0, 0.0)) * (1.0 if i == 0 else rng.uniform(0.5, 0.9))
        shared = _fur(m, rng, env, rate=rate, lo=lo, hi=hi, fcut=fcut)
        sc = shared / _rms(shared)
        pan_i = rng.uniform(-0.35, 0.35)
        gl, gr = dsp.pan_gains(pan_i)
        st = np.zeros((m, 2))
        for ch, gc in ((0, gl), (1, gr)):
            own = _fur(m, rng, env, rate=rate, lo=lo, hi=hi, fcut=fcut)
            st[:, ch] = gc * 1.41 * (0.65 * sc + 0.75 * own / _rms(own))
        _add(y, st * g, t0)
        e2 = np.zeros(n)
        _add(e2, env * g, t0)
        tot_env += e2
    # soft body swish of the fur mass moving (low-mid)
    sw = _bp(rng.standard_normal(n), 300.0, 1400.0, 2) * tot_env
    y += _st(sw / _rms(sw) * _rms(y) * 0.35 * (0.5 + intensity))
    return y


@recipe("cre.fur_rustle", family=FAM, sync="start", kind="event")
def fur_rustle(dur, rng, *, intensity=0.5, brightness=0.5, space="none", send_db=-16.0, **_):
    """Short fur movement (granular hair friction + soft body swish)."""
    L = float(np.clip(dur, 0.12, 3.0))
    y = _fur_event(rng, L, float(intensity), float(brightness))
    y = _hp(y, 120.0, 4)
    y = _space(y, space, send_db)
    return Render(_finish(y, 0.004, 0.02), sync_offset=0, meta={"intensity": intensity})


# ====================================================================== panda crowd (bed)

def _far_step(rng, wet=True):
    lo, de, _f = _footfall(rng, weight=rng.uniform(0.7, 1.1), fore=bool(rng.random() < 0.5), wet=wet,
                           stance=rng.uniform(0.5, 0.8), claw_p=0.2, fur_db=-60.0)
    y = _hp(lo, 70.0, 4) * _db(-3.0) + _hp(de, 120.0, 4)
    return y


@recipe("cre.panda_crowd", family=FAM, sync="start", kind="bed")
def panda_crowd(dur, rng, *, density=0.5, distance="mid", space="city_fog_street", wet=True,
                layers=("fur", "presence", "breath", "steps"), **_):
    """Many pandas lining a street: fur shuffles spread in width/depth, distant huffs/breaths,
    a few soft distant steps. Wide, calm, mysterious. `layers` selects which layers to render
    (fur | presence | breath | steps); every layer always consumes the rng, so solos stay in sync."""
    layers = set([layers] if isinstance(layers, str) else layers)
    dens = float(np.clip(density, 0.05, 1.5))
    far = str(distance) == "far"
    preroll = 1.0
    T = float(dur) + preroll
    n = _n(T + 0.2)
    dry = np.zeros((n, 2))
    wetb = np.zeros((n, 2))
    depth_lo, depth_hi = (0.4, 1.0) if far else (0.12, 0.85)
    send_base = -12.0 if far else -14.0

    def place(x, pan_p, d, extra_db=0.0, lp_scale=1.0, slope_db=-10.0):
        x = np.asarray(x, np.float64)
        fc = (10000.0 * (1.0 - d) + 2400.0 * d) * lp_scale
        x = _lp(x, fc, 2)
        g = _db(slope_db * d + extra_db)
        st = dsp.pan(x, pan_p) * g
        return st, st * _db(send_base + 6.0 * d)

    # --- fur shuffles: 6-10 /s at density 0.5
    rate = (6.0 + 4.0 * rng.random()) * dens * 2.0
    for t in dsp.poisson_times(T, rate, rng):
        L = rng.uniform(0.08, 0.2)
        m = _n(L)
        env = _env_asym(m, rng.uniform(0.25, 0.6), 1.2, 1.5)
        c = np.exp(rng.uniform(np.log(1500.0), np.log(5000.0)))
        x = _fur(m, rng, env, rate=rng.uniform(8000.0, 12000.0), lo=max(1000.0, c / 1.6), hi=min(6500.0, c * 1.6))
        x = x / _rms(x) * 0.25 * _db(rng.uniform(-3.0, 0.0))   # loudness-consistent bursts
        p = float(np.clip(rng.normal(0.0, 0.55), -0.9, 0.9))
        d = depth_lo + (depth_hi - depth_lo) * rng.random() ** 0.6   # most animals are not right at the mic
        a, b = place(x, p, d, slope_db=-7.0)
        if "fur" in layers:
            _add(dry, a, t)
            _add(wetb, b, t)
    # --- continuous fine fur presence (keeps the bed alive between shuffles)
    envc = 0.6 + 0.4 * (0.5 + 0.5 * _lfn(n, rng, 0.6, 1.0))
    furL = _fur(n, rng, envc, rate=8000.0 * dens + 4000.0, lo=2000.0, hi=7000.0, fcut=55.0)
    furR = _fur(n, rng, envc, rate=8000.0 * dens + 4000.0, lo=2000.0, hi=7000.0, fcut=55.0)
    furC = _fur(n, rng, envc, rate=8000.0 * dens + 4000.0, lo=2000.0, hi=7000.0, fcut=55.0)
    pres = np.stack([0.6 * furC + 0.75 * furL, 0.6 * furC + 0.75 * furR], axis=1)
    pres = _lp(pres, 6000.0 if far else 8500.0, 2)
    pres_g = _db(-18.0 if not far else -22.0) / _rms(pres) * 0.25
    if "presence" in layers:
        dry += pres * pres_g
        wetb += pres * pres_g * _db(send_base)
    # --- distant huffs / exhales
    for t in dsp.poisson_times(T, 0.45 * dens * 2.0, rng):
        if rng.random() < 0.55:
            x = _huff(rng, close=False)
        else:
            x = _exhale(rng, rng.uniform(0.4, 0.7), close=False)
        x = _hp(x, 200.0, 4)  # distant breath: the chest is lost in the street, the air carries
        d = rng.uniform(max(depth_lo, 0.3), 1.0)
        p = float(np.clip(rng.normal(0.0, 0.6), -0.85, 0.85))
        a, b = place(_unit(x), p, d, rng.uniform(-11.0, -6.0), 0.8)
        if "breath" in layers:
            _add(dry, a, t)
            _add(wetb, b, t)
    # --- a few distant soft steps (small groups)
    for t in dsp.poisson_times(T, 0.5 * dens * 2.0, rng):
        p = float(np.clip(rng.normal(0.0, 0.6), -0.85, 0.85))
        d = rng.uniform(max(depth_lo, 0.35), 1.0)
        for j in range(int(rng.integers(1, 4))):
            x = _far_step(rng, bool(wet))
            a, b = place(_unit(x), p + rng.uniform(-0.05, 0.05), d, rng.uniform(-17.0, -11.0), 0.45)
            tt = t + j * rng.uniform(0.25, 0.4)
            if "steps" in layers:
                _add(dry, a, tt)
                _add(wetb, b, tt)
    rev = dsp.convolve(_hp(wetb, 150.0, 2), dsp.ir_preset(space), wet=1.0) if space and space != "none" else wetb
    y = np.zeros((max(len(rev), n), 2))
    y[:n] += _peak_soft(_bus_comp(dry, over_db=6.0, ratio=4.0, smooth_hz=40.0), 13.0)
    y[: len(rev)] += rev
    y = _hp(y, 120.0, 4)
    k0 = _n(preroll)
    y = y[k0: k0 + _n(dur)]
    y = _finish(y, 0.01, 0.05, keep=len(y))
    return Render(y, sync_offset=0, meta={"density": dens, "distance": distance})


# ====================================================================== geese

_HONK_NOTES = [311.13, 349.23, 415.30]  # Eb4, F4, Ab4 (key-safe, inside 300-450 Hz)


def _wingbeat(rng, gain_db_feather=-5.0):
    """One downstroke: 'whuff' (BP 150-800 Hz, 20 ms attack, 80 ms decay) + feather rustle (2-6 kHz)."""
    m = _n(0.22)
    w = _rbp(rng.standard_normal(m), rng.uniform(250.0, 480.0), rng.uniform(0.8, 1.2))
    w = _bp(w, 150.0, 800.0, 2)
    w *= _env_ar(m, rng.uniform(0.016, 0.024), rng.uniform(0.026, 0.036))  # 20 ms up, ~80 ms down
    w = _unit(_fade(w, 0.0, 0.08))
    fm = _n(0.16)
    fe = _env_ar(fm, rng.uniform(0.008, 0.014), rng.uniform(0.018, 0.03))
    f = rng.standard_normal(fm) * _shot_env(fm, rng, rng.uniform(8000.0, 14000.0), rng.uniform(150.0, 260.0), 0.5)
    f = _bp(f, 2000.0, 6000.0, 2) * fe
    _add(w, _unit(_fade(f, 0.0, 0.06)), rng.uniform(0.008, 0.02), _db(gain_db_feather + rng.uniform(-2.0, 2.0)))
    # upstroke: lighter feather rustle
    return w


def _honk(rng, f_peak):
    L = rng.uniform(0.15, 0.25)
    n = _n(L)
    x = np.linspace(0, 1, n)
    pk = rng.uniform(0.32, 0.48)
    rise = rng.uniform(0.85, 0.92)
    fall = rng.uniform(0.86, 0.94)
    contour = np.where(x < pk, rise + (1 - rise) * np.sin(0.5 * np.pi * np.minimum(x / pk, 1.0)),
                       1.0 - (1.0 - fall) * (np.maximum(x - pk, 0.0) / (1 - pk)) ** 1.5)
    f = f_peak * contour * (1.0 + _lfn(n, rng, 20.0, 0.003))
    src = dsp.pulse(f, n, width=rng.uniform(0.25, 0.4) + 0.04 * _lfn(n, rng, 8.0, 1.0))
    src += 0.12 * _bp(rng.standard_normal(n), 1000.0, 3000.0, 2)
    y = 0.9 * _rbp(src, rng.uniform(950.0, 1100.0), 3.0) + 0.6 * _rbp(src, rng.uniform(2300.0, 2700.0), 4.0) + \
        0.35 * _lp(src, 700.0, 2)
    y = np.tanh(1.6 * y / _pk(y)) / np.tanh(1.6)
    env = _env_asym(n, rng.uniform(0.15, 0.3), 1.0, 0.9)
    return _fade(y * env, 0.01, 0.03)


@recipe("cre.geese_flyover", family=FAM, sync="start", kind="event")
def geese_flyover(dur, rng, *, birds=6, honks=2, through_glass=0.5, direction=1, space="valley_mountain",
                  distance_m=20.0, **_):
    """Flock of geese flying over (seen through a panoramic sunroof). Wingbeats per bird with own
    rate/phase; 0-3 far reverberant honks; through_glass blends a glass-muffled version.
    distance_m (default 20 = the original 12-35 m flock): each bird is drawn at distance_m*[0.6, 1.75].
    Wings: 12/d gain, air-absorption LP clip(16000*12/d, 1500, 15000) Hz, and beyond 30 m an extra (30/d)^3
    (the faint wing whuff sinks under the air/ambience floor); feather layers scale by clip(30/d).
    Honks fall only 6 dB per doubling re 20 m with a mild extra LP, so beyond ~60 m the flock is honk-led
    (a tiny flock 100+ m up: honks carry, wings are barely there)."""
    dist = float(np.clip(distance_m, 3.0, 400.0))
    D = max(0.6, float(dur))
    nb = int(np.clip(birds, 1, 12))
    n = _n(D + 0.3)
    wings = np.zeros((n, 2))
    order = rng.permutation(nb)
    for b in range(nb):
        rank = order[b] / max(1, nb - 1)
        tc = D * (0.32 + 0.36 * rank) + rng.uniform(-0.05, 0.05)   # V: leader first
        w = D * rng.uniform(0.16, 0.24)
        d_m = dist * rng.uniform(0.6, 1.75)
        gb = 12.0 / d_m * min(1.0, 30.0 / d_m) ** 3
        gf = float(np.clip(30.0 / d_m, 0.0, 1.0))           # feather (2-6 kHz) layers fade with distance
        rate = rng.uniform(3.0, 4.0)
        ph0 = rng.uniform(0.0, 1.0)
        p0 = float(np.clip((rank - 0.5) * 1.5 + rng.uniform(-0.15, 0.15), -0.85, 0.85))
        drift = float(direction) * rng.uniform(0.1, 0.3)
        mono = np.zeros(n)
        t = (ph0 - 1.0) / rate
        r = rate
        while t < D + 0.1:
            r = float(np.clip(r * (1.0 + rng.normal(0.0, 0.02)), rate * 0.94, rate * 1.06))
            t += (1.0 / r) * (1.0 + rng.normal(0.0, 0.025))
            if t < -0.05:
                continue
            g = 1.0 / (1.0 + ((t - tc) / w) ** 2)   # inverse-square-like flyover arc
            if g < 0.04:
                continue
            _add(mono, _wingbeat(rng, -5.0 + 20.0 * np.log10(max(gf, 1e-3))), max(t, 0.0),
                 g * gb * _db(rng.uniform(-2.0, 1.0)))
            if rng.random() < 0.7:  # upstroke feathers
                fm = _n(0.08)
                fe = _env_asym(fm, 0.4, 1.0, 1.3)
                uf = rng.standard_normal(fm) * _shot_env(fm, rng, 10000.0, rng.uniform(150.0, 250.0), 0.5)
                uf = _bp(uf, 2500.0, 6000.0, 2) * fe
                _add(mono, _unit(uf), max(t, 0.0) + 0.5 / r, g * gb * gf * _db(rng.uniform(-18.0, -13.0)))
        # air absorption by distance
        mono = _lp(mono, float(np.clip(16000.0 * 12.0 / d_m, 1500.0, 15000.0)), 2)
        pc = p0 + drift * (np.linspace(0, 1, n) - 0.5)
        wings += dsp.pan(mono, pc)
    wings = _hp(wings, 120.0, 4)
    # space for wings: open sky, short
    wings = _space(wings, "open_exterior", -14.0)
    # --- honks: far, reverberant
    nh = int(np.clip(honks, 0, 3))
    hon = np.zeros((n, 2))
    g_h = min(1.0, 20.0 / dist)                                # 6 dB per doubling re 20 m (inverse distance)
    lp_h = float(np.clip(np.sqrt(60.0 / dist), 0.6, 1.0))      # extra air absorption on the honk top
    if nh:
        ts = np.sort(rng.uniform(0.12, 0.85, nh)) * D
        for t in ts:
            f = float(rng.choice(_HONK_NOTES))
            h = _honk(rng, f)
            h = _lp(_hp(h, 200.0, 2), rng.uniform(3000.0, 4200.0) * lp_h, 2)
            pp = rng.uniform(-0.6, 0.6)
            _add(hon, dsp.pan(_unit(h), pp), t, g_h * _db(rng.uniform(-16.0, -11.0)))
            if rng.random() < 0.35:  # answering honk from another bird, a bit lower
                h2 = _lp(_hp(_honk(rng, f * rng.choice([0.89, 0.84])), 200.0, 2), 3500.0 * lp_h, 2)
                _add(hon, dsp.pan(_unit(h2), -pp * 0.7), t + rng.uniform(0.2, 0.32),
                     g_h * _db(rng.uniform(-20.0, -15.0)))
        hon = dsp.reverb(hon, space, -2.0, dry=0.6, hp_send=200.0) if space and space != "none" else hon
    L = max(len(wings), len(hon))
    y = dsp.pad_to(wings, L) + dsp.pad_to(hon, L)
    a = float(np.clip(through_glass, 0.0, 1.0))
    if a > 0:
        g = dsp.through_glass(y)
        g = _space(g, "cabin_small", -14.0)
        g = dsp.pad_to(g, L)
        g *= _rms(y) / _rms(g)
        y = (1.0 - a) * y + a * g * _db(-1.5)
    y = _hp(y, 120.0, 4)
    return Render(_finish(y, 0.01, 0.06), sync_offset=0, meta={"birds": nb, "honks": nh, "distance_m": dist})


# ====================================================================== small birds

_CHIRP_KINDS = ["cheep", "down", "up", "trill", "chevron"]


def _chirp(rng, pitch=1.0, kind=None, L=None):
    """Sparrow chirp: FM sweep 4-7 kHz with syrinx flutter, 2nd harmonic, occasional second voice
    (birds have two independent sound sources), breath noise and amplitude jitter."""
    L = L or rng.uniform(0.03, 0.12)
    n = _n(L)
    x = np.linspace(0, 1, n)
    kind = kind or rng.choice(_CHIRP_KINDS)
    if kind == "cheep":
        f_lo, f_hi = rng.uniform(3900.0, 4700.0), rng.uniform(5800.0, 7000.0)
        f = f_lo + (f_hi - f_lo) * np.sin(np.pi * x ** rng.uniform(0.6, 1.0)) ** rng.uniform(0.6, 1.2)
        f -= (f_hi - f_lo) * 0.2 * x
    elif kind == "down":
        f = np.geomspace(rng.uniform(6200.0, 7200.0), rng.uniform(4000.0, 4800.0), n)
    elif kind == "up":
        f = np.geomspace(rng.uniform(4000.0, 4800.0), rng.uniform(5800.0, 7000.0), n)
    elif kind == "chevron":  # fast up-down-up
        f = rng.uniform(4400.0, 5200.0) + rng.uniform(900.0, 1600.0) * np.abs(np.sin(np.pi * 1.5 * x))
    else:
        f = rng.uniform(4500.0, 5600.0) + rng.uniform(300.0, 700.0) * np.sin(
            TWO_PI * np.cumsum(np.full(n, rng.uniform(25.0, 45.0))) / SR)
    flutter = 1.0 + rng.uniform(0.004, 0.012) * np.sin(TWO_PI * np.cumsum(
        rng.uniform(90.0, 180.0) * (1.0 + _lfn(n, rng, 40.0, 0.2))) / SR)
    f = np.clip(f * pitch * flutter * (1.0 + _lfn(n, rng, 30.0, 0.004)), 3500.0, 7800.0)
    ph = TWO_PI * np.cumsum(f) / SR + rng.uniform(0, TWO_PI)
    h2 = rng.uniform(0.08, 0.25) * (1.0 + 0.5 * _lfn(n, rng, 25.0, 1.0))
    y = np.sin(ph) + h2 * np.sin(2.0 * ph + rng.uniform(0, TWO_PI))
    if rng.random() < 0.3:  # second syrinx voice, weak, its own glide
        f2 = f * rng.uniform(1.12, 1.35) * (1.0 + _lfn(n, rng, 30.0, 0.01))
        y += rng.uniform(0.1, 0.25) * np.sin(TWO_PI * np.cumsum(np.clip(f2, 3500, 9500)) / SR)
    if rng.random() < 0.3:  # buzzy roughness (irregular)
        y *= _flutter(n, rng, 60.0, 120.0, 0.3)
    br = _hp(_rbp(rng.standard_normal(n), float(np.median(f)), 3.0), 2500.0, 4)  # tame the BPF skirts
    y += rng.uniform(0.04, 0.1) * br / _rms(br)
    a = rng.uniform(0.6, 1.6)
    env = np.sin(np.pi * x ** a) ** rng.uniform(1.0, 1.6) * _db(_lfn(n, rng, 60.0, 1.5))
    return _fade(y * env, 0.003, 0.004)


@recipe("cre.small_birds", family=FAM, sync="start", kind="event")
def small_birds(dur, rng, *, count=3, distance="mid", space="city_day_street", **_):
    """City sparrows: short phrases of FM chirps (4-7 kHz). count = number of phrases."""
    D = max(0.4, float(dur))
    k = int(np.clip(count, 1, 12))
    n = _n(D + 0.6)
    y = np.zeros((n, 2))
    nbirds = int(min(k, rng.integers(2, 4))) if k > 1 else 1
    pans = np.linspace(-0.7, 0.7, nbirds) + rng.uniform(-0.15, 0.15, nbirds) if nbirds > 1 else \
        np.array([rng.uniform(-0.6, 0.6)])
    rng.shuffle(pans)
    birds = []
    for b in range(nbirds):
        d = float(rng.uniform(0.2, 1.0) if distance != "far" else rng.uniform(0.6, 1.0))
        birds.append((float(np.clip(pans[b], -0.9, 0.9)), d, float(rng.uniform(0.93, 1.07)),
                      str(rng.choice(_CHIRP_KINDS))))
    starts = np.sort(rng.uniform(0.0, max(0.05, D - 0.4), k))
    starts[0] = min(starts[0], 0.05)
    for s_ in starts:
        p, d, pitch, kind0 = birds[int(rng.integers(0, nbirds))]
        m = _n(1.2)
        ph = np.zeros(m)
        t = 0.0
        L0 = rng.uniform(0.04, 0.1)
        kind = kind0 if rng.random() < 0.7 else None   # a phrase mostly repeats the bird's own call
        for _ in range(int(rng.integers(2, 7))):
            c = _chirp(rng, pitch * rng.uniform(0.98, 1.02), kind, L0 * rng.uniform(0.8, 1.2))
            _add(ph, c, t, _db(rng.uniform(-4.0, 0.0)))
            t += len(c) / SR + rng.uniform(0.04, 0.15)
            if t > 1.0:
                break
        ph = _lp(ph, 14000.0 * (1.0 - d) + 5500.0 * d, 2) * _db(-10.0 * d)
        _add(y, dsp.pan(ph, p), s_)
    y = _hp(y, 120.0, 4)
    y = _space(y, space, -11.0 if distance != "far" else -6.0, hp_send=300.0)
    return Render(_finish(y, 0.005, 0.05), sync_offset=0, meta={"phrases": k})


# ====================================================================== auditions

# (recipe, dur, params, at, gain, tag, seed)
AUDITIONS = [
    ("cre.panda_steps", 1.7, {"steps": 6, "gait_s": 0.3, "surface": "dry_asphalt", "distance": "mid"}, 46.9, -6.0,
     "steps_dry_stinger", 0),
    ("cre.panda_steps", 1.7, {"steps": 6, "gait_s": 0.3, "surface": "dry_asphalt", "distance": "mid"}, None, None,
     "steps_dry_seed1", 1),
    ("cre.panda_steps", 0.9, {"steps": 3, "gait_s": 0.28, "surface": "wet_asphalt", "distance": "mid"}, 6.63, -10.0,
     "steps_wet_headlights", 0),
    ("cre.panda_steps", 0.9, {"steps": 3, "gait_s": 0.28, "surface": "wet_asphalt", "body_db": -6.0}, 6.63, -6.0,
     "steps_wet_headlights_thin", 0),
    ("cre.panda_steps", 1.6, {"step_times": [0.0, 0.27, 0.61, 0.86, 1.2], "surface": "wet_asphalt",
                              "distance": "close"}, None, None, "steps_wet_close_times", 2),
    ("cre.panda_breath", 0.6, {"type": "exhale", "close": True}, 10.4, -8.0, "breath_exhale_close", 0),
    ("cre.panda_breath", 0.6, {"type": "exhale", "close": True}, None, None, "breath_exhale_seed1", 1),
    ("cre.panda_breath", 0.8, {"type": "sniff", "close": True}, None, None, "breath_sniff", 0),
    ("cre.panda_breath", 0.5, {"type": "huff", "close": True}, None, None, "breath_huff", 0),
    ("cre.panda_breath", 0.6, {"type": "huff", "close": False}, None, None, "breath_huff_far", 3),
    ("cre.paw_on_glass", 1.2, {"press_ms": 220, "squeak": 0.4, "sniff": True, "inside": True}, 7.6, -10.0,
     "paw_glass_inside", 0),
    ("cre.paw_on_glass", 1.2, {"press_ms": 220, "squeak": 0.4, "sniff": True, "inside": True, "body_db": -4.0},
     7.6, -4.0, "paw_glass_hero", 0),
    ("cre.paw_on_glass", 1.2, {"press_ms": 300, "squeak": 0.7, "sniff": True, "inside": True}, None, None,
     "paw_glass_seed1", 1),
    ("cre.panda_crowd", 2.6, {"density": 0.5, "distance": "mid"}, 8.13, -16.0, "crowd_mid", 0),
    ("cre.panda_crowd", 6.0, {"density": 0.5, "distance": "far"}, None, None, "crowd_far_long", 1),
    ("cre.fur_rustle", 0.5, {"intensity": 0.5}, 10.6, -12.0, "fur_rustle", 0),
    ("cre.fur_rustle", 0.35, {"intensity": 0.9}, None, None, "fur_rustle_strong", 1),
    ("cre.geese_flyover", 1.6, {"birds": 6, "honks": 2, "through_glass": 0.5}, 36.88, -10.0, "geese_sunroof", 0),
    ("cre.geese_flyover", 1.6, {"birds": 7, "honks": 1, "through_glass": 0.0}, None, None, "geese_open_seed1", 1),
    ("cre.small_birds", 2.4, {"count": 3}, 46.9, -14.0, "sparrows_stinger", 0),
]


def _run_auditions(only=None):
    from ..audition import audition
    for name, dur, params, at, gain, tag, seed in AUDITIONS:
        if only and not any(o in tag or o == name for o in only):
            continue
        met = audition(name, dur, params, seed=seed, at=at, gain=gain, tag=tag)
        ctx = met.get("context", {}).get("sfx_vs_bed_db_by_band", {})
        print(f"{tag:26s} peak {met['peak_dbfs']:6.1f} rms {met['rms_dbfs']:6.1f} corr {met.get('lr_corr')} "
              f"cent {met['centroid_hz']:6.0f} clicks {met['click_candidates']:2d} {met['click_times_s'][:6]} "
              f"ac {met.get('max_autocorr_0.1-5s')} dc {met['dc_db']} rise {met['sync_rise_db']}"
              + (f"\n{'':26s} ctx {ctx}" if ctx else ""), flush=True)


if __name__ == "__main__":
    # python -m sfx.recipes.creature [filter ...]  -> regenerates out/audition/creature/
    # Run as a script this module is loaded as __main__: drop its registrations and use the package module
    # (audition() imports sfx.recipes.*, which would otherwise register the recipes twice).
    import importlib
    import sys

    from ..core import RECIPES

    for _k in [k for k, v in RECIPES.items() if v["fn"].__module__ == "__main__"]:
        del RECIPES[_k]
    importlib.import_module("sfx.recipes.creature")._run_auditions(sys.argv[1:] or None)
