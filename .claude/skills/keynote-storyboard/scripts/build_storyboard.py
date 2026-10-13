#!/usr/bin/env python3
"""Build a black-and-white storyboard page (artifact body) + a print HTML + a PDF
from data.json and a panels/ folder.

Usage: python3 build_storyboard.py <storyboard_dir> [--pdf]
  <storyboard_dir>/data.json      scenes + panels (see SKILL.md for the schema)
  <storyboard_dir>/panels/*.jpg   one image per panel (16:9)
Outputs in <storyboard_dir>/: index.html (artifact body, no doctype),
  print.html (full document) and storyboard.pdf (if --pdf and chromium is found).
"""
import json, sys, html, os, subprocess, shutil

def esc(s):
    return html.escape(s or "", quote=True)

CSS = r"""
/* Layout: one column of scenes; each scene = header strip + 2-up grid of panels.
   Print: landscape, scene starts on a new page, 2 panels per row, nothing split. */
:root{
  --paper:#f7f6f2; --ink:#161616; --ink-soft:#4a4a46; --line:#c9c6bd; --panel:#ffffff;
  --accent:#0b5fa5; --accent-ink:#ffffff; --sun:#f7e84b;
  --display:"Oswald","Arial Narrow",Impact,sans-serif;
  --body:"IBM Plex Sans","Helvetica Neue",Arial,sans-serif;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#17181a; --ink:#ededea; --ink-soft:#b3b3ad; --line:#3a3b3e; --panel:#1f2023;
  --accent:#6fb3ec; --accent-ink:#0b1a28; --sun:#e4d74a; color-scheme:dark } }
:root[data-theme="dark"]{
  --paper:#17181a; --ink:#ededea; --ink-soft:#b3b3ad; --line:#3a3b3e; --panel:#1f2023;
  --accent:#6fb3ec; --accent-ink:#0b1a28; --sun:#e4d74a; color-scheme:dark }
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.45;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding-block:28px 60px;padding-inline:20px}
h1,h2,h3{font-family:var(--display);font-weight:500;text-wrap:balance;margin:0;line-height:1.05}
.cover{display:grid;grid-template-columns:1fr;gap:18px;border-bottom:2px solid var(--ink);padding-bottom:22px;margin-bottom:26px}
.cover .eyebrow{font-family:var(--display);text-transform:uppercase;letter-spacing:.12em;font-size:13px;color:var(--ink-soft)}
.cover h1{font-size:clamp(40px,7vw,78px);text-transform:uppercase;letter-spacing:.01em}
.cover .sub{font-size:17px;color:var(--ink-soft);max-width:68ch}
.meta{display:flex;flex-wrap:wrap;gap:10px 28px;font-size:14px}
.meta b{font-family:var(--display);font-weight:500;text-transform:uppercase;letter-spacing:.08em;font-size:12px;color:var(--ink-soft);display:block}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px 24px;margin-top:6px}
.legend div{min-width:0;font-size:14px}
.legend b{color:var(--accent)}
.index{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.index a{font-family:var(--display);text-decoration:none;color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:14px}
.index a:hover,.index a:focus-visible{border-color:var(--accent);color:var(--accent);outline:none}
.scene{margin-top:34px}
.scene-head{display:grid;grid-template-columns:auto 1fr auto;gap:14px 20px;align-items:end;border-top:2px solid var(--ink);padding-top:12px;margin-bottom:14px}
.scene-num{font-family:var(--display);font-size:52px;line-height:.9;color:var(--accent)}
.scene-head h2{font-size:30px;text-transform:uppercase;letter-spacing:.02em}
.scene-head .tc{font-family:var(--display);font-size:20px;color:var(--ink-soft);font-variant-numeric:tabular-nums}
.scene-notes{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:6px 22px;font-size:14px;color:var(--ink-soft)}
.scene-notes .loc{color:var(--ink);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}
@media (max-width:760px){.grid{grid-template-columns:1fr}.scene-head{grid-template-columns:auto 1fr}.scene-head .tc{grid-column:2}}
.panel{background:var(--panel);border:1px solid var(--line);min-width:0;display:flex;flex-direction:column;break-inside:avoid;page-break-inside:avoid}
.frame{position:relative;aspect-ratio:16/9;max-width:100%;background:#fff;border-bottom:1px solid var(--line);overflow:hidden}
.frame img{display:block;width:100%;height:100%;object-fit:cover;filter:grayscale(1)}
.frame .num{position:absolute;left:0;top:0;background:var(--ink);color:var(--paper);font-family:var(--display);font-size:16px;padding:3px 10px;letter-spacing:.06em}
.frame .shot{position:absolute;right:0;bottom:0;background:var(--accent);color:var(--accent-ink);font-family:var(--display);font-size:13px;text-transform:uppercase;letter-spacing:.08em;padding:3px 10px}
.endcard{position:absolute;left:30.5%;top:31%;width:39%;height:31%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;color:#111;text-align:center}
.endcard .logo{font-family:var(--body);font-weight:700;font-size:clamp(22px,4.5vw,40px);letter-spacing:-.02em;line-height:1}
.endcard .claim{font-family:var(--display);font-size:clamp(11px,1.6vw,16px);text-transform:uppercase;letter-spacing:.1em}
.txt{padding:12px 14px 14px;display:grid;grid-template-columns:1fr;gap:7px;font-size:14px}
.txt p{margin:0;min-width:0}
.txt .k{font-family:var(--display);text-transform:uppercase;letter-spacing:.1em;font-size:11.5px;color:var(--accent);display:block;margin-bottom:1px}
.txt .action{font-size:15px;color:var(--ink)}
.txt .audio{border-top:1px dashed var(--line);padding-top:7px;color:var(--ink-soft)}
.foot{margin-top:40px;border-top:1px solid var(--line);padding-top:12px;font-size:13px;color:var(--ink-soft)}
@media print{
  @page{size:A4 portrait;margin:10mm}
  :root{--paper:#fff;--panel:#fff;--ink:#111;--ink-soft:#444;--line:#bbb;--accent:#0b5fa5;--accent-ink:#fff}
  body{font-size:11.5px}
  .wrap{max-width:none;padding:0}
  .cover{break-after:page;page-break-after:always;border:0;min-height:250mm;display:flex;flex-direction:column;justify-content:center}
  .cover h1{font-size:56pt}
  .index{display:none}
  .scene{break-before:page;page-break-before:always;margin-top:0}
  .scene-head{margin-bottom:8px;padding-top:6px}
  .scene-num{font-size:34px}
  .scene-head h2{font-size:22px}
  .scene-head .tc{font-size:15px}
  .scene-notes{font-size:10.5px}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px 10px}
  .panel{break-inside:avoid;page-break-inside:avoid}
  .txt{font-size:10.5px;padding:7px 9px 9px;gap:4px}
  .txt .action{font-size:11px}
  .txt .k{font-size:9px}
  .frame img{filter:none}
  a{color:inherit;text-decoration:none}
}
"""

