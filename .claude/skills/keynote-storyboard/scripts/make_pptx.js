// Usage: node make_pptx.js <dir with data.json + panels/> <out.pptx>
// Deck in the client's reference format: dark blue background, 4x3 grid of 16:9 frames,
// direction note above each frame, dialogue/LOC below in bold. data.deck_title overrides the slide title.
const pptxgen = require('pptxgenjs'); const fs = require('fs'); const path = require('path');
const dir = process.argv[2] || '.'; const out = process.argv[3] || 'storyboard.pptx';
const data = JSON.parse(fs.readFileSync(path.join(dir, 'data.json'), 'utf8'));
const pres = new pptxgen(); pres.layout = 'LAYOUT_WIDE'; pres.title = data.title;
pres.theme = { headFontFace: 'Arial', bodyFontFace: 'Arial' };
const esc = s => String(s || '');
const items = []; let n = 0;
for (const sc of data.scenes) for (const p of sc.panels) items.push({ n: ++n, sc, p });
const pages = []; for (let i = 0; i < items.length; i += 12) pages.push(items.slice(i, i + 12));
const COLS = 4, ROWS = 3, X0 = 0.75, Y0 = 0.8, GX = 0.3, GY = 0.0;
const W = (13.333 - 2 * X0 - (COLS - 1) * GX) / COLS, H = W * 9 / 16, NOTE = 0.28, DLG = 0.3;
const short = t => { const m = String(t||'').match(/^[^.]*[.]?/); let r = (m ? m[0] : t).trim(); return r.length > 95 ? r.slice(0, 92).replace(/\s+\S*$/, '') + '…' : r; };
const ROWH = NOTE + H + DLG + GY;
pages.forEach((pg, k) => {
  const sl = pres.addSlide(); sl.background = { path: fs.existsSync(path.join(dir, 'bg_blue.jpg')) ? path.join(dir, 'bg_blue.jpg') : path.join(__dirname, '..', 'assets', 'bg_blue.jpg') };
  sl.addText(`${(data.deck_title || data.title.replace(' Storyboard', '')).toUpperCase()} — ${k + 1}/${pages.length}`, { x: 0.6, y: 0.18, w: 9, h: 0.55, fontSize: 26, bold: true, color: 'FFFFFF', isTextBox: true, margin: 0 });
  sl.addText(esc(data.spot), { x: 8.2, y: 0.3, w: 4.5, h: 0.35, fontSize: 8, color: 'C9D3F0', align: 'right', isTextBox: true, margin: 0 });
  pg.forEach((it, i) => {
    const col = i % COLS, row = Math.floor(i / COLS);
    const x = X0 + col * (W + GX), y = Y0 + row * ROWH;
    sl.addText(`${String(it.n).padStart(2, '0')} · ${short(it.p.action)}`, { x, y, w: W, h: NOTE, fontSize: 7.5, color: 'FFFFFF', align: 'center', valign: 'bottom', isTextBox: true, margin: 0, fit: 'shrink' });
    sl.addImage({ path: path.join(dir, 'panels', it.p.img), x, y: y + NOTE + 0.03, w: W, h: H });
    if (it.p.endcard) sl.addText([{ text: data.brand.toLowerCase(), options: { bold: true, fontSize: 20, breakLine: true } }, { text: 'ESO QUE QUIERES, HOY.', options: { fontSize: 7, charSpacing: 1 } }], { x: x + W * 0.3, y: y + NOTE + 0.03 + H * 0.3, w: W * 0.4, h: H * 0.32, color: '111111', align: 'center', valign: 'middle', isTextBox: true, margin: 0 });
    sl.addText(esc(it.p.audio), { x, y: y + NOTE + 0.05 + H, w: W, h: DLG, fontSize: 8.5, bold: true, color: 'FFFFFF', align: 'center', valign: 'top', isTextBox: true, margin: 0, fit: 'shrink' });
  });
});
pres.writeFile({ fileName: path.join(dir, out) }).then(f => console.log('wrote', f));
