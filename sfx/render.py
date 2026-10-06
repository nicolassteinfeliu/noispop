"""Cue sheet -> stems por bus (sin procesamiento de mezcla todavía).

Uso:  python -m sfx.render A      (o B)
Salida: out/render/<opción>/raw_<BUS>.npy (float32 [N_TOTAL, 2]) + cue_report.json
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml

from . import dsp
from .core import CUES, N_TOTAL, OUT, RECIPES, SR, load_all_recipes, resolve_time, stable_rng, to_db

BUSES = ["AMB", "VEH", "FOL", "DES", "SUB"]
EVENT_PEAK_DB = -6.0
BED_RMS_DB = -20.0


def load_shots():
    return yaml.safe_load((CUES / "shots.yaml").read_text())


def load_cues(option: str):
    doc = yaml.safe_load((CUES / f"option_{option.lower()}.yaml").read_text())
    return doc


def normalize(audio: np.ndarray, kind: str) -> np.ndarray:
    a = np.asarray(audio, dtype=np.float64)
    if kind == "bed":
        # RMS sobre la parte activa (ignora silencios de colas)
        e = np.sqrt((a ** 2).mean(axis=1))
        act = e > (e.max() * 0.01 + 1e-12)
        r = np.sqrt((a[act] ** 2).mean()) if act.any() else 0.0
        return a if r < 1e-12 else a * (10 ** (BED_RMS_DB / 20) / r)
    p = np.abs(a).max()
    return a if p < 1e-12 else a * (10 ** (EVENT_PEAK_DB / 20) / p)


def _recipe_hash(name: str) -> str:
    fn = RECIPES[name]["fn"]
    src = inspect.getsource(sys.modules[fn.__module__])
    return hashlib.sha1(src.encode()).hexdigest()[:12]


def render_recipe(name: str, dur: float, params: dict, seed_keys) -> tuple[np.ndarray, int, dict]:
    """Renderiza y normaliza una receta (con caché en disco)."""
    if name not in RECIPES:
        raise KeyError(f"receta no implementada: {name}")
    info = RECIPES[name]
    key = hashlib.sha1(json.dumps([name, dur, params, list(map(str, seed_keys)), _recipe_hash(name)],
                                  sort_keys=True, default=str).encode()).hexdigest()
    cache = OUT / "cache" / name / f"{key}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return z["audio"], int(z["sync"]), json.loads(str(z["meta"]))
    rng = stable_rng(*seed_keys)
    r = info["fn"](float(dur), rng, **(params or {}))
    audio = normalize(r.audio, info["kind"]).astype(np.float32)
    if not np.isfinite(audio).all():
        raise ValueError(f"{name}: NaN/Inf en la salida")
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, audio=audio, sync=r.sync_offset, meta=json.dumps(r.meta, default=str))
    return audio, r.sync_offset, r.meta


def apply_cue_shaping(a: np.ndarray, cue: dict, start_abs: int, until_abs: int | None) -> np.ndarray:
    a = a.astype(np.float64)
    n = len(a)
    # corte duro (until): recorta y aplica fade_out que termina en until
    fo = float(cue.get("fade_out", 0.01))
    fi = float(cue.get("fade_in", 0.005))
    if until_abs is not None:
        keep = max(0, min(n, until_abs - start_abs))
        a = a[:keep]
        n = len(a)
    a = dsp.fade(a, max(fi, 0.003), max(fo, 0.003))
    # curva de ganancia relativa
    gc = cue.get("gain_curve")
    if gc and n:
        pts = np.asarray(gc, dtype=np.float64)
        t = np.arange(n) / SR
        g = 10 ** (np.interp(t, pts[:, 0], pts[:, 1]) / 20)
        a *= g[:, None]
    # ancho y pan (balance de potencia constante)
    w = cue.get("width", 1.0)
    if w != 1.0:
        a = dsp.width(a, w)
    p = cue.get("pan", 0.0)
    if (np.isscalar(p) and p != 0.0) or not np.isscalar(p):
        if np.isscalar(p):
            pc = np.full(n, float(p))
        else:
            pts = np.asarray(p, dtype=np.float64)
            pc = np.interp(np.arange(n) / SR, pts[:, 0], pts[:, 1])
        gl, gr = dsp.pan_gains(pc)
        a[:, 0] *= gl * np.sqrt(2)
        a[:, 1] *= gr * np.sqrt(2)
    # envío extra de reverb
    send = cue.get("send")
    if send:
        a = dsp.reverb(a, send["preset"], float(send.get("db", -12)), dry=1.0, hp_send=float(send.get("hp", 0)))
    return a * 10 ** (float(cue.get("gain_db", 0.0)) / 20)


def _render_one(args):
    option, cue, cuts = args
    load_all_recipes()
    t0 = time.time()
    at = resolve_time(cue["at"], cuts)
    seed = (option, cue["id"], cue.get("seed", 0))
    audio, sync, meta = render_recipe(cue["recipe"], cue.get("dur", 1.0), cue.get("params", {}) or {}, seed)
    start = at - sync
    until = resolve_time(cue["until"], cuts) if cue.get("until") is not None else None
    shaped = apply_cue_shaping(audio, cue, start, until)
    dev = measure_sync(shaped, int(at - start), RECIPES[cue["recipe"]]["sync"])
    from .dynamics import protect_cue

    shaped = protect_cue(shaped, int(start), cue.get("vo_protect", "normal"))
    return dict(id=cue["id"], start=int(start), at=int(at), audio=shaped.astype(np.float32), meta=meta,
                secs=round(time.time() - t0, 2), sync_dev_frames=dev)


def measure_sync(a: np.ndarray, rel: int, kind: str):
    """Desvío (frames) entre el punto de sync declarado y el medido en el audio colocado."""
    if kind not in ("transient", "peak") or len(a) < 10:
        return None
    m = np.abs(np.asarray(a, np.float64)).mean(axis=1)
    if kind == "transient":
        w = int(0.002 * SR)
        e = np.convolve(m, np.ones(w) / w, mode="same")
        lo, hi = max(0, rel - int(0.12 * SR)), min(len(e) - 1, rel + int(0.12 * SR))
        if hi <= lo + 2:
            return None
        d = np.diff(e[lo:hi])
        pos = lo + int(np.argmax(d))
    else:
        w = int(0.02 * SR)
        e = np.sqrt(np.convolve(m ** 2, np.ones(w) / w, mode="same"))
        lo, hi = max(0, rel - int(0.4 * SR)), min(len(e), rel + int(0.4 * SR))
        if hi <= lo + 2:
            return None
        pos = lo + int(np.argmax(e[lo:hi]))
    return round((pos - rel) / (SR / 24), 2)


def render_option(option: str, workers: int = 2, only: set | None = None):
    load_all_recipes()
    doc = load_cues(option)
    cuts = load_shots()["cuts"]
    cues = [c for c in doc["cues"] if c.get("enabled", True) and (only is None or c["id"] in only)]
    missing = sorted({c["recipe"] for c in cues if c["recipe"] not in RECIPES})
    if missing:
        print("AVISO recetas faltantes (cues omitidos):", missing)
    cues = [c for c in cues if c["recipe"] in RECIPES]
    buses = {b: np.zeros((N_TOTAL, 2), np.float64) for b in BUSES}
    report = []
    jobs = [(option, c, cuts) for c in cues]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_render_one, jobs))
    by_id = {c["id"]: c for c in cues}
    cdir = OUT / "render" / option.upper() / "cues"
    if cdir.exists():
        for f in cdir.glob("*.npy"):
            f.unlink()
    cdir.mkdir(parents=True, exist_ok=True)
    for r in results:
        cue = by_id[r["id"]]
        bus = cue.get("bus", "DES")
        if bus not in buses:
            raise ValueError(f"{cue['id']}: bus desconocido {bus}")
        dsp.mix_into(buses[bus], r["audio"].astype(np.float64), r["start"])
        a = r["audio"]
        report.append(dict(id=r["id"], recipe=cue["recipe"], bus=bus, at_s=round(r["at"] / SR, 4),
                           start_s=round(r["start"] / SR, 4), end_s=round((r["start"] + len(a)) / SR, 4),
                           peak_dbfs=round(float(to_db(np.abs(a).max())), 1),
                           rms_dbfs=round(float(to_db(np.sqrt((a.astype(np.float64) ** 2).mean()))), 1),
                           vo_protect=cue.get("vo_protect", "normal"), sync=cue.get("sync"),
                           sync_type=RECIPES[cue["recipe"]]["sync"], sync_dev_frames=r["sync_dev_frames"],
                           render_s=r["secs"]))
        np.save(cdir / f"{r['id']}.npy", a)
    out = OUT / "render" / option.upper()
    out.mkdir(parents=True, exist_ok=True)
    for b, x in buses.items():
        np.save(out / f"raw_{b}.npy", x.astype(np.float32))
    (out / "cue_report.json").write_text(json.dumps(report, indent=1))
    return buses, report


def main():
    option = sys.argv[1].upper() if len(sys.argv) > 1 else "A"
    t = time.time()
    buses, report = render_option(option)
    print(f"opción {option}: {len(report)} cues renderizados en {time.time() - t:.1f}s")
    for b, x in buses.items():
        print(f"  {b}: pico {to_db(np.abs(x).max()):.1f} dBFS")


if __name__ == "__main__":
    main()
