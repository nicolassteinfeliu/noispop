"""Mezcla de una opción: buses -> stems procesados -> preview (bed + SFX) -> MP4.

Uso:  python -m sfx.mix A [--no-mp4]

Cadena:
  bed (intocable) ──────────────── × g (trim estático global) ──────────────┐
  buses crudos -> limpieza (DC, HP 30 Hz) -> graves de no-SUB respiran con el  │
  bombo -> SUB: LP 100 Hz + duck por bombo -> Σ = SFX -> limitador SOLO del SFX │
  (gana igual en todos los stems) ────────── × g ─────────────────────────────(+)-> premaster -> WAV/MP4
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal

from . import dsp
from .core import N_TOTAL, OUT, PICTURE, SR, load_bed, to_db, write_wav
from .dynamics import headroom_limiter, kick_duck, kick_env, true_peak
from .render import BUSES

TRIM_DB = -1.5
CEILING_DB = -1.0
STEM_NAMES = {"AMB": "AMBIENTES", "VEH": "VEHICULO", "FOL": "FOLEY", "DES": "DISENO", "SUB": "SUB"}


def lufs(x: np.ndarray) -> float:
    import pyloudnorm as pyln

    meter = pyln.Meter(SR)
    x = np.asarray(x, np.float64)
    if np.abs(x).max() < 1e-9:
        return -120.0
    return float(meter.integrated_loudness(x))


def short_term_lufs(x: np.ndarray, win: float = 3.0, hop: float = 0.5):
    import pyloudnorm as pyln

    meter = pyln.Meter(SR, block_size=0.4)
    out = []
    w, h = int(win * SR), int(hop * SR)
    for i in range(0, len(x) - w + 1, h):
        seg = x[i:i + w]
        out.append(round(float(meter.integrated_loudness(seg)) if np.abs(seg).max() > 1e-7 else -120.0, 1))
    return out


def process_buses(raw: dict) -> dict:
    """Procesamiento de bus (no toca el bed)."""
    k = kick_env()
    out = {}
    for b, x in raw.items():
        x = np.asarray(x, np.float64)
        if np.abs(x).max() < 1e-9:
            out[b] = x
            continue
        x = dsp.dc_block(x, 12.0)
        if b == "SUB":
            x = signal.sosfiltfilt(dsp.butter_sos(4, 100, "lowpass"), x, axis=0)
            x = signal.sosfiltfilt(dsp.butter_sos(2, 25, "highpass"), x, axis=0)
            x = kick_duck(x, depth_db=10.0)
        else:
            # graves (<120 Hz) de los buses normales respiran con el bombo (división complementaria exacta)
            low = signal.sosfiltfilt(dsp.butter_sos(4, 120, "lowpass"), x, axis=0)
            high = x - low
            g = 10 ** (-8.0 * np.clip(k * 1.5, 0, 1) / 20)
            x = high + low * g[:, None]
        out[b] = x
    return out


def mix_option(option: str, make_mp4: bool = True) -> dict:
    option = option.upper()
    rdir = OUT / "render" / option
    raw = {b: np.load(rdir / f"raw_{b}.npy").astype(np.float64) for b in BUSES}
    bed = load_bed().astype(np.float64)
    g = 10 ** (TRIM_DB / 20)

    buses = process_buses(raw)
    # corte a negro (frame 1193): nada de SFX después; rampa de 5 ms que termina en el corte
    cut = 1193 * 2000
    ramp = np.ones(N_TOTAL)
    k = int(0.005 * SR)
    ramp[cut - k:cut] = np.cos(np.linspace(0, np.pi / 2, k)) ** 2
    ramp[cut:] = 0.0
    buses = {b: x * ramp[:, None] for b, x in buses.items()}
    sfx = sum(buses.values())
    L = headroom_limiter(g * bed, g * sfx, ceiling_db=CEILING_DB)
    stems = {b: x * L[:, None] for b, x in buses.items()}
    sfx_l = sum(stems.values())
    premaster = g * bed + g * sfx_l

    pdir = OUT / "preview" / option
    sdir = OUT / "stems" / option
    pdir.mkdir(parents=True, exist_ok=True)
    sdir.mkdir(parents=True, exist_ok=True)

    wav = pdir / f"Geely_SD_Opcion{option}_preview.wav"
    write_wav(wav, premaster, "PCM_24")
    np.save(pdir / "premaster_f32.npy", premaster.astype(np.float32))
    np.save(pdir / "limiter_gain.npy", L.astype(np.float32))

    # stems a nivel de la mezcla original a 0 dB (sin el trim): bed + Σ stems = mezcla completa
    for b, x in stems.items():
        if np.abs(x).max() > 1e-7:
            write_wav(sdir / f"Geely_SD_Op{option}_{STEM_NAMES[b]}_48k24.wav", x, "PCM_24")
    write_wav(sdir / f"Geely_SD_Op{option}_SFX_TOTAL_48k24.wav", sfx_l, "PCM_24")

    lim_active = L < 0.999
    rep = {
        "option": option,
        "trim_db": TRIM_DB,
        "ceiling_dbtp": CEILING_DB,
        "lufs_bed": round(lufs(bed), 2),
        "lufs_preview": round(lufs(premaster), 2),
        "lufs_sfx_only": round(lufs(sfx_l), 2),
        "tp_bed_dbtp": round(float(to_db(true_peak(bed))), 2),
        "tp_preview_dbtp": round(float(to_db(true_peak(premaster))), 2),
        "sfx_limiter_active_ms": round(float(lim_active.sum() / SR * 1000), 1),
        "sfx_limiter_max_gr_db": round(float(-to_db(L.min())), 2),
        "stems_peak_dbfs": {b: round(float(to_db(np.abs(x).max())), 1) for b, x in stems.items()},
        "stems_lufs": {b: round(lufs(x), 1) for b, x in stems.items() if np.abs(x).max() > 1e-7},
        "st_lufs_bed": short_term_lufs(g * bed),
        "st_lufs_preview": short_term_lufs(premaster),
    }
    if make_mp4:
        mp4 = pdir / f"Geely_SD_Opcion{option}_preview.mp4"
        mux(wav, mp4, title=f"Opcion {option}")
        rep["mp4"] = str(mp4)
        rep.update(check_mp4(mp4, premaster))
    (pdir / "mix_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def mux(wav: Path, mp4: Path, title: str = ""):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(PICTURE), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(SR), "-movflags", "+faststart",
           "-metadata:s:a:0", f"title={title}", "-shortest", str(mp4)]
    subprocess.run(cmd, check=True)


def decode_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-ac", "2",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def check_mp4(mp4: Path, ref: np.ndarray) -> dict:
    """Alineación y picos del audio ya codificado en AAC (lo que realmente se escucha)."""
    y = decode_audio(mp4)
    a = ref[SR * 5:SR * 15, 0]
    best = (0, -1.0)
    for lag in range(-3000, 3001):
        b = y[SR * 5 + lag:SR * 15 + lag, 0]
        if len(b) != len(a):
            continue
        c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        if c > best[1]:
            best = (lag, c)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration,start_time",
                            "-of", "json", str(mp4)], capture_output=True, text=True).stdout
    return {"mp4_audio_lag_samples": best[0], "mp4_corr": round(best[1], 5),
            "mp4_tp_dbtp": round(float(to_db(true_peak(y))), 2),
            "mp4_lufs": round(lufs(y), 2), "mp4_streams": json.loads(probe).get("streams", [])}


def main():
    option = sys.argv[1] if len(sys.argv) > 1 else "A"
    rep = mix_option(option, make_mp4="--no-mp4" not in sys.argv)
    short = {k: v for k, v in rep.items() if not k.startswith("st_lufs")}
    print(json.dumps(short, indent=1))


if __name__ == "__main__":
    main()