def render(data, body_only):
    s = []
    if not body_only:
        s.append('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">')
    s.append(f'<title>{esc(data["title"])}</title>')
    s.append('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,600;1,400&display=swap">')
    s.append(f'<style>{CSS}</style>')
    if not body_only:
        s.append('</head><body>')
    s.append('<div class="wrap">')
    # cover
    s.append('<header class="cover">')
    s.append(f'<div class="eyebrow">Storyboard · blanco y negro · {esc(data["spot"])}</div>')
    s.append(f'<h1>{esc(data["title"])}</h1>')
    s.append(f'<p class="sub">Resumen visual de la historia para presentar antes de filmar. Fuente: {esc(data["source"])}. Cada viñeta lleva la acción, el proceso del efecto tal como está descrito en las notas, la cámara y el audio o sobreimpreso.</p>')
    s.append('<div class="meta">')
    for c in data.get("cast", []):
        s.append(f'<div><b>{esc(c["name"])}</b>{esc(c["desc"])}</div>')
    total = sum(len(sc["panels"]) for sc in data["scenes"])
    s.append(f'<div><b>Láminas</b>{total} viñetas en {len(data["scenes"])} escenas</div>')
    s.append('</div>')
    if data.get("legend"):
        s.append('<div class="legend">')
        for l in data["legend"]:
            s.append(f'<div><b>{esc(l["k"])}.</b> {esc(l["v"])}</div>')
        s.append('</div>')
    s.append('<nav class="index">')
    for sc in data["scenes"]:
        s.append(f'<a href="#escena{sc["num"]}">{sc["num"]} · {esc(sc["name"])}</a>')
    s.append('</nav></header>')
    # scenes
    n = 0
    for sc in data["scenes"]:
        s.append(f'<section class="scene" id="escena{sc["num"]}">')
        s.append('<div class="scene-head">')
        s.append(f'<div class="scene-num">{sc["num"]}</div><h2>{esc(sc["name"])}</h2><div class="tc">{esc(sc.get("tc",""))}</div>')
        notes = []
        if sc.get("loc"): notes.append(f'<span class="loc">{esc(sc["loc"])}</span>')
        if sc.get("refs"): notes.append(f'<span>Referencias: {esc(sc["refs"])}</span>')
        if notes: s.append('<div class="scene-notes">' + ''.join(notes) + '</div>')
        s.append('</div><div class="grid">')
        for p in sc["panels"]:
            n += 1
            s.append('<article class="panel">')
            s.append(f'<div class="frame"><img src="panels/{esc(p["img"])}" alt="Viñeta {n}: {esc(p["shot"])}" loading="lazy">')
            s.append(f'<span class="num">{n:02d}</span><span class="shot">{esc(p["shot"])}</span>')
            if p.get("endcard"):
                s.append(f'<div class="endcard"><div class="logo">{esc(data["brand"].lower())}</div><div class="claim">Eso que quieres, hoy.</div></div>')
            s.append('</div><div class="txt">')
            s.append(f'<p class="action"><span class="k">Acción</span>{esc(p["action"])}</p>')
            s.append(f'<p><span class="k">Efecto / proceso</span>{esc(p["fx"])}</p>')
            s.append(f'<p><span class="k">Cámara</span>{esc(p["cam"])}</p>')
            s.append(f'<p class="audio"><span class="k">Audio / sobreimpreso</span>{esc(p["audio"])}</p>')
            s.append('</div></article>')
        s.append('</div></section>')
    s.append(f'<footer class="foot">Storyboard de previsualización. Dibujos en blanco y negro generados a partir de las notas y referencias del Keynote; los looks, precios y locaciones finales se definen en producción.</footer>')
    s.append('</div>')
    if not body_only:
        s.append('</body></html>')
    return '\n'.join(s)

