"""Audición de recetas para quien no puede escuchar: WAV + espectrograma PNG + métricas JSON.

Uso:
  python -m sfx.audition <receta> [--dur 3] [--params '{"k": 1}'] [--seed 0]
                         [--at 12.3 --gain -12] [--out out/audition/<familia>] [--tag nombre]

Con --at, además renderiza el contexto (bed + SFX) y un espectrograma comparativo bed / bed+SFX.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import signal

from .core import OUT, RECIPES, SR, load_all_recipes, load_bed, stable_rng, to_db, write_wav
from .render import normalize

BANDS = {"sub<60": (20, 60), "low60-150": (60, 150), "lowmid150-500": (150, 500), "mid500-2k": (500, 2000),
         "pres2k-5k": (2000, 5000), "high5k-10k": (5000, 10000), "air10k+": (10000, 20000)}


def spectrogram_png(x: np.ndarray, path, title: str = "", width: int = 1200, height: int = 360,
                    fmin: float = 30.0, fmax: float = 20000.0, db_range: float = 90.0, marks_s=None, t0: float = 0.0):
    """Espectrograma log-frecuencia (mono = media L/R). marks_s: líneas verticales (s, relativos a x)."""
    m = np.asarray(x, np.float64)
    if m.ndim == 2:
        m = m.mean(axis=1)
    nper = 2048
    hop = max(64, len(m) // width)
    f, t, Z = signal.stft(m, SR, nperseg=nper, noverlap=max(0, nper - hop), boundary=None)
    S = 20 * np.log10(np.abs(Z) + 1e-10)
    S = S - max(S.max(), -200)
    # remuestrear a eje log
    fl = np.geomspace(fmin, fmax, height)
    rows = np.array([np.interp(fl, f, S[:, j]) for j in range(S.shape[1])]).T  # [height, T]
    img = np.clip((rows + db_range) / db_range, 0, 1)[::-1]
    # colormap tipo "magma" simple
    c = np.stack([np.clip(1.6 * img, 0, 1), np.clip(1.6 * img - 0.5, 0, 1) ** 1.2, np.clip(0.6 * img + 0.4 * img ** 3, 0, 1)], axis=-1)
    im = Image.fromarray((c * 255).astype(np.uint8)).resize((width, height))
    d = ImageDraw.Draw(im)
    dur = len(m) / SR
    for fr in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
        y = height - 1 - int(np.log(fr / fmin) / np.log(fmax / fmin) * (height - 1))
        d.line([(0, y), (12, y)], fill=(120, 200, 255))
        d.text((14, y - 6), f"{fr if fr < 1000 else str(fr // 1000) + 'k'}", fill=(120, 200, 255))
    step = 0.5 if dur <= 8 else (1.0 if dur <= 20 else 2.0)
    for k in np.arange(0, dur + 1e-9, step):
        xx = int(k / dur * (width - 1))
        d.line([(xx, height - 8), (xx, height - 1)], fill=(255, 255, 0))
        d.text((xx + 2, height - 20), f"{t0 + k:.1f}", fill=(255, 255, 0))
    for mk in marks_s or []:
        xx = int(mk / dur * (width - 1))
        d.line([(xx, 0), (xx, height - 1)], fill=(0, 255, 120))
    if title:
        d.text((60, 4), title, fill=(255, 255, 255))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def dsp_pad(x, w):
    k = (len(x) + w - 1) // w * w
    return np.concatenate([x, np.zeros(k - len(x))])


def metrics(a: np.ndarray, sync: int) -> dict:
    a = np.asarray(a, np.float64)
    m = a.mean(axis=1)
    out = {"dur_s": round(len(a) / SR, 3), "sync_s": round(sync / SR, 4),
           "peak_dbfs": round(float(to_db(np.abs(a).max())), 2),
           "rms_dbfs": round(float(to_db(np.sqrt((a ** 2).mean()))), 2),
           "dc_db": round(float(to_db(abs(m.mean()))), 1),
           "finite": bool(np.isfinite(a).all())}
    out["crest_db"] = round(out["peak_dbfs"] - out["rms_dbfs"], 1)
    # bandas (energía relativa al total)
    F = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2
    f = np.fft.rfftfreq(len(m), 1 / SR)
    tot = F.sum() + 1e-20
    out["bands_db"] = {k: round(float(10 * np.log10(F[(f >= lo) & (f < hi)].sum() / tot + 1e-12)), 1)
                       for k, (lo, hi) in BANDS.items()}
    out["centroid_hz"] = round(float((F * f).sum() / tot), 0)
    # correlación L/R
    if a.shape[1] == 2 and np.std(a[:, 0]) > 0 and np.std(a[:, 1]) > 0:
        out["lr_corr"] = round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 2)
    # envolvente: pico de energía y energía alrededor del sync
    hop = 240
    e = np.sqrt(np.convolve(m ** 2, np.ones(hop) / hop, mode="same"))
    out["energy_peak_s"] = round(float(np.argmax(e) / SR), 3)
    w = int(0.02 * SR)
    pre = e[max(0, sync - 3 * w):max(1, sync - w)].mean() if sync > w else 0.0
    post = e[sync:sync + w].mean() if sync < len(e) - 1 else 0.0
    out["sync_rise_db"] = round(float(to_db(post + 1e-12) - to_db(pre + 1e-12)), 1)
    # clics: picos de energía HF (>6 kHz) en 0.5 ms que superan 9 dB la mediana local (~20 ms)
    hf = signal.sosfilt(signal.butter(4, 6000, btype="highpass", fs=SR, output="sos"), m)
    w5 = 12
    eh = np.sqrt((dsp_pad(hf ** 2, w5).reshape(-1, w5)).mean(axis=1)) + 1e-9
    from scipy.ndimage import median_filter

    med = median_filter(eh, size=81, mode="nearest") + 1e-9
    ratio = 20 * np.log10(eh / med)
    idx = np.nonzero((ratio > 9) & (eh > 10 ** (-60 / 20)))[0]
    # agrupar candidatos contiguos
    groups = []
    for i in idx:
        if not groups or i - groups[-1] > 20:
            groups.append(i)
    out["click_candidates"] = len(groups)
    out["click_times_s"] = [round(float(g * w5 / SR), 4) for g in groups[:12]]
    # repetición (autocorrelación de envolvente) para camas
    if len(m) > SR:
        ed = e[::480] - e[::480].mean()
        ac = np.correlate(ed, ed, "full")[len(ed) - 1:]
        ac = ac / (ac[0] + 1e-12)
        lo = 10  # 0.1 s
        out["max_autocorr_0.1-5s"] = round(float(ac[lo:min(len(ac), 500)].max()), 2) if len(ac) > lo + 1 else None
    return out


def audition(name: str, dur: float, params: dict, seed: int = 0, at: float | None = None, gain: float | None = None,
             out_dir: Path | None = None, tag: str | None = None) -> dict:
    load_all_recipes()
    if name not in RECIPES:
        raise SystemExit(f"receta no registrada: {name}. Registradas: {sorted(RECIPES)}")
    info = RECIPES[name]
    out_dir = Path(out_dir or OUT / "audition" / info["family"])
    tag = tag or name.replace(".", "_")
    rng = stable_rng("audition", name, seed)
    r = info["fn"](float(dur), rng, **params)
    a = normalize(r.audio, info["kind"])
    met = metrics(a, r.sync_offset)
    met.update(recipe=name, kind=info["kind"], sync_type=info["sync"], params=params, meta=r.meta)
    write_wav(out_dir / f"{tag}.wav", a)
    spectrogram_png(a, out_dir / f"{tag}.png", title=f"{name} {json.dumps(params)[:80]}", marks_s=[r.sync_offset / SR])
    if at is not None:
        bed = load_bed().astype(np.float64)
        g = 10 ** ((gain if gain is not None else (-14 if info["kind"] == "bed" else -10)) / 20)
        start = int(at * SR) - r.sync_offset
        i0 = max(0, start - SR)
        i1 = min(len(bed), start + len(a) + SR)
        ctx_bed = bed[i0:i1].copy()
        ctx = ctx_bed.copy()
        s0 = start - i0
        seg = a[max(0, -s0):max(0, -s0) + len(ctx) - max(0, s0)]
        ctx[max(0, s0):max(0, s0) + len(seg)] += g * seg
        write_wav(out_dir / f"{tag}__ctx.wav", np.clip(ctx, -1, 1))
        both = np.concatenate([ctx_bed, np.zeros((int(0.05 * SR), 2)), ctx])
        spectrogram_png(both, out_dir / f"{tag}__ctx.png", title=f"izq: bed solo | der: bed + {name} @ {at}s ({20*np.log10(g):.0f} dB)",
                        marks_s=[(start - i0 + r.sync_offset) / SR, (len(ctx_bed) + int(0.05 * SR) + start - i0 + r.sync_offset) / SR])
        # cuánto se destaca el SFX sobre el bed en el tramo (por banda)
        sfx_only = np.zeros_like(ctx)
        sfx_only[max(0, s0):max(0, s0) + len(seg)] = g * seg
        met["context"] = {"at": at, "gain_db": round(20 * np.log10(g), 1),
                          "sfx_vs_bed_db_by_band": _band_ratio(sfx_only, ctx_bed)}
    (out_dir / f"{tag}.json").write_text(json.dumps(met, indent=1, default=str))
    return met


def _band_ratio(sfx, bed):
    res = {}
    ms, mb = sfx.mean(axis=1), bed.mean(axis=1)
    for k, (lo, hi) in BANDS.items():
        sos = signal.butter(4, [lo, min(hi, SR / 2 - 200)], btype="band", fs=SR, output="sos")
        es = np.sqrt((signal.sosfilt(sos, ms) ** 2).mean()) + 1e-12
        eb = np.sqrt((signal.sosfilt(sos, mb) ** 2).mean()) + 1e-12
        res[k] = round(float(20 * np.log10(es / eb)), 1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe")
    ap.add_argument("--dur", type=float, default=2.0)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--at", type=float, default=None)
    ap.add_argument("--gain", type=float, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--tag", default=None)
    a = ap.parse_args()
    met = audition(a.recipe, a.dur, json.loads(a.params), a.seed, a.at, a.gain, Path(a.out) if a.out else None, a.tag)
    print(json.dumps(met, indent=1, default=str))


if __name__ == "__main__":
    main()
