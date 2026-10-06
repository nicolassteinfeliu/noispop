"""Familia FOLEY: contactos precisos, amortiguados, "caros" (Geely EX2 / EX5). Sin samples.

Todo se sintetiza por capas (transiente + cuerpo + textura + espacio), con modelos de base física:

  * Contactos sólidos (clics, detents, pestillos, contactores): fuerza de contacto de Hertz aproximada por un
    pulso coseno-cuadrado (su ancho fija el brillo: 0.05-0.15 ms = duro/metálico, 2-5 ms = yema de dedo) que
    excita un banco modal (senos amortiguados, fase física sin(wt) -> sin escalón) + una ráfaga de ruido de
    contacto. Cada evento se re-sintetiza desde el rng (frecuencias +-2-5 %, tau +-15-20 %, nivel +-1.5 dB).
  * Agua: gotas = impacto (tick modal de chapa pintada 2-5 kHz tau 1.5-5 ms, re-sorteado en cada gota |
    vidrio 3-8 kHz tau 4-12 ms | "splat" de ruido LP 3-8 kHz), HP 400 Hz, + burbuja de Minnaert opcional
    (f0 = 3.26 kHz*mm / r, r 0.8-2.5 mm, subida 10-20 %, tau 4-12 ms) + satélites de salpicadura; las gotas
    salen de 1-4 puntos de goteo cuasi-periódicos (cada punto con su timbre y su pan) + gotas Poisson + un
    hilo de escurrimiento (micro-burbujas densas, muy bajas).
  * Motores de portón: polyBLEP 90-140 Hz con arranque suave (rampa de pitch), variación de carga 1/f,
    parciales de engrane 600-1200 Hz con AM aleatoria (no periódica), ruido de escobillas modulado por la
    conmutación, resonancias de panel; amortiguador a gas = siseo HP 1.5-5 kHz que sigue la velocidad.
  * Fricción (manos en cuero): ruido BP 1-6 kHz cuyo centroide y nivel siguen la velocidad de la mano,
    rugosidad granular + tren stick-slip (dsp.stick_slip) cuya tasa sigue la velocidad; agarre = thump de
    palma + crujido de cuero suave (sin chirrido).
  * LED: tren de impulsos de Poisson inhomogéneo (densidad en rampa) con amplitudes de cola pesada,
    HP 6-12 kHz variable + siseo finísimo, estéreo parcialmente correlacionado.
  * Espacio: dsp.reverb con el preset que corresponde (cabin_small, studio_stage, open_exterior,
    valley_mountain, city_fog_street, city_day_street); distancia = nivel + LPF de absorción del aire +
    relación directo/reverb.

Higiene: HP 120 Hz (24 dB/oct) por defecto; 70 Hz en recetas con cuerpo intencional (portón, suspensión,
contactor). Bordes con fade >= 3 ms, transientes con pre-roll de silencio (el sync cae en el primer sample
del contacto). Elementos tonales (zumbido de lámpara) afinados a nota segura (Ab2 = 103.83 Hz por defecto,
armónicos 5 y 7 atenuados por quedar fuera de la colección Bb Db Eb F Ab).

Audición de todo el módulo:  python -m sfx.recipes.foley [tag ...]
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .. import dsp
from ..core import SR, Render, recipe

TWO_PI = 2.0 * np.pi
AB2 = 103.826  # zumbido de red (100 Hz) re-afinado a nota segura
_SAFE_PCS = (10, 1, 3, 5, 8)   # Bb Db Eb F Ab


def _snap(f: float, pcs=_SAFE_PCS) -> float:
    """Frecuencia -> nota segura más cercana (Bb Db Eb F Ab)."""
    m = 69 + 12 * np.log2(max(f, 1e-3) / 440.0)
    cands = [k for k in range(int(np.floor(m)) - 6, int(np.ceil(m)) + 7) if k % 12 in pcs]
    k = min(cands, key=lambda c: abs(c - m))
    return 440.0 * 2 ** ((k - 69) / 12)


# =====================================================================================================
# utilidades privadas
# =====================================================================================================

def _n(sec: float) -> int:
    return max(1, int(round(sec * SR)))


def _ss(x, a, b):
    """Smoothstep 0->1 entre a y b."""
    u = np.clip((np.asarray(x, np.float64) - a) / (b - a + 1e-12), 0.0, 1.0)
    return u * u * (3 - 2 * u)


def _db(x):
    return 10.0 ** (np.asarray(x, np.float64) / 20.0)


def _pulse(width_s: float) -> np.ndarray:
    """Fuerza de contacto (coseno cuadrado, área 1). Ancho chico = contacto duro y brillante."""
    k = max(3, int(round(width_s * SR)) + 2)
    w = np.sin(np.linspace(0.0, np.pi, k)) ** 2
    return w / w.sum()


def _burst(n: int, rng, tau: float, lo: float | None = None, hi: float | None = None,
           attack: float = 0.0002, order: int = 2) -> np.ndarray:
    """Ráfaga de ruido de contacto con decaimiento exponencial (filtrada)."""
    t = np.arange(n) / SR
    e = np.exp(-t / max(tau, 1e-5))
    ka = max(2, int(attack * SR))
    e[:ka] *= np.linspace(0.0, 1.0, ka)
    x = rng.standard_normal(n) * e
    if lo and hi:
        x = dsp.bp(x, lo, hi, order)
    elif lo:
        x = dsp.hp(x, lo, order)
    elif hi:
        x = dsp.lp(x, hi, order)
    return x


def _modal_ir(n: int, freqs, taus, amps_db, rng=None, fj: float = 0.0, tj: float = 0.0,
              aj: float = 0.0) -> np.ndarray:
    """Respuesta al impulso de un banco modal (fase física sin(wt): arranca en 0, sin escalón)."""
    t = np.arange(n) / SR
    y = np.zeros(n)
    for f, tau, a in zip(freqs, taus, amps_db):
        if rng is not None:
            f = f * (1.0 + rng.uniform(-fj, fj))
            tau = tau * (1.0 + rng.uniform(-tj, tj))
            a = a + rng.uniform(-aj, aj)
        if f >= SR * 0.47:
            continue
        m = min(n, int(tau * 9 * SR) + 1)
        y[:m] += 10 ** (a / 20) * np.exp(-t[:m] / tau) * np.sin(TWO_PI * f * t[:m])
    return y


def _strike(exc: np.ndarray, freqs, taus, amps_db, rng=None, fj=0.0, tj=0.0, aj=0.0,
            n: int | None = None) -> np.ndarray:
    """Contacto excitando un banco modal (convolución excitador * IR modal)."""
    n = n or int(max(taus) * 8 * SR) + len(exc) + 16
    ir = _modal_ir(n, freqs, taus, amps_db, rng, fj, tj, aj)
    return signal.oaconvolve(ir, exc)[:n]


def _damped(n: int, f0: float, tau: float, glide: float = 0.0, glide_tau: float = 0.03) -> np.ndarray:
    """Seno amortiguado con glissando (glide < 0 = cae). Para cuerpos/thumps."""
    t = np.arange(n) / SR
    f = f0 * (1.0 + glide * (1.0 - np.exp(-t / glide_tau)))
    return np.exp(-t / tau) * np.sin(dsp.phase_from_freq(f, n))


def _air(x: np.ndarray, dist_m: float) -> np.ndarray:
    """Absorción del aire (aprox.) para una distancia: LPF suave."""
    fc = float(np.clip(22000.0 / (1.0 + dist_m / 6.0), 2500.0, 20000.0))
    return x if fc > 18500 else dsp.lp(x, fc, 2)


def _gain_wobble(n: int, rng, rate: float = 1.5, depth_db: float = 1.0) -> np.ndarray:
    return _db(dsp.random_walk(n, rng, rate, depth_db))


def _space(y: np.ndarray, preset: str | None, send_db: float, hp_send: float = 150.0) -> np.ndarray:
    if not preset or preset == "none" or send_db <= -80:
        return dsp.stereo(y)
    return dsp.reverb(y, preset, send_db, dry=1.0, hp_send=hp_send)


def _finish(y: np.ndarray, hp_hz: float = 120.0, fin: float = 0.003, fout: float = 0.02,
            trim_db: float = -96.0) -> np.ndarray:
    """HP (24 dB/oct), recorte de cola inaudible, fades, sin NaN, float32 estéreo."""
    y = dsp.stereo(np.nan_to_num(np.asarray(y, np.float64)))
    if hp_hz:
        y = dsp.hp(y, hp_hz, 4)
    # recorte de cola por debajo de trim_db re pico
    e = np.abs(y).max(axis=1)
    pk = e.max()
    if pk > 0:
        idx = np.nonzero(e > pk * 10 ** (trim_db / 20))[0]
        if len(idx):
            y = y[: min(len(y), idx[-1] + _n(0.03))]
    y = dsp.fade(y, fin, fout)
    return np.ascontiguousarray(y, dtype=np.float32)


def _spread_freqs(rng, lo: float, hi: float, k: int, jit: float = 0.08) -> np.ndarray:
    """k frecuencias repartidas log en [lo, hi] con jitter (evita modos amontonados)."""
    f = np.geomspace(lo, hi, k)
    return np.clip(f * (1 + rng.uniform(-jit, jit, k)), lo * 0.95, hi * 1.05)


# =====================================================================================================
# fol.phone_shutter
# =====================================================================================================

def _shutter_click(rng, lo, hi, width, tau_lo, tau_hi, nmodes=5):
    freqs = _spread_freqs(rng, lo, hi, nmodes)
    taus = rng.uniform(tau_lo, tau_hi, nmodes)
    amps = rng.uniform(-9.0, 0.0, nmodes)
    c = _strike(_pulse(width), freqs, taus, amps, rng, aj=1.0, n=_n(0.025))
    c /= np.abs(c).max() + 1e-12
    b = _strike(_pulse(width * 1.2), freqs * rng.uniform(0.97, 1.03), taus * 0.8, amps, rng, aj=2.0, n=len(c))
    dsp.mix_into(c, b / (np.abs(b).max() + 1e-12), _n(rng.uniform(0.9e-3, 1.8e-3)), _db(rng.uniform(-12, -8)))
    c += 0.35 * _burst(len(c), rng, rng.uniform(0.25e-3, 0.45e-3), lo=2500, hi=16000)
    # carcasa del teléfono (pequeña, apagada)
    c += 0.18 * _strike(_pulse(width * 2), [rng.uniform(1100, 1500)], [rng.uniform(3e-3, 5e-3)], [0.0],
                        n=len(c))
    return c


@recipe("fol.phone_shutter", family="foley", sync="transient", kind="event")
def phone_shutter(dur, rng, *, style="modern", gap_ms=None, space="open_exterior", send_db=-18.0, **_):
    """Obturador de celular moderno: clic 1 + swish de cortina (BP 1-4 kHz, ~30 ms) + clic 2 (70-90 ms).
    style: modern | soft (más bajo y redondo). sync = primer clic."""
    soft = str(style).lower() == "soft"
    pre = _n(0.008)
    gap = (float(gap_ms) if gap_ms else rng.uniform(70.0, 90.0)) * 1e-3
    n = pre + _n(gap + 0.12)
    y = np.zeros(n)
    if soft:
        lo, hi, width, t_lo, t_hi = 1500.0, 5200.0, 0.35e-3, 1.5e-3, 3.0e-3
        g2, sw_db, sw_len = _db(rng.uniform(-8, -6)), -5.0, 0.040
    else:
        lo, hi, width, t_lo, t_hi = 2000.0, 8000.0, 0.09e-3, 1.0e-3, 2.6e-3
        g2, sw_db, sw_len = _db(rng.uniform(-4, -2)), -10.0, 0.030
    c1 = _shutter_click(rng, lo, hi, width, t_lo, t_hi)
    c2 = _shutter_click(rng, lo * 0.85, hi * 0.9, width * 1.3, t_lo, t_hi)
    dsp.mix_into(y, c1, pre, 1.0)
    dsp.mix_into(y, c2, pre + _n(gap), g2)
    # swish de cortina entre los clics: BP con centro que barre 1.4 -> 3.4 kHz
    ns = _n(sw_len)
    sw_start = pre + _n(rng.uniform(0.006, 0.012))
    env = dsp.swell(ns, peak_pos=rng.uniform(0.3, 0.45), attack_pow=1.5, release_pow=1.6)
    fc = np.geomspace(rng.uniform(1300, 1600), rng.uniform(3000, 3800), ns)
    sw = dsp.tv_filter(rng.standard_normal(ns), fc, "bandpass", q=1.1, block=32)
    sw = dsp.bp(sw, 1000, 4200, 2) * env
    sw /= np.abs(sw).max() + 1e-12
    dsp.mix_into(y, sw, sw_start, _db(sw_db) * np.abs(c1).max())
    # parlante del teléfono: banda limitada + presencia
    y = dsp.hp(y, 420, 2)
    y = dsp.lp(y, 7500 if soft else 16000, 2)
    y = dsp.eq(y, "peak", 2800 if not soft else 2200, 1.0, 3.0)
    y = dsp.fade(y, 0.003, 0.004)
    y = _space(y, space, send_db)
    return Render(_finish(y), sync_offset=pre, meta={"gap_s": round(gap, 4), "style": style})


# =====================================================================================================
# fol.tailgate_close
# =====================================================================================================

def _rmsn(x):
    return x / (np.std(x) + 1e-12)


def _gear_motor(n: int, rng, f0: float, *, soft_start: float = 0.12, fade_in: float = 0.04,
                stop_at: float | None = None, stop_len: float = 0.08, stop_drop: float = 0.18,
                load_rise: float = 0.0, mesh_lo: float = 600.0, mesh_hi: float = 1200.0,
                whine: float = 1.0, orders=None) -> np.ndarray:
    """Motorreductor DC (portón): buzz de conmutación polyBLEP (con aspereza por ciclo) + engranes con AM
    aleatoria + fricción del husillo + escobillas, a través de las resonancias del panel.
    orders=(m1, m2): órdenes de engrane fijos (afinados); si None, m1 cae al azar en [mesh_lo, mesh_hi]."""
    t = np.arange(n) / SR
    T = n / SR
    stop_at = T if stop_at is None else stop_at
    prog = np.clip(t / max(stop_at, 1e-3), 0, 1)
    ramp = _ss(t, 0.0, soft_start)
    f = f0 * (0.55 + 0.45 * ramp)
    f *= 1.0 + 0.016 * dsp.random_walk(n, rng, 0.9) + 0.005 * dsp.random_walk(n, rng, 6.0)  # carga 1/f
    f *= 1.0 - load_rise * prog ** 2                                     # carga creciente (sello)
    f *= 1.0 - stop_drop * _ss(t, stop_at - stop_len, stop_at)          # frenado suave
    ph = dsp.phase_from_freq(f, n, rng.uniform(0, TWO_PI))
    # conmutación: saw polyBLEP con aspereza (variación ciclo a ciclo) -> carcasa/panel
    rough = _rmsn(dsp.lp(rng.standard_normal(n), 350, 2))
    buzz = dsp.saw(f, n, rng.uniform(0, TWO_PI)) * (1.0 + 0.3 * rough)
    buzz = dsp.lp(dsp.hp(buzz, 170, 2), 2600, 2)
    buzz = dsp.eq(buzz, "peak", rng.uniform(260, 320), 2.0, 4.0)
    buzz = dsp.eq(buzz, "peak", rng.uniform(820, 980), 2.5, 3.0)
    # engranes: dos órdenes con AM aleatoria (no periódica)
    f_mean = float(np.median(f))
    if orders is not None:
        m1, m2 = float(orders[0]), float(orders[1])
    else:
        m1 = rng.uniform(mesh_lo, mesh_lo + 0.55 * (mesh_hi - mesh_lo)) / f_mean
        m2 = m1 * rng.uniform(1.45, 1.6)
    am1 = np.clip(1.0 + 0.45 * dsp.random_walk(n, rng, 14.0) + 0.2 * dsp.random_walk(n, rng, 3.0), 0.1, None)
    am2 = np.clip(1.0 + 0.5 * dsp.random_walk(n, rng, 19.0), 0.1, None)
    mesh = (np.sin(ph * m1 + rng.uniform(0, TWO_PI)) * am1 * 0.55 +
            np.sin(ph * m2 + rng.uniform(0, TWO_PI)) * am2 * 0.28 +
            np.sin(ph * m1 * 2 + rng.uniform(0, TWO_PI)) * 0.10)
    # fricción del husillo / engranes (llena entre armónicos: nada de "synth" limpio)
    fric = dsp.bp(rng.standard_normal(n), 450, 3200, 2) * np.clip(1.0 + 0.4 * dsp.random_walk(n, rng, 5.0), 0.2, None)
    # escobillas: ruido HF levemente modulado por la conmutación (f deriva -> no periódico)
    brush = dsp.bp(rng.standard_normal(n), 2600, 9000, 2) * (0.82 + 0.18 * (0.5 + 0.5 * np.cos(ph)) ** 2)
    y = (_rmsn(buzz) + 0.8 * whine * _rmsn(mesh) + 0.45 * _rmsn(fric) + 0.22 * _rmsn(brush))
    # envolvente: entrada suave, ganancia 1/f +-1.2 dB, corte al detenerse
    env = _ss(t, 0.0, fade_in) * _gain_wobble(n, rng, 2.0, 1.2)
    env *= 1.0 - _ss(t, stop_at - stop_len * 0.6, stop_at)
    return dsp.hp(y * env, 120, 4)          # el motor no baja de 120 Hz (sólo el thud del pestillo llega a 70)


@recipe("fol.tailgate_close", family="foley", sync="transient", kind="event")
def tailgate_close(dur, rng, *, motor_s=1.0, latch=True, cinch_s=0.3, distance_m=4.0,
                   space="valley_mountain", send_db=-18.0, motor_db=-6.0, tune=True, **_):
    """Portón eléctrico bajando y cerrando: motorreductor (motor_s) + amortiguador a gas + contacto con el
    burlete + cinch (~0.3 s, más agudo) + pestillo (clunk modal + thud de carrocería + squash del sello).
    Exterior, distancia media. sync = transiente del pestillo (latch=False: sync = detención del motor)."""
    pre = _n(0.01)
    motor_s = max(0.35, float(motor_s))
    cinch = min(float(cinch_s), 0.4 * motor_s) if latch else 0.0
    lower_s = motor_s - cinch
    post = max(0.35, float(dur) - motor_s)
    n = pre + _n(motor_s + post)
    t_latch = pre + _n(motor_s)
    t_touch = pre + _n(lower_s)
    y = np.zeros(n)
    f0 = rng.uniform(95.0, 135.0)
    orders = None
    if tune:   # régimen estable en nota segura (Ab2 / Bb2 / Db3) y engranes en órdenes 6/8 u 8/12 (también seguras)
        f0 = _snap(f0, (8, 10, 1))
        orders = (6.0, 8.0) if rng.random() < 0.5 else (8.0, 12.0)

    # 1) bajada: motorreductor con arranque suave y frenado al tocar el burlete
    nl = _n(lower_s + 0.01)
    mot = _gear_motor(nl, rng, f0, soft_start=0.13, fade_in=0.05, stop_at=lower_s, stop_len=0.12,
                      stop_drop=0.2, orders=orders)
    mot /= np.abs(mot).max() + 1e-12
    dsp.mix_into(y, mot, pre, _db(motor_db))

    # 2) amortiguador a gas: siseo HP que sigue la velocidad del portón (crece hacia el final)
    tl = np.arange(nl) / SR
    vel = _ss(tl, 0.0, 0.18) * (1.0 - _ss(tl, lower_s - 0.15, lower_s))
    hiss_env = vel * (0.45 + 0.55 * np.clip(tl / lower_s, 0, 1)) * _gain_wobble(nl, rng, 3.0, 1.5)
    fc = np.geomspace(2200, 3600, nl) * (1 + 0.08 * dsp.random_walk(nl, rng, 2.0))
    hiss = dsp.tv_filter(rng.standard_normal(nl), fc, "bandpass", q=0.8, block=128)
    hiss = dsp.lp(dsp.hp(hiss, 1500, 2), 5200, 4) * hiss_env
    hiss /= np.abs(hiss).max() + 1e-12
    dsp.mix_into(y, hiss, pre, _db(motor_db - 9.0))

    if latch:
        # 3) contacto con el burlete + primer enganche (pequeño tic metálico)
        nt = _n(0.12)
        touch = 0.8 * signal.oaconvolve(_damped(nt, rng.uniform(100, 125), 0.022), _pulse(0.006))[:nt]
        touch += 0.5 * _burst(nt, rng, 0.016, 300, 1200, attack=0.003)
        touch /= np.abs(touch).max() + 1e-12
        dsp.mix_into(y, touch, t_touch, _db(motor_db - 4.0))
        catch = _strike(_pulse(0.12e-3), [2600, 4100, 5900], [0.004, 0.003, 0.002], [0, -4, -9], rng,
                        fj=0.04, tj=0.2, aj=1.5)
        catch /= np.abs(catch).max() + 1e-12
        dsp.mix_into(y, catch, t_touch + _n(rng.uniform(0.008, 0.016)), _db(motor_db - 8.0))

        # 4) cinch: motor pequeño, más agudo, con carga creciente (comprime el sello) y corte en el latch
        c_len = max(0.05, cinch - 0.012)          # el cinch arranca 20 ms después del contacto y para ~8 ms tras el latch
        nc = _n(c_len) + _n(0.004)
        f_c = f0 * (1.5 if tune else rng.uniform(1.45, 1.65))   # quinta arriba si está afinado
        cm = _gear_motor(nc, rng, f_c, soft_start=0.03, fade_in=0.015,
                         stop_at=c_len, stop_len=0.012, stop_drop=0.05, load_rise=0.12,
                         mesh_lo=900, mesh_hi=1500, whine=1.4, orders=(6.0, 8.0) if tune else None)
        cm /= np.abs(cm).max() + 1e-12
        dsp.mix_into(y, cm, t_touch + _n(0.02), _db(motor_db - 2.0))
        # squash lento del burlete durante el cinch
        sq = _burst(nc, rng, cinch * 0.6, 250, 1100, attack=cinch * 0.5)
        sq /= np.abs(sq).max() + 1e-12
        dsp.mix_into(y, sq, t_touch, _db(motor_db - 14.0))

        # 5) pestillo: clunk modal + thud de carrocería + squash + segundo detent
        nk = _n(0.6)
        clunk = _strike(_pulse(rng.uniform(0.4e-3, 0.6e-3)), [180, 420, 950, 1900, 3300],
                        [0.11, 0.08, 0.055, 0.04, 0.03], [0, -3, -6, -10, -14], rng, fj=0.03, tj=0.15,
                        aj=1.5, n=nk)
        clunk /= np.abs(clunk).max() + 1e-12
        clunk += 0.30 * _burst(nk, rng, rng.uniform(0.8e-3, 1.4e-3), 2500, 9000)   # contacto metálico
        body = signal.oaconvolve(_damped(nk, rng.uniform(80, 95), rng.uniform(0.045, 0.06), glide=-0.08),
                                 _pulse(0.004))[:nk]
        body = body / (np.abs(body).max() + 1e-12) * 0.85
        squash = _burst(nk, rng, 0.025, 250, 1200, attack=0.003) * 0.20
        squash += dsp.lp(_burst(nk, rng, 0.03, attack=0.004), 900, 2) * 0.12       # aire comprimido
        k = clunk + body + squash
        det = _strike(_pulse(0.1e-3), [2300, 3500, 5200], [0.005, 0.004, 0.003], [0, -3, -8], rng,
                      fj=0.04, tj=0.2, aj=1.5)
        dsp.mix_into(k, det / (np.abs(det).max() + 1e-12), _n(rng.uniform(0.012, 0.018)), 0.22)
        dsp.mix_into(y, k, t_latch, 1.0)

        # 6) el cinch rebobina (detalle premium): giro corto y bajo
        nr = _n(0.14)
        rw = _gear_motor(nr, rng, f0 * (2.0 if tune else rng.uniform(1.7, 1.9)), soft_start=0.02, fade_in=0.02,
                         stop_at=0.13, stop_len=0.04, mesh_lo=1000, mesh_hi=1600,
                         orders=(6.0, 8.0) if tune else None)
        rw /= np.abs(rw).max() + 1e-12
        dsp.mix_into(y, rw, t_latch + _n(rng.uniform(0.07, 0.1)), _db(motor_db - 10.0))
        sync = t_latch
    else:
        # sin pestillo: el portón se detiene (tope amortiguado), sync = detención
        nt = _n(0.15)
        stop = signal.oaconvolve(_damped(nt, rng.uniform(95, 115), 0.03), _pulse(0.008))[:nt]
        stop /= np.abs(stop).max() + 1e-12
        dsp.mix_into(y, stop, t_touch, _db(motor_db + 2.0))
        sync = t_touch

    # distancia + espacio exterior (reflexión de suelo + valle)
    y = _air(y, float(distance_m))
    y = dsp.fade(y, 0.003, 0.02)
    y = dsp.reverb(y, "open_exterior", -12.0, hp_send=150)
    if space and space != "open_exterior":
        wet = dsp.convolve(dsp.hp(y, 150, 2), dsp.ir_preset(space), wet=_db(send_db))
        wet[: len(y)] += y
        y = wet
    return Render(_finish(y, hp_hz=70.0), sync_offset=sync,
                  meta={"latch_t": round(t_latch / SR, 4), "touch_t": round(t_touch / SR, 4),
                        "motor_hz": round(f0, 1)})


# =====================================================================================================
# fol.gear_selector
# =====================================================================================================

def _detent(rng, style: str, soft: float = 0.0):
    """Un clic de detent: bola/resorte que cae en la muesca -> modos HF + cuerpo plástico."""
    nk = _n(0.08)
    if style == "column":
        hf = ([1650, 2650, 3900], [0.012, 0.009, 0.006], [0, -3, -7])
        body = ([260, 430, 980], [0.010, 0.008, 0.005], [0, -2, -8])
        width = 0.18e-3
    else:  # rotary (cristal)
        hf = ([2300, 3700, 5100], [0.010, 0.007, 0.005], [0, -2, -5])
        body = ([330, 520, 1200], [0.007, 0.005, 0.004], [0, -2, -9])
        width = 0.11e-3
    width *= 1.0 + 0.8 * soft
    exc = _pulse(width * rng.uniform(0.9, 1.1))
    c = _strike(exc, *hf, rng, fj=0.03, tj=0.2, aj=1.5, n=nk)
    c /= np.abs(c).max() + 1e-12
    b = _strike(_pulse(width * 3), *body, rng, fj=0.05, tj=0.2, aj=1.5, n=nk)
    b /= np.abs(b).max() + 1e-12
    # modos débiles densos (un objeto real no tiene 3 modos): quitan lo "sintético"
    k = 6
    dz = _strike(exc, _spread_freqs(rng, 1500, 9500, k, 0.12), rng.uniform(1.5e-3, 4e-3, k),
                 rng.uniform(-12, -6, k), rng, n=nk)
    y = c + _db(-5.0 - 2 * soft) * b + 0.5 * dz / (np.abs(dz).max() + 1e-12)
    y += 0.28 * _burst(nk, rng, rng.uniform(0.2e-3, 0.35e-3), 3500, 16000)
    if style != "column":  # destello vítreo del selector de cristal (lee sobre el bed)
        g = _strike(exc, [rng.uniform(6500, 7200), rng.uniform(8600, 9400)], [0.005, 0.004], [0, -4], rng,
                    tj=0.2, n=nk)
        y += _db(-15.0 - 4 * soft) * g / (np.abs(g).max() + 1e-12)
    return y


@recipe("fol.gear_selector", family="foley", sync="transient", kind="event")
def gear_selector(dur, rng, *, style="rotary", second=True, second_ms=None, space="cabin_small",
                  send_db=-14.0, **_):
    """Selector de marcha premium: roce corto + detent (modos 2.3/3.7/5.1 kHz, tau 5-15 ms, cuerpo plástico
    300-600 Hz) + segundo clic más suave ~60 ms después. En cabina. sync = primer clic."""
    style = "column" if str(style).lower() in ("column", "stalk", "columna") else "rotary"
    slide = rng.uniform(0.025, 0.04) if style == "rotary" else rng.uniform(0.04, 0.06)
    pre = _n(0.006 + slide)
    gap = (float(second_ms) if second_ms else rng.uniform(55.0, 68.0) * (1.4 if style == "column" else 1.0)) * 1e-3
    n = pre + _n(max(float(dur), gap + 0.12))
    y = np.zeros(n)
    # roce del mando girando hacia la muesca (muy bajo, sube hacia el clic)
    ns = _n(slide)
    fr = rng.standard_normal(ns) * (1 + 0.6 * dsp.lp(rng.standard_normal(ns), 120, 2) * 4)
    fr = dsp.bp(fr, 2200, 7000, 2) * _ss(np.arange(ns), 0, ns) ** 1.5
    fr /= np.abs(fr).max() + 1e-12
    dsp.mix_into(y, fr, pre - ns, _db(-30.0))
    c1 = _detent(rng, style)
    dsp.mix_into(y, c1, pre, 1.0)
    if second:
        c2 = _detent(rng, style, soft=0.6)
        dsp.mix_into(y, c2, pre + _n(gap), _db(rng.uniform(-10.0, -8.0)))
    y = dsp.fade(y, 0.003, 0.01)
    y = _space(y, space, send_db)
    return Render(_finish(y), sync_offset=pre, meta={"second_s": round(gap, 4) if second else None})


# =====================================================================================================
# fol.ped_signal
# =====================================================================================================

def _ped_tick(rng, f1=1000.0, f2=2700.0, fj=0.015):
    nk = _n(0.12)
    exc = _pulse(rng.uniform(0.12e-3, 0.18e-3))
    tone = _strike(exc, [f1, f2], [0.015, 0.015], [0, -2], rng, fj=fj, tj=0.15, aj=1.0, n=nk)
    tone /= np.abs(tone).max() + 1e-12
    box = _strike(exc, [450, 1700, 4200], [0.006, 0.005, 0.004], [0, -2, -7], rng, fj=0.05, tj=0.2, aj=1.5,
                  n=nk)
    box /= np.abs(box).max() + 1e-12
    pole = _modal_ir(nk, [3350, 5150], [0.04, 0.03], [0, -3], rng, fj=0.02, tj=0.1)
    pole = signal.oaconvolve(pole, exc)[:nk]
    pole /= np.abs(pole).max() + 1e-12
    y = tone + _db(-8.0) * box + _db(-24.0) * pole
    y += 0.12 * _burst(nk, rng, 0.4e-3, 1500, 9000)
    return y


@recipe("fol.ped_signal", family="foley", sync="start", kind="event")
def ped_signal(dur, rng, *, count=2, rate_hz=1.0, distance_m=18.0, space="city_fog_street", send_db=-9.0,
               tune=True, **_):
    """Tic de semáforo peatonal (modos ~1 kHz + 2.7 kHz, tau 15 ms + caja plástica + poste; tune=True los afina a
    Bb5 932 Hz + F7 2794 Hz, notas seguras), count veces a
    rate_hz, a distancia en la calle. sync = primer contacto."""
    count = max(1, int(count))
    period = 1.0 / max(0.2, float(rate_hz))
    pre = _n(0.004)
    n = pre + _n((count - 1) * period + max(0.25, float(dur) - (count - 1) * period))
    y = np.zeros(n)
    for i in range(count):
        at = pre + _n(i * period + (rng.uniform(-0.8e-3, 0.8e-3) if i else 0.0))
        tk = _ped_tick(rng, 932.33, 2793.8, 0.003) if tune else _ped_tick(rng)   # Bb5 + F7 (duodécima)
        dsp.mix_into(y, tk, at, _db(rng.uniform(-1.0, 0.0)))
    y = dsp.bp(y, 280, 7000, 2)              # parlante/bocina del pulsador
    y = _air(y, float(distance_m))
    y = dsp.fade(y, 0.003, 0.01)
    y = _space(y, space, send_db)
    return Render(_finish(y), sync_offset=pre, meta={"period_s": round(period, 4)})


# =====================================================================================================
# fol.relay_click
# =====================================================================================================

@recipe("fol.relay_click", family="foley", sync="transient", kind="event")
def relay_click(dur, rng, *, space="open_exterior", send_db=-24.0, **_):
    """Relé / activación de faro: armadura que golpea (modos 2-4 kHz, muy cortos) + rebote de contactos +
    asentamiento. Muy sutil. sync = transiente."""
    pre = _n(0.005)
    n = pre + _n(max(0.08, float(dur)))
    y = np.zeros(n)

    def hit(g, w):
        nk = _n(0.03)
        f = _spread_freqs(rng, 2100, 3900, 3, 0.06)
        c = _strike(_pulse(w), f, rng.uniform(1.5e-3, 3e-3, 3), [0, -2, -4], rng, aj=1.5, n=nk)
        c /= np.abs(c).max() + 1e-12
        case = _strike(_pulse(w), [rng.uniform(6200, 7200)], [0.8e-3], [0], n=nk)   # carcasa del relé
        c += 0.35 * case / (np.abs(case).max() + 1e-12)
        c += 0.25 * _burst(nk, rng, 0.25e-3, 2500, 12000)
        return c * g

    dsp.mix_into(y, hit(1.0, 0.06e-3), pre)
    t = pre
    for g_db in (-10.0, -18.0):                                  # rebote de contactos
        t += _n(rng.uniform(0.6e-3, 1.1e-3))
        dsp.mix_into(y, hit(_db(g_db + rng.uniform(-2, 1)), 0.05e-3), t)
    dsp.mix_into(y, hit(_db(rng.uniform(-22, -19)), 0.1e-3), pre + _n(rng.uniform(0.007, 0.011)))  # asienta
    y = dsp.lp(dsp.hp(y, 900, 2), 10000, 2)   # dentro del faro/caja
    y = dsp.fade(y, 0.003, 0.01)
    y = _space(y, space, send_db)
    return Render(_finish(y), sync_offset=pre)


# =====================================================================================================
# fol.light_contactor
# =====================================================================================================

def _lamp_hum(n: int, rng, f0: float) -> np.ndarray:
    """Zumbido de balasto/lámpara: armónicos de f0 (5 y 7 atenuados, fuera de tonalidad) + buzz LPF 800."""
    f = f0 * (1.0 + 0.003 * dsp.random_walk(n, rng, 0.8))
    ph = dsp.phase_from_freq(f, n, rng.uniform(0, TWO_PI))
    amps = {1: 0, 2: -3, 3: -7, 4: -9, 5: -30, 6: -13, 7: -34, 8: -17}
    y = np.zeros(n)
    for h, a in amps.items():
        y += _db(a) * np.sin(h * ph + rng.uniform(0, TWO_PI)) * (1 + 0.15 * dsp.random_walk(n, rng, 1.5 + h * 0.3))
    # buzz magnético: ruido de banda modulado al doble de la red (seguido por la deriva de f)
    bz = dsp.bp(rng.standard_normal(n), 250, 780, 2) * (0.5 + 0.5 * np.cos(2 * ph)) ** 6
    y = y + 0.9 * bz / (np.std(bz) + 1e-12) * np.std(y) * 0.35
    y = dsp.lp(y, 800, 4)
    return y * _gain_wobble(n, rng, 1.2, 1.2)


@recipe("fol.light_contactor", family="foley", sync="transient", kind="event")
def light_contactor(dur, rng, *, hum=0.5, hum_hz=AB2, hum_s=1.5, arc=0.4, space="studio_stage",
                    send_db=-10.0, **_):
    """Contactor grande de luz de estudio: clack metálico (modos 300 Hz-3 kHz) con rebote de armadura + golpe
    de gabinete + chispa leve, y zumbido de lámpara (Ab2 ~ red 100 Hz, LPF 800 Hz) que decae en ~1.5 s.
    Escenario de estudio. sync = clack. arc 0..1: chispa + chisporroteo 2-8 kHz 5-60 ms después del clack,
    nivel -24 + 18*arc dB re el clack (0.4 ~ -17 dB, discreto; 0.8 ~ -10 dB, crepitar eléctrico legible)."""
    pre = _n(0.006)
    hum_s = max(0.2, float(hum_s))
    n = pre + _n(max(float(dur), hum_s) + 0.05)
    y = np.zeros(n)
    nk = _n(0.35)

    def clack(g, w):
        c = _strike(_pulse(w), [318, 590, 1040, 1530, 2210, 2870], [0.045, 0.038, 0.03, 0.022, 0.016, 0.012],
                    [-4, 0, -2, -5, -7, -10], rng, fj=0.04, tj=0.2, aj=1.5, n=nk)
        c /= np.abs(c).max() + 1e-12
        k = 7   # modos densos de chapa/armadura, cortos
        dz = _strike(_pulse(w), _spread_freqs(rng, 900, 6500, k, 0.12), rng.uniform(3e-3, 9e-3, k),
                     rng.uniform(-10, -3, k), rng, n=nk)
        c += 0.6 * dz / (np.abs(dz).max() + 1e-12)
        c += 0.7 * _burst(nk, rng, rng.uniform(1.4e-3, 2.4e-3), 1500, 12000)
        return c * g

    dsp.mix_into(y, clack(1.0, 0.22e-3), pre)
    t = pre
    for g_db, dt in ((-8.0, (2.5e-3, 4e-3)), (-17.0, (5e-3, 8e-3))):   # rebote de armadura ("ka-CHAK")
        t += _n(rng.uniform(*dt))
        dsp.mix_into(y, clack(_db(g_db + rng.uniform(-1.5, 1.0)), 0.18e-3), t)
    # gabinete (cuerpo, >= 70 Hz)
    th = signal.oaconvolve(0.7 * _damped(nk, rng.uniform(130, 160), 0.025) +
                           0.5 * _damped(nk, rng.uniform(82, 92), 0.035), _pulse(0.003))[:nk]
    dsp.mix_into(y, th / (np.abs(th).max() + 1e-12), pre, _db(-6.0))
    # chispa de contactos + chisporroteo eléctrico. arc 0..1 escala en dB (-24 + 18*arc re el clack): un
    # multiplicador lineal sobre -16 dB no cambiaba nada audible bajo el clack. La chispa inicial (HF, 1 ms
    # después del contacto) queda pegada al clack; el chisporroteo (crackle 2-8 kHz, tren de Poisson de
    # densidad decreciente) vive 5-60 ms después, fuera de la máscara temporal del clack, y es lo que lee.
    arc = float(np.clip(arc, 0.0, 1.0))
    if arc > 0:
        g_arc = _db(-24.0 + 18.0 * arc)
        na = _n(rng.uniform(0.008, 0.015))
        dens = rng.standard_normal(na) * (rng.random(na) < 0.12)
        sp = dsp.hp(dens, 3500, 2) * np.exp(-np.arange(na) / na * 3)
        dsp.mix_into(y, sp / (np.abs(sp).max() + 1e-12), pre + _n(0.001), g_arc * _db(-4.0))
        t0z, t1z = 0.005, 0.02 + 0.04 * arc                       # sizzle: 5 ms .. 25-60 ms tras el clack
        nz = _n(t1z - t0z + 0.01)
        tz = np.arange(nz) / SR
        rate = (1500.0 + 2500.0 * arc) * np.exp(-tz / (0.35 * (t1z - t0z)))   # chispas/s, decreciente
        hit = rng.random(nz) < rate / SR
        amp = np.where(hit, rng.lognormal(0.0, 0.7, nz) * rng.choice([-1.0, 1.0], nz), 0.0)
        cr = dsp.bp(signal.oaconvolve(amp, np.exp(-np.arange(_n(0.0006)) / (0.00015 * SR)))[:nz], 2000.0, 8000.0, 2)
        cr += 0.25 * np.std(cr) * dsp.bp(rng.standard_normal(nz), 2500.0, 7000.0, 2) * np.exp(-tz / 0.012)
        cr *= _ss(tz, 0.0, 0.002) * (1.0 - _ss(tz, t1z - t0z - 0.004, t1z - t0z + 0.008))
        dsp.mix_into(y, cr / (np.abs(cr).max() + 1e-12), pre + _n(t0z), g_arc)
    # zumbido de lámpara: enciende 15-30 ms después (inrush) y decae en hum_s
    if hum > 0:
        h0 = pre + _n(rng.uniform(0.015, 0.03))
        nh = n - h0
        th_ = np.arange(nh) / SR
        env = _ss(th_, 0, 0.04) * (1 + 0.5 * np.exp(-th_ / 0.12)) * (1 - _ss(th_, 0.0, hum_s)) ** 1.3
        hm = _lamp_hum(nh, rng, float(hum_hz)) * env
        hm = dsp.hp(hm, 80, 2)
        dsp.mix_into(y, hm / (np.abs(hm).max() + 1e-12), h0, _db(-26.0 + 16.0 * float(hum)))
    y = dsp.fade(y, 0.003, 0.02)
    y = _space(y, space, send_db)
    return Render(_finish(y, hp_hz=70.0), sync_offset=pre, meta={"hum_hz": round(float(hum_hz), 2)})


# =====================================================================================================
# fol.droplets
# =====================================================================================================

_MINNAERT = 3260.0          # Hz*mm: f0 = 3.26 kHz * mm / r
_PANEL_TAU_MAX = 0.040      # s: tope de decaimiento de un modo de chapa pintada con película de agua


def _drop(rng, surface: str, timbre: dict, close: float = 1.0):
    """Una gota: impacto (tick modal / splat) + burbuja de Minnaert opcional + satélites.

    El juego modal se re-sortea en CADA gota (2-3 modos a +-20 % de los del punto de goteo, amplitudes al
    azar: el modo más fuerte no es siempre el más grave) con decaimiento corto (chapa pintada mojada:
    1.5-5 ms, vidrio 4-12 ms, tope 40 ms), así ninguna altura se repite gota tras gota ni queda sonando en la
    reverb. El 'splat' es ruido corto LP 3-8 kHz; la burbuja es un chirp de Minnaert (r 0.8-2.5 mm, subida
    10-20 %, tau 4-12 ms con Q físico). Todo el impacto lleva HP 400 Hz (24 dB/oct): sin columna grave."""
    n = _n(0.09)
    y = np.zeros(n)
    kind = timbre["kind"] if rng.random() < 0.75 else rng.choice(["tick", "plink", "splat"])
    k = 2 if rng.random() < 0.5 else 3
    fs = np.asarray(timbre["f"][:k], np.float64) * (1.0 + rng.uniform(-0.2, 0.2, k))
    amps = -rng.uniform(2.0, 11.0, k)
    pw = np.array([0.5, 0.35, 0.15][:k])
    amps[int(rng.choice(k, p=pw / pw.sum()))] = 0.0                        # el más fuerte: casi siempre grave
    glass = surface == "glass"
    if kind == "tick" and glass:
        exc = _pulse(rng.uniform(0.05e-3, 0.1e-3))
        taus = np.minimum(rng.uniform(0.004, 0.012, k), _PANEL_TAU_MAX)
        imp = _strike(exc, fs, taus, amps, n=n)
        sp = _strike(exc, rng.uniform(8500, 12500, 2), rng.uniform(0.003, 0.006, 2), [-8, -12], rng, n=n)
    elif kind == "tick":
        exc = _pulse(rng.uniform(0.06e-3, 0.15e-3))
        taus = np.minimum(rng.uniform(0.0015, 0.005, k), _PANEL_TAU_MAX)
        imp = _strike(exc, fs, taus, amps, n=n)
        sp = _strike(exc, rng.uniform(6000, 9500, 2), rng.uniform(0.0015, 0.003, 2), [-9, -13], rng, n=n)
    else:
        imp = _strike(_pulse(0.15e-3), fs[:2], [0.002, 0.0015], [0, -4], rng, aj=2.0, n=n) * 0.4
        sp = np.zeros(n)
    pk = np.abs(imp).max() + 1e-12
    imp = (imp + sp) / pk                                                    # chispa HF del panel
    # golpe de agua sobre la película: ruido muy corto, LP 3-8 kHz
    pat = dsp.lp(_burst(n, rng, rng.uniform(0.5e-3, 1.8e-3)), rng.uniform(3000.0, 8000.0), 2)
    pat /= np.abs(pat).max() + 1e-12
    g_imp = {"tick": 1.0, "plink": 0.45, "splat": 0.3}[kind]
    y += g_imp * imp + (0.4 if kind != "splat" else 1.0) * pat
    # burbuja (cavidad atrapada en la película/charco): Minnaert, radio propio de cada gota
    if kind == "plink" or rng.random() < 0.3:
        r_mm = float(np.clip(timbre["r_mm"] * rng.lognormal(0.0, 0.2), 0.8, 2.5))
        f0 = _MINNAERT / r_mm
        tau = float(np.clip(rng.uniform(25.0, 60.0) / (np.pi * f0), 0.004, 0.012))
        nb = _n(min(0.08, 7.0 * tau + 0.004))
        b = dsp.bubble(f0, tau, nb, glide=rng.uniform(0.10, 0.20), rng=rng)
        b /= np.abs(b).max() + 1e-12
        dsp.mix_into(y, b, _n(rng.uniform(0.0008, 0.004)), 1.0 if kind == "plink" else 0.5)
    # satélites de salpicadura (micro-gotitas)
    if kind == "splat" or rng.random() < 0.4:
        for _k in range(rng.integers(1, 4)):
            nb = _n(0.02)
            s = dsp.bubble(rng.uniform(4500, 9000), rng.uniform(0.001, 0.003), nb, glide=0.3, rng=rng)
            dsp.mix_into(y, s / (np.abs(s).max() + 1e-12), _n(rng.uniform(0.008, 0.045)),
                         _db(rng.uniform(-22, -14)))
    y = dsp.hp(y, 400.0, 4)                                                  # sin columna 120-400 Hz
    # cerca = más brillo
    y = y if close > 0.8 else dsp.lp(y, 6000 + 12000 * close, 2)
    return y


def _timbre(rng, surface: str):
    """Rasgos de un punto de goteo (borde del capó / espejo / parrilla): centro modal y radio típico de gota.
    Consume del rng exactamente lo mismo que la versión original (4 uniformes + 1 uniforme + 1 choice), así
    los tiempos de las gotas de cada semilla no cambian. Cada gota re-sortea sus modos alrededor de éstos."""
    u = (rng.uniform(-0.1, 0.1, 4) + 0.1) / 0.2                             # 4 x U(0, 1)
    lo, hi = (3000.0, 8000.0) if surface == "glass" else (2000.0, 5000.0)
    fc = lo * (hi / lo) ** u[0]
    f = fc * np.array([1.0, 1.5 + 0.7 * u[1], 2.4 + 1.0 * u[2]])
    f = np.minimum(f, 15000.0)
    r_mm = 0.8 + 1.7 * (rng.uniform(1600, 4200) - 1600.0) / 2600.0           # radio de burbuja 0.8-2.5 mm
    kinds = ["tick", "tick", "plink", "splat"]
    return {"f": f, "r_mm": float(r_mm), "fb": _MINNAERT / r_mm, "kind": str(rng.choice(kinds))}


def _ctrl_1f(n: int, rng, rates=(0.2, 0.45, 1.0), decay=0.6) -> np.ndarray:
    """Modulador ~1/f lento a tasa de control (nudos con interpolación coseno por octava), en [-1, 1]."""
    tc = np.arange(0.0, n / SR + 0.05, 0.005)
    y = np.zeros_like(tc)
    for o, r in enumerate(rates):
        step = 1.0 / r
        k = int(tc[-1] / step) + 3
        v = rng.uniform(-1, 1, k)
        u = tc / step + rng.uniform(0, 1)
        i = np.floor(u).astype(np.int64)
        w = 0.5 - 0.5 * np.cos(np.pi * (u - i))
        y += decay ** o * (v[i] * (1 - w) + v[i + 1] * w)
    y /= np.abs(y).max() + 1e-12
    return np.interp(np.arange(n) / SR, tc, y)


def _rain_panel_ir(rng, surface: str) -> np.ndarray | None:
    """Respuesta de la superficie golpeada por la lluvia: chapa (300 Hz-3 kHz, tau 4-12 ms), vidrio (2-6 kHz,
    tau 2-5 ms); asfalto = None (sólo ruido de impacto)."""
    if surface == "metal":
        k, lo, hi, tl, th = 26, 300.0, 3000.0, 0.004, 0.012
    elif surface == "glass":
        k, lo, hi, tl, th = 18, 2000.0, 6000.0, 0.002, 0.005
    else:
        return None
    f = _spread_freqs(rng, lo, hi, k, 0.1)
    ir = _modal_ir(_n(th * 7), f, rng.uniform(tl, th, k), rng.uniform(-12.0, 0.0, k))
    return ir / (np.sqrt((ir ** 2).sum()) + 1e-12)


def _rain(dur, rng, *, rate, surface, spread, distance, puddles, wash_db, variation_db, space, send_db):
    """Lluvia: impactos Poisson (rate 100-800/s) con intensidad 1/f lenta (0.2-1 Hz), tamaño de gota log-normal
    -> nivel (-30..0 dB) y centro espectral (gotas chicas 4-10 kHz, grandes 1-3 kHz); cada impacto es una
    ráfaga de ruido 0.5-3 ms filtrada a su banda (vectorizado: 6 clases de tamaño, tren de impulsos * ruido)
    que además excita los modos de la superficie (chapa / vidrio; asfalto = sólo ruido), burbujas de Minnaert
    en charcos/película con probabilidad `puddles`, y un lavado difuso estéreo 1-12 kHz a wash_db re los
    impactos, con LP suave por distancia (distance 0 cerca .. 1 lejos)."""
    n = _n(dur + 0.12)
    ne = _n(dur)
    dist = float(np.clip(distance, 0.0, 1.0))
    # intensidad: modula la tasa y el nivel
    mod = _ctrl_1f(n, rng)
    inten = _db(float(variation_db) * mod)                                     # +-variation_db
    r_t = rate * inten ** 1.6
    r_max = float(r_t.max())
    nt = rng.poisson(r_max * dur)
    ts = np.sort(rng.uniform(0.0, dur - 0.004, nt))
    keep = rng.random(nt) < r_t[(ts * SR).astype(np.int64)] / r_max
    ts = ts[keep]
    m = len(ts)
    d_mm = np.clip(rng.lognormal(np.log(0.9), 0.5, m), 0.3, 4.0)
    u = np.log(d_mm / 0.3) / np.log(4.0 / 0.3)                                # 0 (chica) .. 1 (grande)
    lvl = _db(-30.0 + 30.0 * u + rng.uniform(-3.0, 1.5, m)) * inten[(ts * SR).astype(np.int64)]
    pans = rng.uniform(-spread, spread, m)
    gl, gr = dsp.pan_gains(pans)
    idx = (ts * SR).astype(np.int64)
    imp = np.zeros((n, 2))
    edges = np.linspace(0.0, 1.0 + 1e-9, 7)
    for b in range(6):
        sel = (u >= edges[b]) & (u < edges[b + 1])
        if not sel.any():
            continue
        ub = 0.5 * (edges[b] + edges[b + 1])
        fc = float(np.exp(np.log(8000.0) + (np.log(1500.0) - np.log(8000.0)) * ub))
        tau = (0.5e-3 + 2.5e-3 * ub) / 3.0                                     # ráfaga 0.5-3 ms
        kn = np.exp(-np.arange(_n(tau * 6)) / (tau * SR))
        ka = max(2, _n(0.0001))
        kn[:ka] *= np.linspace(0.0, 1.0, ka)
        tr = np.zeros((n, 2))
        np.add.at(tr[:, 0], idx[sel], lvl[sel] * gl[sel])
        np.add.at(tr[:, 1], idx[sel], lvl[sel] * gr[sel])
        env = signal.oaconvolve(tr, kn[:, None], axes=0)[:n]
        nz = rng.standard_normal(n)
        x = env * nz[:, None]
        x = dsp.bp(x, max(400.0, fc / 1.9), min(16000.0, fc * 1.9), 2)
        imp += x * np.sqrt(fc / 3000.0)                                        # ráfagas brillantes = más energía
    out = imp.copy()
    ir = _rain_panel_ir(rng, surface)
    if ir is not None:
        ir2 = _rain_panel_ir(rng, surface)                                      # dos zonas del panel (L / R)
        pan_ = np.stack([signal.oaconvolve(imp[:, 0], ir)[:n], signal.oaconvolve(imp[:, 1], ir2)[:n]], axis=1)
        out = 0.55 * imp + pan_ * (np.sqrt(np.mean(imp ** 2)) / (np.sqrt(np.mean(pan_ ** 2)) + 1e-12))
    else:
        # asfalto: salpicadura de micro-gotitas (HF corta) sobre el ruido de impacto
        out = imp + 0.35 * dsp.hp(imp, 5000.0, 2)
    # burbujas de Minnaert (charcos / película de agua)
    pb = float(np.clip(puddles, 0.0, 0.5))
    if pb > 0 and m:
        bsel = np.nonzero(rng.random(m) < pb)[0]
        ref = np.abs(out).max() + 1e-12
        for j in bsel:
            r_mm = float(np.clip(rng.lognormal(np.log(1.1), 0.35), 0.5, 2.5))
            f0 = _MINNAERT / r_mm
            tb = float(np.clip(rng.uniform(25.0, 60.0) / (np.pi * f0), 0.003, 0.012))
            bb = dsp.bubble(f0, tb, _n(min(0.06, 6.0 * tb + 0.003)), glide=rng.uniform(0.08, 0.2), rng=rng)
            bb = bb / (np.abs(bb).max() + 1e-12) * lvl[j] * ref * _db(-8.0)
            dsp.mix_into(out, dsp.pan(bb, float(pans[j])), int(idx[j]) + _n(rng.uniform(0.001, 0.004)))
    # lavado difuso: la lluvia lejana de todo el campo, estéreo decorrelacionado 1-12 kHz
    wash = dsp.decorrelated_stereo(lambda r: dsp.bp(dsp.pink(n, r), 1000.0, 12000.0, 2), rng, 0.3)
    wash *= np.sqrt(inten)[:, None] * _db(1.0 * _ctrl_1f(n, rng, (1.5, 3.0, 6.0)))[:, None]
    wash *= np.sqrt(np.mean(out ** 2)) / (np.sqrt(np.mean(wash ** 2)) + 1e-12) * _db(float(wash_db))
    wash = dsp.lp(wash, 11000.0 - 5000.0 * dist, 2)
    out = out + wash
    if dist > 0.05:
        out = dsp.lp(out, float(np.clip(18000.0 - 12000.0 * dist, 4000.0, 18000.0)), 2)
    out = dsp.hp(out, 250.0, 2)
    out[ne:] *= np.linspace(1.0, 0.0, n - ne)[:, None]
    out = dsp.fade(out, 0.01, 0.01)
    out = _space(out, space, send_db, hp_send=400.0)
    return out, m


@recipe("fol.droplets", family="foley", sync="start", kind="event")
def droplets(dur, rng, *, rate=6.0, surface="metal", trickle=0.5, spread=0.7, space="city_day_street",
             send_db=-24.0, first_s=None, mode="drip", distance=0.3, puddles=None, wash_db=-12.0,
             variation_db=4.0, **_):
    """Gotas cayendo/escurriendo sobre carrocería, muy cerca y detalladas. surface: metal | glass.
    Puntos de goteo cuasi-periódicos (timbre y pan propios) + gotas Poisson + hilo de escurrimiento.
    mode='rain': LLUVIA (no goteo). rate = impactos/s (100-800; un rate < 50 se toma como 300), surface
    metal | glass | asphalt, distance 0..1 (LP suave), puddles = prob. de burbuja por gota (default 0.18
    asfalto, 0.1 chapa, 0.06 vidrio), wash_db = lavado difuso re impactos (-12), variation_db = profundidad de
    la intensidad 1/f (4 dB). Ver _rain."""
    if str(mode).lower() == "rain":
        sf = str(surface).lower()
        sf = "glass" if sf.startswith("gl") else ("asphalt" if sf.startswith(("as", "road", "st")) else "metal")
        dur = max(0.3, float(dur))
        rr = float(rate) if float(rate) >= 50.0 else 300.0
        pb = {"asphalt": 0.18, "metal": 0.1, "glass": 0.06}[sf] if puddles is None else float(puddles)
        out, m = _rain(dur, rng, rate=float(np.clip(rr, 50.0, 1500.0)), surface=sf,
                       spread=float(np.clip(spread, 0.0, 1.0)), distance=distance, puddles=pb,
                       wash_db=wash_db, variation_db=variation_db, space=space, send_db=send_db)
        return Render(_finish(out, fin=0.01, fout=0.03), sync_offset=0,
                      meta={"mode": "rain", "events": int(m), "surface": sf, "rate": rr})
    surface = "glass" if str(surface).lower().startswith("gl") else "metal"
    dur = max(0.2, float(dur))
    rate = max(0.1, float(rate))
    n = _n(dur + 0.15)
    out = np.zeros((n, 2))
    events = []                         # (t, timbre, pan, close)
    # puntos de goteo (bordes del capó / espejo / parrilla)
    n_src = int(np.clip(round(rate / 2.5), 1, 4))
    r_src = 0.55 * rate / n_src
    for s in range(n_src):
        tb = _timbre(rng, surface)
        p = rng.uniform(-spread, spread)
        close = rng.uniform(0.6, 1.0)
        per = 1.0 / r_src
        t = rng.uniform(0.0, per)
        while t < dur - 0.02:
            events.append((t, tb, p, close))
            t += per * rng.uniform(0.82, 1.18)
    # gotas sueltas (Poisson)
    for t in dsp.poisson_times(dur - 0.02, 0.45 * rate, rng):
        events.append((t, _timbre(rng, surface), rng.uniform(-spread, spread), rng.uniform(0.4, 1.0)))
    # garantizar una gota al comienzo del plano (el corte necesita un contacto)
    t_first = float(first_s) if first_s is not None else rng.uniform(0.03, 0.08)
    if not events or min(e[0] for e in events) > 0.1:
        events.append((t_first, _timbre(rng, surface), rng.uniform(-0.3, 0.3), 1.0))
    events.sort(key=lambda e: e[0])
    for t, tb, p, close in events:
        d = _drop(rng, surface, tb, close)
        g = _db(rng.uniform(-7.0, 0.0)) * (0.35 + 0.65 * close)
        dsp.mix_into(out, dsp.pan(d, float(np.clip(p + rng.uniform(-0.08, 0.08), -1, 1))), _n(t + 0.004), g)
    peak_ref = np.abs(out).max() + 1e-12
    # hilo de escurrimiento: micro-burbujas densas, muy bajas, con caudal 1/f
    if trickle > 0:
        flow_rate = 90.0 * float(trickle)
        tt = dsp.poisson_times(dur, flow_rate, rng)
        tr = np.zeros((n, 2))
        flow = 0.6 + 0.4 * dsp.random_walk(n, rng, 1.5)
        for t in tt:
            nb = _n(0.012)
            b = dsp.bubble(rng.uniform(3500, 10000), rng.uniform(0.0008, 0.0025), nb,
                           glide=rng.uniform(0.1, 0.4), rng=rng)
            i = _n(t)
            dsp.mix_into(tr, dsp.pan(b, rng.uniform(-spread, spread)), i,
                         _db(rng.uniform(-10, 0)) * flow[min(i, n - 1)])
        film = np.stack([dsp.hp(rng.standard_normal(n), 5000, 2), dsp.hp(rng.standard_normal(n), 5000, 2)], 1)
        tr += film * 0.01 * flow[:, None]
        tr = dsp.fade(tr, 0.08, 0.1)
        out += tr / (np.abs(tr).max() + 1e-12) * peak_ref * _db(-24.0 + 6.0 * float(trickle))
    # superficie muy cerca: reflexión temprana de la carrocería (1.5-3 ms) + calle de día
    er = np.zeros_like(out)
    for ms, gdb, ch in ((rng.uniform(1.3, 1.9), -9.0, 0), (rng.uniform(2.2, 3.1), -11.0, 1)):
        k = int(ms * 1e-3 * SR)
        er[k:, ch] += _db(gdb) * out[:-k, 1 - ch]
    out = out + dsp.lp(er, 7000, 2)
    out = dsp.fade(out, 0.003, 0.01)
    out = _space(out, space, send_db, hp_send=400.0)
    return Render(_finish(out, fout=0.03), sync_offset=0,
                  meta={"events": len(events), "first_s": round(float(min(e[0] for e in events)) + 0.004, 4)})


# =====================================================================================================
# fol.suspension
# =====================================================================================================

def _susp_hit(rng, n):
    t = np.arange(n) / SR
    body = (0.9 * _damped(n, rng.uniform(78, 95), rng.uniform(0.035, 0.05), glide=-0.08, glide_tau=0.04) +
            0.55 * _damped(n, rng.uniform(120, 150), rng.uniform(0.022, 0.032), glide=-0.05))
    body = signal.oaconvolve(body, _pulse(rng.uniform(0.006, 0.009)))[:n]
    body /= np.abs(body).max() + 1e-12
    knock = _strike(_pulse(1.5e-3), [rng.uniform(380, 460), rng.uniform(560, 680)], [0.012, 0.009], [0, -3],
                    rng, tj=0.2, n=n)
    knock = dsp.lp(knock / (np.abs(knock).max() + 1e-12) + 0.6 * _burst(n, rng, 0.006, 250, 900), 1500, 2)
    knock /= np.abs(knock).max() + 1e-12
    tick = _burst(n, rng, 0.003, 1500, 3200)           # junta del camino a través de la carrocería
    tick /= np.abs(tick).max() + 1e-12
    reb = dsp.lp(rng.standard_normal(n), 500, 2) * np.exp(-((t - 0.06) / 0.03) ** 2)   # rebote del amortiguador
    reb /= np.abs(reb).max() + 1e-12
    return body + _db(-6.0) * knock + _db(-21.0) * tick + _db(-22.0) * reb


@recipe("fol.suspension", family="foley", sync="transient", kind="event")
def suspension(dur, rng, *, double=True, speed_kmh=50.0, wheelbase_m=2.75, space="cabin_small",
               send_db=-14.0, **_):
    """Golpe sordo de suspensión desde la cabina (junta del camino): cuerpo amortiguado 70-150 Hz + knock
    medio apagado; con double=True el eje trasero repite wheelbase/v después. Sin vibraciones. sync = 1er golpe."""
    pre = _n(0.006)
    gap = float(wheelbase_m) / max(1.0, float(speed_kmh) / 3.6)
    n = pre + _n(max(float(dur), (gap if double else 0.0) + 0.3))
    y = np.zeros(n)
    nk = _n(0.3)
    dsp.mix_into(y, _susp_hit(rng, nk), pre, 1.0)
    if double:
        dsp.mix_into(y, _susp_hit(rng, nk), pre + _n(gap * rng.uniform(0.98, 1.02)), _db(rng.uniform(-6, -4)))
    y = dsp.fade(y, 0.003, 0.02)
    y = _space(y, space, send_db, hp_send=100.0)
    return Render(_finish(y, hp_hz=70.0), sync_offset=pre, meta={"second_s": round(gap, 4) if double else None})


# =====================================================================================================
# fol.screen_tap
# =====================================================================================================

def _tap(rng):
    """Toque de yema: la pulpa (pulso blando 1.6-2.6 ms) da el cuerpo apagado del soporte; el borde firme del
    dedo (~0.7-1 ms) excita los modos del vidrio laminado (amortiguados por el propio dedo)."""
    nk = _n(0.06)
    exc = _pulse(rng.uniform(0.7e-3, 1.0e-3))
    glass = _strike(exc, [rng.uniform(1400, 1900), rng.uniform(2600, 3400), rng.uniform(4300, 5200)],
                    [0.004, 0.003, 0.002], [0, -4, -9], rng, tj=0.2, aj=1.5, n=nk)
    glass = dsp.hp(glass, 900, 2)                       # sin la respuesta cuasi-estática (LF) del pulso
    glass /= np.abs(glass).max() + 1e-12
    mount = _strike(_pulse(rng.uniform(1.6e-3, 2.6e-3)), [rng.uniform(320, 480)], [0.005], [0], n=nk)
    mount /= np.abs(mount).max() + 1e-12
    skin = _burst(nk, rng, 0.0015, 1500, 6500, attack=0.0006)
    skin /= np.abs(skin).max() + 1e-12
    return glass + _db(-8.0) * mount + _db(-12.0) * skin


@recipe("fol.screen_tap", family="foley", sync="transient", kind="event")
def screen_tap(dur, rng, *, count=1, space="cabin_small", send_db=-16.0, **_):
    """Toque muy suave de yema sobre pantalla de vidrio: modos amortiguados por el dedo + soporte + piel
    + despegue sutil. count=2 = doble toque. sync = primer toque."""
    pre = _n(0.006)
    count = max(1, int(count))
    n = pre + _n(max(float(dur), 0.18 * count + 0.12))
    y = np.zeros(n)
    t = pre
    for i in range(count):
        dsp.mix_into(y, _tap(rng), t, 1.0 if i == 0 else _db(rng.uniform(-3, -1)))
        lift = _burst(_n(0.01), rng, 0.0006, 2000, 7000, attack=0.0003)      # despegue de la piel
        dsp.mix_into(y, lift / (np.abs(lift).max() + 1e-12), t + _n(rng.uniform(0.06, 0.11)), _db(-22.0))
        t += _n(rng.uniform(0.13, 0.18))
    y = dsp.fade(y, 0.003, 0.01)
    y = _space(y, space, send_db)
    return Render(_finish(y, hp_hz=150.0), sync_offset=pre)


# =====================================================================================================
# fol.led_fizz
# =====================================================================================================

@recipe("fol.led_fizz", family="foley", sync="start", kind="event")
def led_fizz(dur, rng, *, ramp=0.35, density=1.0, hp_hz=7500.0, pops=5, corr=0.5, **_):
    """Fizz eléctrico finísimo de LEDs encendiéndose: chisporroteo de impulsos (densidad en rampa, cola
    pesada) HP 6-12 kHz variable + siseo fino + pops de segmentos al encender. Sutil."""
    dur = max(0.15, float(dur))
    n = _n(dur)
    t = np.arange(n) / SR
    r_end = max(0.05, float(ramp)) * dur
    # densidad: 40/s -> 1500/s en la rampa, luego se asienta (decae a ~45 %) con deriva 1/f
    dens = 40.0 + 1460.0 * float(density) * _ss(t, 0.0, r_end) ** 1.6
    dens *= 1.0 - 0.55 * _ss(t, r_end, dur) ** 0.8
    dens *= 1.0 + 0.2 * dsp.random_walk(n, rng, 2.0)
    lvl = 0.25 + 0.75 * _ss(t, 0.0, r_end * 0.8)
    lvl *= 1.0 - 0.45 * _ss(t, r_end, dur)

    def crackle(rng_):
        hit = rng_.random(n) < dens / SR
        amp = np.minimum(0.4 + rng_.pareto(3.5, n), 3.0) * rng_.choice([-1.0, 1.0], n)   # cola pesada, acotada
        return np.where(hit, amp, 0.0)

    shared, l_own, r_own = crackle(rng), crackle(rng), crackle(rng)
    k, j = np.sqrt(corr), np.sqrt(1 - corr)
    st = np.stack([k * shared + j * l_own, k * shared + j * r_own], axis=1)
    hs = rng.standard_normal(n)                         # siseo finísimo (misma correlación L/R que el crackle)
    st += 0.12 * np.stack([k * hs + j * rng.standard_normal(n), k * hs + j * rng.standard_normal(n)], axis=1)
    st *= lvl[:, None]
    # pops de segmentos encendiéndose (dentro de la rampa), antes del HP: mismo color que el fizz
    ref = np.abs(st).max() + 1e-12
    for i in range(int(pops)):
        tp = (i + rng.uniform(0.1, 0.9)) / max(1, int(pops)) * r_end
        pk = _burst(_n(0.003), rng, rng.uniform(0.1e-3, 0.25e-3))
        side = rng.uniform(-0.4, 0.4)
        dsp.mix_into(st, dsp.pan(pk / (np.abs(pk).max() + 1e-12), side), _n(tp), ref * _db(rng.uniform(-9, -4)))
    fc = float(hp_hz) * (1.0 + 0.08 * dsp.random_walk(n, rng, 1.0)) * (0.9 + 0.2 * _ss(t, 0, r_end))
    st = dsp.tv_filter(st, np.clip(fc, 6000, 12000), "highpass", q=0.7, block=128, stages=2)
    st = dsp.tv_filter(st, np.clip(fc * 1.35, 8000, 16000), "peak", q=1.2, gain_db=4.0, block=128)
    st /= np.abs(st).max() + 1e-12
    return Render(_finish(st, hp_hz=120.0, fin=0.004, fout=0.04), sync_offset=0)


# =====================================================================================================
# fol.hands_wheel
# =====================================================================================================

def _slide(rng, n_len: int, intensity: float) -> np.ndarray:
    """Un deslizamiento de mano sobre cuero: velocidad en campana -> fricción (BP que sigue la velocidad,
    rugosidad de piel), granos de poro/costura (Poisson ~ v) y tren stick-slip (tasa ~ v)."""
    v = dsp.swell(n_len, peak_pos=rng.uniform(0.3, 0.5), attack_pow=1.6, release_pow=1.4)
    v = np.clip(v * (1 + 0.15 * dsp.random_walk(n_len, rng, 6.0)), 0, None)
    # fricción: centroide 1.2 -> 3.5 kHz con la velocidad (BP variable), techo suave
    fc = 1200 + 2300 * v
    fr = dsp.tv_filter(rng.standard_normal(n_len), fc, "bandpass", q=0.9, block=64)
    fr = dsp.hp(fr, 900, 2)
    ridges = np.clip(1.0 + 0.5 * _rmsn(dsp.lp(rng.standard_normal(n_len), 60, 2)), 0.2, None)
    fr *= v ** 1.5 * ridges
    # granos (poros del cuero perforado / costuras): impulsos Poisson con densidad ~ v, redondeados
    dens = (200 + 1300 * v) / SR
    imp = (rng.random(n_len) < dens) * (0.5 + rng.pareto(5.0, n_len)) * rng.choice([-1.0, 1.0], n_len)
    kl = _n(0.0008)
    ker = rng.standard_normal(kl) * np.exp(-np.arange(kl) / _n(0.00025))
    gr = dsp.lp(dsp.bp(signal.oaconvolve(imp, ker)[:n_len], 1500, 6000, 2), 5000, 2) * v
    # stick-slip (piel que se adhiere y suelta), pulsos redondos
    ss = dsp.stick_slip(n_len, 120 + 500 * v, rng, jitter=0.3, sharp=0.0025)
    ss = dsp.bp(ss, 1200, 4500, 2) * v ** 1.5
    y = _rmsn(fr) + 0.3 * _rmsn(gr) + 0.22 * _rmsn(ss)
    y = dsp.lp(y, 6500, 2)                              # cuero = suave: el aire cae por encima de ~6 kHz
    return y / (np.abs(y).max() + 1e-12) * (0.6 + 0.4 * intensity)


def _grip(rng, n_len: int) -> np.ndarray:
    """Agarre: palma que se apoya (thump blando, amortiguado) + crujido corto de cuero (stick-slip lento)."""
    palm = signal.oaconvolve(_damped(n_len, rng.uniform(300, 420), 0.008), _pulse(rng.uniform(3e-3, 5e-3)))[:n_len]
    palm /= np.abs(palm).max() + 1e-12
    skin = dsp.lp(_burst(n_len, rng, 0.006, 1200, 4500, attack=0.003), 5000, 4)
    skin /= np.abs(skin).max() + 1e-12
    nc = _n(rng.uniform(0.06, 0.11))
    cr = dsp.stick_slip(nc, np.linspace(rng.uniform(90, 140), rng.uniform(160, 230), nc), rng, jitter=0.25,
                        sharp=0.003)
    cr = dsp.bp(cr, 700, 2600, 2) * dsp.swell(nc, 0.3, 1.5, 1.5)
    cr /= np.abs(cr).max() + 1e-12
    y = 0.5 * palm + 0.5 * skin
    dsp.mix_into(y, cr, _n(0.012), _db(-6.0))
    return y


@recipe("fol.hands_wheel", family="foley", sync="start", kind="event")
def hands_wheel(dur, rng, *, slides=2, grip=True, intensity=0.5, space="cabin_small", send_db=-14.0, **_):
    """Manos deslizándose / tomando un volante de cuero: fricción 1-6 kHz con grano stick-slip que sigue la
    velocidad, dos manos (pan +-0.35), agarre final con palma + crujido suave. sync = primer contacto."""
    dur = max(0.3, float(dur))
    pre = _n(0.004)
    n = pre + _n(dur + 0.15)
    out = np.zeros((n, 2))
    slides = max(1, int(slides))
    first = pre
    for i in range(slides):
        side = -0.35 if i % 2 == 0 else 0.35
        # gestos repartidos en la duración: el primero arranca en el contacto, los demás entran solapados
        t0 = pre if i == 0 else pre + _n(rng.uniform(0.15 + 0.35 * (i - 1) / slides, 0.5) * dur)
        L = min(_n(rng.uniform(0.4, 0.6) * dur), pre + _n(dur) - t0 - _n(0.03))
        if L < _n(0.06):
            continue
        s = _slide(rng, L, float(intensity)) * _db(rng.uniform(-3, 0))
        dsp.mix_into(out, dsp.pan(s, side + rng.uniform(-0.1, 0.1)), t0)
        if grip:
            g = _grip(rng, _n(0.15))
            dsp.mix_into(out, dsp.pan(g, side), t0 + L - _n(0.02), _db(-11.0 + rng.uniform(-2, 1)))
    out = dsp.fade(out, 0.003, 0.02)
    out = _space(out, space, send_db)
    return Render(_finish(out), sync_offset=first)


# =====================================================================================================
# audición de todo el módulo:  python -m sfx.recipes.foley [tag ...]
# =====================================================================================================

AUDITIONS = [
    # (receta, dur, params, at, gain, tag, seed)
    ("fol.phone_shutter", 0.4, {"style": "modern"}, 40.958, -11, "phone_shutter", 0),
    ("fol.phone_shutter", 0.4, {"style": "modern"}, None, None, "phone_shutter_s1", 1),
    ("fol.phone_shutter", 0.4, {"style": "soft"}, None, None, "phone_shutter_soft", 0),
    ("fol.tailgate_close", 1.6, {"motor_s": 1.33, "latch": True}, 42.542, -10, "tailgate_close", 0),
    ("fol.tailgate_close", 1.6, {"motor_s": 1.33, "latch": True}, None, None, "tailgate_close_s1", 1),
    ("fol.gear_selector", 0.4, {"style": "rotary"}, 31.167, -9, "gear_selector", 0),
    ("fol.gear_selector", 0.4, {"style": "rotary"}, None, None, "gear_selector_s1", 1),
    ("fol.gear_selector", 0.4, {"style": "column"}, None, None, "gear_selector_column", 0),
    ("fol.ped_signal", 0.5, {"count": 1, "rate_hz": 1.0}, 14.083, -11, "ped_signal", 0),
    ("fol.ped_signal", 2.5, {"count": 3, "rate_hz": 1.0}, None, None, "ped_signal_x3", 1),
    ("fol.relay_click", 0.3, {}, 3.958, -15, "relay_click", 0),
    ("fol.relay_click", 0.3, {}, None, None, "relay_click_s1", 1),
    ("fol.light_contactor", 1.5, {"hum": 0.5}, 23.625, -11, "light_contactor", 0),
    ("fol.light_contactor", 1.5, {"hum": 0.5}, None, None, "light_contactor_s1", 1),
    ("fol.droplets", 1.2, {"rate": 5.0, "surface": "metal"}, 48.583, -12, "droplets_metal", 0),
    ("fol.droplets", 1.2, {"rate": 5.0, "surface": "metal"}, None, None, "droplets_metal_s1", 1),
    ("fol.droplets", 2.0, {"rate": 6.0, "surface": "glass"}, None, None, "droplets_glass", 0),
    ("fol.suspension", 0.5, {}, 20.708, -15, "suspension", 0),
    ("fol.suspension", 0.5, {}, None, None, "suspension_s1", 1),
    ("fol.screen_tap", 0.3, {}, 39.0, -12, "screen_tap", 0),
    ("fol.screen_tap", 0.4, {"count": 2}, None, None, "screen_tap_double", 1),
    ("fol.led_fizz", 1.15, {}, 26.333, -19, "led_fizz", 0),
    ("fol.led_fizz", 1.15, {}, None, None, "led_fizz_s1", 1),
    ("fol.hands_wheel", 1.2, {}, 20.0, -14, "hands_wheel", 0),
    ("fol.hands_wheel", 1.2, {}, None, None, "hands_wheel_s1", 1),
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
    importlib.import_module("sfx.recipes.foley")

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
              f"clk {met['click_candidates']} {met['click_times_s'][:6]} dc {met['dc_db']}"
              + (f" | ctx pres {ctx.get('pres2k-5k')} hi {ctx.get('high5k-10k')} air {ctx.get('air10k+')}"
                 f" mid {ctx.get('mid500-2k')} low {ctx.get('low60-150')}" if ctx else ""))


if __name__ == "__main__":
    import sys as _sys

    _audition_all(_sys.argv[1:] or None)