def main():
    d = sys.argv[1]
    data = json.load(open(os.path.join(d, 'data.json'), encoding='utf-8'))
    open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(render(data, True))
    open(os.path.join(d, 'print.html'), 'w', encoding='utf-8').write(render(data, False))
    print('wrote index.html and print.html')
    if '--pdf' in sys.argv:
        chrome = None
        for c in ['/opt/pw-browsers/chromium/chrome', 'chromium', 'chromium-browser', 'google-chrome']:
            if os.path.exists(c) or shutil.which(c):
                chrome = c if os.path.exists(c) else shutil.which(c); break
        if not chrome:
            import glob
            g = glob.glob('/opt/pw-browsers/chromium*/chrome-linux*/chrome') + glob.glob('/opt/pw-browsers/chromium*/chrome')
            chrome = g[0] if g else None
        if not chrome:
            print('chromium not found; skipped PDF'); return
        out = os.path.join(d, 'storyboard.pdf')
        cmd = [chrome, '--headless=new', '--no-sandbox', '--disable-gpu', '--run-all-compositor-stages-before-draw',
               '--virtual-time-budget=20000', '--no-pdf-header-footer', f'--print-to-pdf={out}',
               'file://' + os.path.abspath(os.path.join(d, 'print.html'))]
        subprocess.run(cmd, check=True, timeout=180)
        print('wrote', out, os.path.getsize(out))

if __name__ == '__main__':
    main()

