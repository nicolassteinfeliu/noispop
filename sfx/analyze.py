"""Análisis de la referencia: cortes, grilla de beats, locución (VAD), ocupación espectral,
rasgos de imagen y tonalidad. Escribe analysis/*.json (+ .npz con curvas por frame).

Uso:  python -m sfx.analyze
"""
from __future__ import annotations

import json
import subprocess

import numpy as np
from scipy import signal

from .core import ANALYSIS, CUES, FPS, N_FRAMES, N_TOTAL, PICTURE, ROOT, SPF, SR, load_bed, to_db

VAD_MODEL = ROOT / "tools" / "models" / "silero_vad.onnx"


# ---------------------------------------------------------------- cortes

def detect_cuts(threshold: float = 0.25) -> list[int]:
    cmd = ["ffmpeg", "-hide_banner", "-i", str(PICTURE), "-vf", f"select='gt(scene,{threshold})',showinfo",
           "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    frames = []
    for tok in err.split():
        if tok.startswith("pts_time:"):
            frames.append(int(round(float(tok.split(":")[1]) * FPS)))
    return sorted(set(frames))


# ---------------------------------------------------------------- imagen

def video_features():
    """Por frame: luma media, luma top-1 %, energía de movimiento y centroide horizontal del movimiento (-1..1)."""
    w, h = 160, 90
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(PICTURE), "-vf", f"scale={w}:{h},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32) / 255.0
    n = len(v)
    luma = v.mean(axis=(1, 2))
    top = np.percentile(v.reshape(n, -1), 99, axis=1)
    diff = np.zeros_like(v)
    diff[1:] = np.abs(v[1:] - v[:-1])
    motion = diff.mean(axis=(1, 2))
    xs = np.linspace(-1, 1, w)[None, None, :]
    wsum = diff.sum(axis=(1, 2)) + 1e-9
    centroid = (diff * xs).sum(axis=(1, 2)) / wsum
    # brillo horizontal: centroide de la luz (para seguir faros/LED)
    bright = np.clip(v - np.percentile(v.reshape(n, -1), 90, axis=1)[:, None, None], 0, None)
    bsum = bright.sum(axis=(1, 2)) + 1e-9
    light_x = (bright * xs).sum(axis=(1, 2)) / bsum
    return dict(luma=luma, top=top, motion=motion, motion_x=centroid, light_x=light_x)


# ---------------------------------------------------------------- beats

def beat_grid(bed: np.ndarray):
    """Grilla de bombo: picos reales de la banda 40-120 Hz + ajuste lineal (período/fase)."""
    mono = bed.mean(axis=1).astype(np.float64)
    sos = signal.butter(4, [40, 120], btype="band", fs=SR, output="sos")
    low = signal.sosfiltfilt(sos, mono)
    hop = 48  # 1 ms
    env = np.sqrt(np.convolve(low ** 2, np.ones(480) / 480, mode="same"))[::hop]
    fr = SR / hop
    pk, _ = signal.find_peaks(env, distance=int(0.3 * fr), height=env.max() * 0.25)
    peaks = pk / fr
    # onset = primer cruce del 50 % del pico hacia atrás
    onsets = []
    for p_ in pk:
        thr = env[p_] * 0.5
        i = p_
        while i > 0 and env[i] > thr and p_ - i < int(0.08 * fr):
            i -= 1
        onsets.append(i / fr)
    onsets = np.array(onsets)
    # ajuste lineal robusto sobre la sección regular
    period0 = np.median(np.diff(onsets))
    idx = np.round((onsets - onsets[0]) / period0)
    A = np.stack([idx, np.ones_like(idx)], axis=1)
    sol, *_ = np.linalg.lstsq(A, onsets, rcond=None)
    for _ in range(3):
        res = onsets - A @ sol
        ok = np.abs(res) < 0.03
        sol, *_ = np.linalg.lstsq(A[ok], onsets[ok], rcond=None)
    period, phase = float(sol[0]), float(sol[1] % sol[0])
    nz = np.nonzero(env > env.max() * 0.05)[0]
    active_end = float(nz[-1] / fr)
    beats = np.arange(phase, active_end, period)
    amps = env[pk] / env[pk].max()
    return dict(period_s=period, bpm=60.0 / period, phase_s=phase,
                beats_s=[round(float(b), 4) for b in beats],
                kick_onsets_s=[round(float(o), 4) for o in onsets],
                kick_strength_db=[round(float(a), 1) for a in to_db(amps)],
                music_end_s=active_end)


# ---------------------------------------------------------------- locución (VAD)

def _center_extract(bed: np.ndarray) -> np.ndarray:
    """Extrae el centro (la locución vive en el centro) y limita banda 100 Hz - 4 kHz."""
    m = (bed[:, 0] + bed[:, 1]) * 0.5
    s = (bed[:, 0] - bed[:, 1]) * 0.5
    f, t, M = signal.stft(m, SR, nperseg=2048, noverlap=1536)
    _, _, S = signal.stft(s, SR, nperseg=2048, noverlap=1536)
    mask = (np.abs(S) < 0.35 * np.abs(M)).astype(np.float32)
    band = ((f > 100) & (f < 4000)).astype(np.float32)[:, None]
    _, c = signal.istft(M * mask * band, SR, nperseg=2048, noverlap=1536)
    return c[: len(m)]


def vad(bed: np.ndarray):
    import onnxruntime as ort

    c = _center_extract(bed)
    x16 = signal.resample_poly(c, 1, 3).astype(np.float32)
    x16 /= max(1e-6, np.abs(x16).max()) / 0.8
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 1
    opts.intra_op_num_threads = 1
    sess = ort.InferenceSession(str(VAD_MODEL), sess_options=opts, providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), np.float32)
    ctx = np.zeros((1, 64), np.float32)
    probs = []
    for i in range(0, len(x16) - 512 + 1, 512):
        chunk = x16[i:i + 512][None, :]
        inp = np.concatenate([ctx, chunk], axis=1)
        out, state = sess.run(None, {"input": inp, "state": state, "sr": np.array(16000, dtype=np.int64)})
        probs.append(float(out[0, 0]))
        ctx = inp[:, -64:]
    probs = np.array(probs)
    hop_s = 512 / 16000
    # histéresis
    on, off = 0.5, 0.35
    regions, active, start = [], False, 0
    for i, p in enumerate(probs):
        if not active and p >= on:
            active, start = True, i
        elif active and p < off:
            active = False
            regions.append([start * hop_s, i * hop_s])
    if active:
        regions.append([start * hop_s, len(probs) * hop_s])
    # unir huecos < 0.2 s, descartar < 0.25 s
    merged = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < 0.2:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    merged = [r for r in merged if r[1] - r[0] >= 0.25]
    padded = [[round(max(0, a - 0.12), 3), round(b + 0.2, 3)] for a, b in merged]
    return dict(regions_raw=[[round(a, 3), round(b, 3)] for a, b in merged], regions=padded,
                probs_hop_s=hop_s, probs=[round(float(p), 3) for p in probs])


