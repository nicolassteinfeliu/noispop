"""Verificación automática de una opción ya renderizada y mezclada.

Uso:  python -m sfx.verify A
Escribe out/review/<opción>/verify.json y verify.md. Exit code 1 si hay errores duros.
"""
from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter

from .core import ANALYSIS, BED_WAV, CUES, FPS, N_TOTAL, OUT, SPF, SR, load_bed, read_wav, to_db
from .mix import STEM_NAMES, TRIM_DB, lufs

THIRD_OCT = [250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _band_energy_frames(x, centers, nper=2048, hop=1024):
    f, t, Z = signal.stft(x, SR, nperseg=nper, noverlap=nper - hop, boundary=None)
    P = np.abs(Z) ** 2
    out = []
    for c in centers:
        lo, hi = c / 2 ** (1 / 6), c * 2 ** (1 / 6)
        out.append(P[(f >= lo) & (f < hi)].sum(axis=0))
    return t, 10 * np.log10(np.array(out) + 1e-14)


def click_scan(x, exclude_s, margin=0.03):
    m = x.mean(axis=1)
    hf = signal.sosfilt(signal.butter(4, 6000, btype="highpass", fs=SR, output="sos"), m)
    w = 12
    k = len(hf) // w * w
    e = np.sqrt((hf[:k] ** 2).reshape(-1, w).mean(axis=1)) + 1e-9
    med = median_filter(e, size=81, mode="nearest") + 1e-9
    r = 20 * np.log10(e / med)
    idx = np.nonzero((r > 9) & (e > 10 ** (-60 / 20)))[0]
    times = []
    for i in idx:
        t = i * w / SR
        if times and t - times[-1] < 0.01:
            continue
        times.append(t)
    ex = np.array(exclude_s) if exclude_s else np.zeros(0)
    flagged = [round(t, 3) for t in times if not (len(ex) and np.min(np.abs(ex - t)) < margin)]
    return flagged


def verify(option: str) -> dict:
    option = option.upper()
    errors, warns = [], []
    pdir = OUT / "preview" / option
    sdir = OUT / "stems" / option
    rdir = OUT / "render" / option
    mixrep = json.loads((pdir / "mix_report.json").read_text())
    cuerep = json.loads((rdir / "cue_report.json").read_text())
    bed = load_bed().astype(np.float64)
    g = 10 ** (TRIM_DB / 20)
    res = {"option": option}

    # 1) bed intacto (prueba de nulo con archivos re-leídos)
    pre = read_wav(pdir / f"Geely_SD_Opcion{option}_preview.wav").astype(np.float64)
    tot = read_wav(sdir / f"Geely_SD_Op{option}_SFX_TOTAL_48k24.wav").astype(np.float64)
    if len(pre) != N_TOTAL or len(tot) != N_TOTAL:
        errors.append(f"longitud incorrecta: preview {len(pre)}, sfx {len(tot)} (esperado {N_TOTAL})")
    resid = pre - g * bed - g * tot
    res["null_test_max_abs"] = float(np.abs(resid).max())
    res["null_test_dbfs"] = round(float(to_db(np.abs(resid).max())), 1)
    if res["null_test_max_abs"] > 4 * 2 ** -23 + 1e-9:
        errors.append(f"prueba de nulo falla: residuo {res['null_test_dbfs']} dBFS")
    # tramo después de la música: el bed es cero exacto
    res["bed_sha256"] = _sha(BED_WAV)
    res["finite"] = bool(np.isfinite(pre).all())
    res["dc_db"] = round(float(to_db(abs(pre.mean()))), 1)

    # 2) stems: suma = SFX total
    ssum = np.zeros_like(tot)
    for b, name in STEM_NAMES.items():
        p = sdir / f"Geely_SD_Op{option}_{name}_48k24.wav"
        if p.exists():
            ssum += read_wav(p).astype(np.float64)
    res["stems_sum_vs_total_dbfs"] = round(float(to_db(np.abs(ssum - tot).max())), 1)
    if np.abs(ssum - tot).max() > 8 * 2 ** -23:
        warns.append("la suma de stems difiere del SFX total más que la cuantización")

    # 3) sincronía
    sync_rows = []
    for c in cuerep:
        s = c.get("sync") or {}
        row = {"id": c["id"], "at_s": c["at_s"]}
        if s.get("frame") is not None:
            dev = (c["at_s"] * SR - s["frame"] * SPF) / SPF
            row["declared_dev_frames"] = round(dev, 2)
            if abs(dev) > 1.0 + 1e-6:
                errors.append(f"{c['id']}: at={c['at_s']}s fuera de ±1 frame del frame {s['frame']}")
        if c.get("sync_dev_frames") is not None:
            row["measured_dev_frames"] = c["sync_dev_frames"]
            if abs(c["sync_dev_frames"]) > 1.0 and s.get("frame") is not None:
                warns.append(f"{c['id']}: el {c.get('sync_type')} medido cae a {c['sync_dev_frames']} frames del sync")
        sync_rows.append(row)
    res["sync"] = sync_rows

    # 4) loudness / picos
    res["loudness"] = {k: mixrep.get(k) for k in ("lufs_bed", "lufs_preview", "lufs_sfx_only", "tp_bed_dbtp",
                                                   "tp_preview_dbtp", "mp4_tp_dbtp", "mp4_lufs",
                                                   "mp4_audio_lag_samples", "sfx_limiter_active_ms",
                                                   "sfx_limiter_max_gr_db")}
    if mixrep.get("mp4_tp_dbtp", -99) > -0.95:
        warns.append(f"true peak del MP4 {mixrep.get('mp4_tp_dbtp')} dBTP > -1")
    if mixrep.get("mp4_audio_lag_samples", 0) not in (-1, 0, 1):
        errors.append(f"audio del MP4 desfasado {mixrep.get('mp4_audio_lag_samples')} samples")

    # 5) locución: SFX (mid) vs bed (mid) en tercios de octava 250 Hz-5 kHz durante la locución
    vo = json.loads((ANALYSIS / "vo_regions.json").read_text())["regions_raw"]
    sfx = pre - g * bed
    sm = sfx.mean(axis=1)
    bm = (g * bed).mean(axis=1)
    t, Es = _band_energy_frames(sm, THIRD_OCT)
    _, Eb = _band_energy_frames(bm, THIRD_OCT)
    in_vo = np.zeros(len(t), bool)
    for a, b in vo:
        in_vo |= (t >= a) & (t <= b)
    diff = Es[:, in_vo] - Eb[:, in_vo]
    active = Es[:, in_vo] > (Es.max() - 60)
    viol = (diff > -6) & active
    res["vo_masking"] = {"cells_checked": int(active.sum()),
                         "frac_sfx_within_6db_of_bed": round(float(viol.sum() / max(1, active.sum())), 4),
                         "frac_sfx_within_10db_of_bed": round(float(((diff > -10) & active).sum() / max(1, active.sum())), 4)}
    worst_t = t[in_vo][np.argsort(-viol.sum(axis=0))[:8]]
    res["vo_masking"]["worst_times_s"] = sorted(round(float(x), 2) for x in worst_t if viol.sum() > 0)
    if res["vo_masking"]["frac_sfx_within_6db_of_bed"] > 0.03:
        warns.append(f"SFX cerca del nivel del bed en la banda de voz en {100 * res['vo_masking']['frac_sfx_within_6db_of_bed']:.1f}% de celdas")

    # 6) graves: SFX 25-120 Hz en ventanas de bombo
    bg = json.loads((ANALYSIS / "beat_grid.json").read_text())
    sos = signal.butter(4, [25, 120], btype="band", fs=SR, output="sos")
    sl = signal.sosfilt(sos, sm)
    bl = signal.sosfilt(sos, bm)
    ratios = []
    for k in bg["kick_onsets_s"]:
        i0, i1 = int((k - 0.02) * SR), int((k + 0.08) * SR)
        es, eb = np.sqrt((sl[i0:i1] ** 2).mean()) + 1e-12, np.sqrt((bl[i0:i1] ** 2).mean()) + 1e-12
        ratios.append(20 * np.log10(es / eb))
    res["kick_windows_sfx_vs_bed_db"] = {"max": round(float(max(ratios)), 1), "median": round(float(np.median(ratios)), 1)}
    if max(ratios) > -6:
        warns.append(f"graves del SFX compiten con el bombo (máx {max(ratios):.1f} dB vs bed)")

    # 7) remate
    i0, i1 = int(46.83 * SR), int(49.70 * SR)
    res["stinger"] = {"lufs_46.83-49.70": round(lufs(pre[i0:i1]), 1),
                      "peak_dbfs": round(float(to_db(np.abs(pre[i0:i1]).max())), 1),
                      "after_cut_peak_dbfs": round(float(to_db(np.abs(pre[int(49.713 * SR):]).max() + 1e-12)), 1)}
    if res["stinger"]["after_cut_peak_dbfs"] > -70:
        warns.append("hay sonido después del corte a negro (49.708 s)")

    # 8) clics (excluye ±30 ms alrededor de cada sync y bordes de cue)
    excl = []
    for c in cuerep:
        excl += [c["at_s"], c["start_s"], c["end_s"]]
    res["click_candidates_s"] = click_scan(sfx, excl)[:40]
    if len(res["click_candidates_s"]) > 5:
        warns.append(f"{len(res['click_candidates_s'])} posibles clics fuera de transientes declarados")

    # 9) audibilidad por cue (fracción de celdas tiempo-frecuencia donde el cue supera bed-10 dB)
    cdir = rdir / "cues"
    aud = []
    centers = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 12500]
    for c in cuerep:
        p = cdir / f"{c['id']}.npy"
        if not p.exists():
            continue
        a = np.load(p).astype(np.float64)
        st = int(round(c["start_s"] * SR))
        i0, i1 = max(0, st), min(N_TOTAL, st + len(a))
        if i1 - i0 < 4096:
            continue
        seg = a[i0 - st:i1 - st].mean(axis=1) * g
        bseg = bm[i0:i1]
        _, Ec = _band_energy_frames(seg, centers, nper=2048, hop=1024)
        _, Ebb = _band_energy_frames(bseg, centers, nper=2048, hop=1024)
        act = Ec > (Ec.max() - 30)
        frac = float(((Ec - Ebb > -10) & act).sum() / max(1, act.sum()))
        aud.append({"id": c["id"], "audible_frac": round(frac, 2), "peak_dbfs": c["peak_dbfs"]})
    res["audibility"] = aud
    quiet = [x["id"] for x in aud if x["audible_frac"] < 0.05]
    if quiet:
        warns.append(f"cues prácticamente inaudibles (<5% celdas): {quiet[:12]}")

    res["errors"], res["warnings"] = errors, warns
    out = OUT / "review" / option
    out.mkdir(parents=True, exist_ok=True)
    (out / "verify.json").write_text(json.dumps(res, indent=1))
    md = [f"# Verificación opción {option}", "", f"- Errores: {len(errors)}", *[f"  - {e}" for e in errors],
          f"- Avisos: {len(warns)}", *[f"  - {w}" for w in warns], "",
          f"- Prueba de nulo (preview − trim·bed − trim·SFX): {res['null_test_dbfs']} dBFS",
          f"- Loudness: {res['loudness']}", f"- Locución: {res['vo_masking']}",
          f"- Bombo: {res['kick_windows_sfx_vs_bed_db']}", f"- Remate: {res['stinger']}",
          f"- Clics candidatos: {res['click_candidates_s']}", "", "## Audibilidad por cue",
          *[f"- {x['id']}: {x['audible_frac']:.2f}" for x in aud]]
    (out / "verify.md").write_text("\n".join(md))
    return res


def main():
    option = sys.argv[1] if len(sys.argv) > 1 else "A"
    r = verify(option)
    print(json.dumps({k: r[k] for k in ("errors", "warnings", "null_test_dbfs", "loudness", "vo_masking",
                                        "kick_windows_sfx_vs_bed_db", "stinger")}, indent=1))
    sys.exit(1 if r["errors"] else 0)


if __name__ == "__main__":
    main()