# ---------- Classic storyboard: 6 panels per landscape page ----------
CLASSIC_CSS = r"""
:root{--ink:#111;--soft:#555;--line:#999;--accent:#0b5fa5;--display:"Oswald","Arial Narrow",sans-serif;--body:"IBM Plex Sans","Helvetica Neue",Arial,sans-serif}
*{box-sizing:border-box}body{margin:0;font-family:var(--body);color:var(--ink);background:#fff;font-size:10.5px;line-height:1.35}
@page{size:A4 landscape;margin:8mm}
.page{width:281mm;height:194mm;padding:4mm 4mm 0;display:flex;flex-direction:column;break-after:page;page-break-after:always;margin:0 auto}
.page:last-child{break-after:auto;page-break-after:auto}
.head{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1.5px solid var(--ink);padding-bottom:2mm;margin-bottom:3mm;font-family:var(--display);text-transform:uppercase;letter-spacing:.08em}
.head .t{font-size:16px}.head .s{font-size:10px;color:var(--soft)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(2,1fr);gap:4mm 5mm;flex:1;min-height:0}
.cell{display:flex;flex-direction:column;min-height:0}
.fr{position:relative;aspect-ratio:16/9;width:100%;border:1.2px solid var(--ink);overflow:hidden;background:#fff}
.fr img{width:100%;height:100%;object-fit:cover;display:block}
.fr .n{position:absolute;left:0;top:0;background:var(--ink);color:#fff;font-family:var(--display);font-size:11px;padding:1px 6px}
.fr .sh{position:absolute;right:0;bottom:0;background:var(--accent);color:#fff;font-family:var(--display);font-size:8.5px;text-transform:uppercase;letter-spacing:.06em;padding:1px 6px}
.endcard{position:absolute;left:30.5%;top:31%;width:39%;height:31%;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#111;text-align:center}
.endcard .logo{font-weight:700;font-size:20px;letter-spacing:-.02em;line-height:1}.endcard .claim{font-family:var(--display);font-size:8px;text-transform:uppercase;letter-spacing:.1em}
.cap{padding-top:1.5mm;display:grid;grid-template-columns:1fr;gap:2px;overflow:hidden}
.cap .sc{font-family:var(--display);text-transform:uppercase;letter-spacing:.08em;font-size:8.5px;color:var(--accent)}
.cap .a{font-size:10.5px}.cap .d{font-size:10px;color:var(--soft);border-top:1px dashed var(--line);padding-top:2px}
.foot{font-size:8.5px;color:var(--soft);padding:2mm 0;text-align:right;font-family:var(--display);letter-spacing:.08em;text-transform:uppercase}
"""

def render_classic(data):
    items = []
    n = 0
    for sc in data["scenes"]:
        for p in sc["panels"]:
            n += 1; items.append((n, sc, p))
    pages = [items[i:i+6] for i in range(0, len(items), 6)]
    s = ['<!doctype html><html lang="es"><head><meta charset="utf-8">', f'<title>{esc(data["title"])} · clásico</title>',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500&family=IBM+Plex+Sans:wght@400;600&display=swap">',
         f'<style>{CLASSIC_CSS}</style></head><body>']
    for k, pg in enumerate(pages, 1):
        s.append('<section class="page"><div class="head">')
        s.append(f'<span class="t">{esc(data["title"])}</span><span class="s">{esc(data["spot"])} · página {k}/{len(pages)}</span></div><div class="grid">')
        for n, sc, p in pg:
            s.append('<div class="cell"><div class="fr">')
            s.append(f'<img src="panels/{esc(p["img"])}" alt=""><span class="n">{n:02d}</span><span class="sh">{esc(p["shot"])}</span>')
            if p.get("endcard"):
                s.append(f'<div class="endcard"><div class="logo">{esc(data["brand"].lower())}</div><div class="claim">Eso que quieres, hoy.</div></div>')
            s.append('</div><div class="cap">')
            s.append(f'<span class="sc">Esc. {sc["num"]} · {esc(sc["name"])} · {esc(sc.get("tc",""))}</span>')
            s.append(f'<span class="a">{esc(p["action"])}</span>')
            s.append(f'<span class="d">{esc(p["audio"])}</span></div></div>')
        s.append('</div><div class="foot">Storyboard · blanco y negro · previsualización</div></section>')
    s.append('</body></html>')
    return '\n'.join(s)

if __name__ == '__main__' and '--classic' in sys.argv:
    d = sys.argv[1]
    data = json.load(open(os.path.join(d, 'data.json'), encoding='utf-8'))
    open(os.path.join(d, 'classic.html'), 'w', encoding='utf-8').write(render_classic(data))
    import glob
    g = glob.glob('/opt/pw-browsers/chromium*/chrome-linux*/chrome')
    if g:
        out = os.path.join(d, 'storyboard_clasico.pdf')
        subprocess.run([g[0], '--headless=new', '--no-sandbox', '--disable-gpu', '--virtual-time-budget=20000', '--no-pdf-header-footer',
                        f'--print-to-pdf={out}', 'file://' + os.path.abspath(os.path.join(d, 'classic.html'))], check=True, timeout=180, capture_output=True)
        print('wrote', out)
