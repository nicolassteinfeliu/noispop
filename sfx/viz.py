"""Material de revisión visual (para críticos que no pueden escuchar).

Uso:  python -m sfx.viz A
Genera en out/review/<opción>/:
  overview.png      — espectrogramas bed | SFX | final de todo el spot con cortes, locución y bloques de cues
  sec_XX.png        — por sección: fotogramas cada 0.5 s alineados sobre espectrograma SFX y final
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import signal

from .core import ANALYSIS, FPS, N_TOTAL, OUT, PICTURE, SR, load_bed
from .render import load_shots

BUS_COLORS = {"AMB": (80, 170, 255), "VEH": (255, 170, 60), "FOL": (120, 230, 120), "DES": (230, 110, 230),
              "SUB": (255, 70, 70)}


def _spec_img(x, width, height, fmin=30, fmax=20000, db_range=80, ref_db=None):
    m = np.asarray(x, np.float64)
    if m.ndim == 2:
        m = m.mean(axis=1)
    nper = 2048
    hop = max(64, len(m) // width)
    f, t, Z = signal.stft(m, SR, nperseg=nper, noverlap=max(0, nper - hop), boundary=None)
    S = 20 * np.log10(np.abs(Z) + 1e-10)
    ref = S.max() if ref_db is None else ref_db
    S = S - ref
    fl = np.geomspace(fmin, fmax, height)
    rows = np.array([np.interp(fl, f, S[:, j]) for j in range(S.shape[1])]).T
    img = np.clip((rows + db_range) / db_range, 0, 1)[::-1]
    c = np.stack([np.clip(1.6 * img, 0, 1), np.clip(1.6 * img - 0.5, 0, 1) ** 1.2,
                  np.clip(0.6 * img + 0.4 * img ** 3, 0, 1)], axis=-1)
    return Image.fromarray((c * 255).astype(np.uint8)).resize((width, height)), ref


def _freq_labels(d, x0, y0, h, fmin=30, fmax=20000):
    for fr in (100, 1000, 5000, 10000):
        y = y0 + h - 1 - int(np.log(fr / fmin) / np.log(fmax / fmin) * (h - 1))
        d.text((x0 + 2, y - 6), f"{fr if fr < 1000 else str(fr // 1000) + 'k'}", fill=(140, 210, 255))


def load_mix(option):
    pdir = OUT / "preview" / option
    pre = np.load(pdir / "premaster_f32.npy").astype(np.float64)
    bed = load_bed().astype(np.float64) * 10 ** (-1.5 / 20)
    sfx = pre - bed
    return bed, sfx, pre


def overview(option, width=2400):
    bed, sfx, pre = load_mix(option)
    shots = load_shots()
    cuts = shots["cuts"]
    vo = json.loads((ANALYSIS / "vo_regions.json").read_text())["regions_raw"]
    rep = json.loads((OUT / "render" / option / "cue_report.json").read_text())
    h = 200
    band = 70
    W = width
    H = 30 + band + 3 * (h + 18)
    im = Image.new("RGB", (W, H), (10, 10, 14))
    d = ImageDraw.Draw(im)
    dur = N_TOTAL / SR

    def X(t):
        return int(t / dur * (W - 1))

    d.text((6, 4), f"Opcion {option} - arriba: cues por bus (AMB azul, VEH naranja, FOL verde, DES magenta, SUB rojo); "
                   f"barra gris = locucion (VO); lineas blancas = cortes", fill=(230, 230, 230))
    y = 22
    for a, b in vo:
        d.rectangle([X(a), y, X(b), y + 5], fill=(110, 110, 110))
    lanes = {b: i for i, b in enumerate(BUS_COLORS)}
    for c in rep:
        ln = lanes.get(c["bus"], 0)
        yy = y + 9 + ln * 12
        d.rectangle([X(max(0, c["start_s"])), yy, X(min(dur, c["end_s"])), yy + 9], outline=BUS_COLORS[c["bus"]])
        d.line([X(c["at_s"]), yy, X(c["at_s"]), yy + 9], fill=(255, 255, 255))
    y = 30 + band
    _, ref = _spec_img(pre, 50, 50)
    for lab, x in (("BED (musica+locucion, -1.5 dB)", bed), ("SOLO SFX", sfx), ("FINAL", pre)):
        sp, _ = _spec_img(x, W, h, ref_db=ref)
        im.paste(sp, (0, y + 16))
        d.text((6, y + 2), lab, fill=(255, 255, 255))
        _freq_labels(d, 0, y + 16, h)
        for cf in cuts:
            d.line([X(cf / FPS), y + 16, X(cf / FPS), y + 16 + 6], fill=(255, 255, 255))
        y += h + 18
    for s in range(0, int(dur) + 1, 2):
        d.text((X(s) + 2, H - 12), str(s), fill=(255, 255, 0))
    out = OUT / "review" / option
    out.mkdir(parents=True, exist_ok=True)
    im.save(out / "overview.png")
    return out / "overview.png"


def _frames(t0, t1, step=0.5, w=160):
    """Fotogramas (PIL) cada `step` s entre t0 y t1."""
    ts = np.arange(t0, t1 - 1e-6, step)
    imgs = []
    for t in ts:
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(PICTURE), "-frames:v", "1",
                              "-vf", f"scale={w}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True).stdout
        from io import BytesIO

        imgs.append(Image.open(BytesIO(raw)).convert("RGB"))
    return ts, imgs


def sections(option, sec_len=8.0, width=1600):
    bed, sfx, pre = load_mix(option)
    rep = json.loads((OUT / "render" / option / "cue_report.json").read_text())
    shots = load_shots()
    cuts = [c / FPS for c in shots["cuts"]]
    vo = json.loads((ANALYSIS / "vo_regions.json").read_text())["regions_raw"]
    dur = N_TOTAL / SR
    out = OUT / "review" / option
    out.mkdir(parents=True, exist_ok=True)
    _, ref = _spec_img(pre, 50, 50)
    paths = []
    starts = np.arange(0, dur, sec_len)
    for k, t0 in enumerate(starts):
        t1 = min(dur, t0 + sec_len)
        ts, frames = _frames(t0, t1, 0.5, w=int(width / ((t1 - t0) / 0.5)))
        fh = frames[0].height if frames else 60
        h = 170
        H = fh + 26 + 60 + 2 * (h + 16) + 16
        im = Image.new("RGB", (width, H), (10, 10, 14))
        d = ImageDraw.Draw(im)

        def X(t):
            return int((t - t0) / (t1 - t0) * (width - 1))

        for t, fr in zip(ts, frames):
            im.paste(fr, (X(t), 0))
            d.text((X(t) + 2, fh + 1), f"{t:.1f}", fill=(255, 255, 0))
        y = fh + 14
        for a, b in vo:
            if b > t0 and a < t1:
                d.rectangle([X(max(a, t0)), y, X(min(b, t1)), y + 5], fill=(110, 110, 110))
        d.text((width - 260, y - 2), "gris = locucion (VO)", fill=(150, 150, 150))
        y += 9
        # cues
        lanes = {b: i for i, b in enumerate(BUS_COLORS)}
        for c in rep:
            if c["end_s"] < t0 or c["start_s"] > t1:
                continue
            yy = y + lanes.get(c["bus"], 0) * 11
            d.rectangle([X(max(t0, c["start_s"])), yy, X(min(t1, c["end_s"])), yy + 8], outline=BUS_COLORS[c["bus"]])
            if t0 <= c["at_s"] <= t1:
                d.line([X(c["at_s"]), yy, X(c["at_s"]), yy + 8], fill=(255, 255, 255))
                d.text((X(c["at_s"]) + 3, yy - 1), c["id"][:18], fill=BUS_COLORS[c["bus"]])
        y += 60
        i0, i1 = int(t0 * SR), int(t1 * SR)
        for lab, x in (("SOLO SFX", sfx[i0:i1]), ("FINAL", pre[i0:i1])):
            sp, _ = _spec_img(x, width, h, ref_db=ref)
            im.paste(sp, (0, y + 14))
            d.text((6, y), lab, fill=(255, 255, 255))
            _freq_labels(d, 0, y + 14, h)
            for c in cuts:
                if t0 <= c <= t1:
                    d.line([X(c), y + 14, X(c), y + 14 + h], fill=(255, 255, 255))
            y += h + 16
        p = out / f"sec_{k:02d}_{t0:04.1f}-{t1:04.1f}.png"
        im.save(p)
        paths.append(p)
    return paths


def main():
    option = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()
    print(overview(option))
    for p in sections(option):
        print(p)


if __name__ == "__main__":
    main()