# ---------------------------------------------------------------- ocupación espectral

BANDS = {"sub": (25, 60), "low": (60, 150), "lowmid": (150, 500), "mid": (500, 2000),
         "presence": (2000, 5000), "high": (5000, 10000), "air": (10000, 20000)}


def band_occupancy(bed: np.ndarray):
    """Nivel por banda, por frame de video (dBFS RMS) para mid (L+R) y side (L-R)."""
    m = (bed[:, 0] + bed[:, 1]) * 0.5
    s = (bed[:, 0] - bed[:, 1]) * 0.5
    out = {}
    for name, (lo, hi) in BANDS.items():
        sos = signal.butter(4, [lo, min(hi, SR / 2 - 100)], btype="band", fs=SR, output="sos")
        for lab, x in (("M", m), ("S", s)):
            y = signal.sosfilt(sos, x)
            e = np.sqrt((y[: N_FRAMES * SPF].reshape(N_FRAMES, SPF) ** 2).mean(axis=1))
            out[f"{lab}_{name}"] = to_db(e).astype(np.float32)
    return out


# ---------------------------------------------------------------- tonalidad

def key_estimate(bed: np.ndarray, end_s: float):
    mono = bed[: int(end_s * SR)].mean(axis=1)
    f, t, Z = signal.stft(mono, SR, nperseg=8192, noverlap=6144)
    mag = np.abs(Z)
    sel = (f > 60) & (f < 2000)
    pcs = np.round(12 * np.log2(f[sel] / 440.0)).astype(int) % 12  # 0 = A
    chroma = np.zeros(12)
    for pc in range(12):
        chroma[pc] = mag[sel][pcs == pc].sum()
    chroma = np.roll(chroma, -3)  # 0 = C
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    names = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    res = []
    for k in range(12):
        res.append((float(np.corrcoef(chroma, np.roll(major, k))[0, 1]), f"{names[k]} major"))
        res.append((float(np.corrcoef(chroma, np.roll(minor, k))[0, 1]), f"{names[k]} minor"))
    res.sort(reverse=True)
    return dict(best=res[0][1], corr=round(res[0][0], 3), top5=[[n, round(c, 3)] for c, n in res[:5]],
                chroma_C_based=[round(float(c / chroma.max()), 3) for c in chroma])


# ---------------------------------------------------------------- main

def main():
    ANALYSIS.mkdir(exist_ok=True)
    bed = load_bed()
    print("bed", bed.shape, "peak", float(np.abs(bed).max()))

    cuts = detect_cuts()
    print("cortes (frames):", cuts)

    bg = beat_grid(bed)
    print(f"tempo {bg['bpm']:.2f} BPM, fase {bg['phase_s']:.3f}s, fin música {bg['music_end_s']:.2f}s")

    v = vad(bed)
    print("locución (regiones con pad):", v["regions"])

    occ = band_occupancy(bed)
    vf = video_features()
    k = key_estimate(bed, bg["music_end_s"])
    print("tonalidad:", k["top5"])

    nz = np.nonzero(np.abs(bed).max(axis=1) > 1e-5)[0]
    meta = dict(sr=SR, fps=FPS, spf=SPF, n_frames=N_FRAMES, n_total=N_TOTAL,
                audio_content_end_s=round(float(nz[-1] / SR), 3),
                bed_peak_dbfs=round(float(to_db(np.abs(bed).max())), 2),
                side_to_mid_db=round(float(to_db(np.sqrt(((bed[:, 0] - bed[:, 1]) ** 2).mean()) /
                                                np.sqrt(((bed[:, 0] + bed[:, 1]) ** 2).mean()))), 1))

    (ANALYSIS / "cuts.json").write_text(json.dumps({"frames": cuts, "seconds": [round(c / FPS, 4) for c in cuts]}, indent=1))
    (ANALYSIS / "beat_grid.json").write_text(json.dumps(bg, indent=1))
    (ANALYSIS / "vo_regions.json").write_text(json.dumps(v))
    (ANALYSIS / "key.json").write_text(json.dumps(k, indent=1))
    (ANALYSIS / "meta.json").write_text(json.dumps(meta, indent=1))
    np.savez_compressed(ANALYSIS / "curves.npz", **occ, **{f"video_{k}": val for k, val in vf.items()})

    # resumen legible por medio segundo (para el spotting)
    rows = []
    for i in range(0, N_FRAMES, FPS // 2):
        sl = slice(i, i + FPS // 2)
        rows.append({"t": round(i / FPS, 2),
                     **{b: round(float(occ[f"M_{b}"][sl].mean()), 1) for b in BANDS},
                     "side_mid": round(float(occ["S_mid"][sl].mean()), 1),
                     "luma": round(float(vf["luma"][sl].mean()), 3),
                     "motion": round(float(vf["motion"][sl].mean()), 4),
                     "motion_x": round(float(vf["motion_x"][sl].mean()), 2)})
    (ANALYSIS / "occupancy_halfsec.json").write_text(json.dumps(rows, indent=0))
    print("meta:", meta)


if __name__ == "__main__":
    main()
