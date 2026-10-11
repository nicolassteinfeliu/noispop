#!/usr/bin/env python3
"""Extract everything a storyboard artist needs from a Keynote (.key) file:
slide order, presenter notes + on-slide text per slide, which media (images/videos)
each slide uses, contact sheets of every video and thumbnail sheets of the images.

Usage: python3 -I keynote_extract.py <file.key> <outdir>
Writes <outdir>/report.md plus <outdir>/sheets/*.jpg and <outdir>/unzipped/ (raw package).
Needs: python3 + Pillow, ffmpeg/ffprobe. No third-party snappy module (iwa.py is pure Python).
"""
import os, re, sys, zipfile, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iwa import iwa_decompress

def read_varint(b, p):
    r = 0; s = 0
    while True:
        x = b[p]; p += 1; r |= (x & 0x7f) << s
        if not x & 0x80: return r, p
        s += 7

def walk(b, ints, strs, depth=0, maxdepth=14):
    """Ordered generic protobuf walk: appends varints to ints (in order) and utf-8 strings to strs."""
    p = 0; n = len(b)
    try:
        while p < n:
            key, p = read_varint(b, p); w = key & 7
            if w == 0:
                v, p = read_varint(b, p); ints.append(v)
            elif w == 1: p += 8
            elif w == 5: p += 4
            elif w == 2:
                l, p = read_varint(b, p); sub = b[p:p+l]; p += l
                is_text = False
                try:
                    s = sub.decode('utf-8')
                    clean = ''.join(ch if (ch.isprintable() or ch in '\n\t') else ' ' for ch in s.replace('\r', '\n'))
                    good = sum(1 for ch in s if ch.isprintable() or ch in '\n\r\t')
                    # prose-like chunk: mostly printable and has letters -> keep whole, don't walk into it
                    if len(s) >= 4 and good >= 0.9 * len(s) and re.search(r'[A-Za-zÀ-ÿ]{3}', s):
                        strs.append(clean); is_text = True
                except UnicodeDecodeError: pass
                if not is_text and depth < maxdepth and l > 0: walk(sub, ints, strs, depth+1, maxdepth)
            else: return
    except Exception:
        return

def parse_archives(data):
    """Yield (identifier, type, payload) for every object in a decompressed .iwa."""
    p = 0; out = []
    while p < len(data):
        l, p = read_varint(data, p); info = data[p:p+l]; p += l
        q = 0; ident = None; msgs = []
        while q < len(info):
            key, q = read_varint(info, q); f = key >> 3; w = key & 7
            if w == 0:
                v, q = read_varint(info, q)
                if f == 1: ident = v
            elif w == 2:
                ln, q = read_varint(info, q); sub = info[q:q+ln]; q += ln
                if f == 2:
                    r = 0; t = None; L = None
                    while r < len(sub):
                        k2, r = read_varint(sub, r); f2 = k2 >> 3; w2 = k2 & 7
                        if w2 == 0:
                            v2, r = read_varint(sub, r)
                            if f2 == 1: t = v2
                            if f2 == 3: L = v2
                        elif w2 == 2:
                            ln2, r = read_varint(sub, r); r += ln2
                        elif w2 == 1: r += 8
                        elif w2 == 5: r += 4
                    msgs.append((t, L))
            elif w == 1: q += 8
            elif w == 5: q += 4
        for t, L in msgs:
            out.append((ident, t, data[p:p+L])); p += L
    return out

NOISE = re.compile(r'^(\$?[0-9a-fA-F-]{12,}|apple:.*|All at Once|Transition|decimal|gregorian|[A-Za-z0-9_.:/+-]{1,6})$')
def useful_strings(strs):
    """Keep prose-like strings (notes, titles, on-slide text); drop hashes, uuids, Keynote internals."""
    seen = set(); out = []
    for s in strs:
        s2 = re.sub(r'[ \t]+', ' ', s.replace('\r', '\n')).strip()
        if len(s2) < 4 or NOISE.match(s2) or s2 in seen: continue
        if not re.search(r'[A-Za-zÀ-ÿ]{3}', s2): continue
        seen.add(s2); out.append(s2)
    return out

def main():
    key, out = sys.argv[1], sys.argv[2]
    unz = os.path.join(out, 'unzipped'); os.makedirs(unz, exist_ok=True)
    sheets = os.path.join(out, 'sheets'); os.makedirs(sheets, exist_ok=True)
    with zipfile.ZipFile(key) as z: z.extractall(unz)
    idx = os.path.join(unz, 'Index'); data_dir = os.path.join(unz, 'Data')
    dec = {f: iwa_decompress(os.path.join(idx, f)) for f in os.listdir(idx) if f.endswith('.iwa')}
    slide_files = {int(m.group(1)): f for f in dec for m in [re.match(r'Slide-(\d+)\.iwa$', f)] if m}
    # slide order from Document.iwa: Show (type 2) lists slide-node ids in order; nodes (type 4) reference slide ids
    doc = parse_archives(dec['Document.iwa'])
    nodes = {}
    for ident, t, payload in doc:
        if t == 4:
            ints, strs = [], []; walk(payload, ints, strs)
            ref = [i for i in ints if i in slide_files]
            if ref: nodes[ident] = ref[0]
    order = []
    for ident, t, payload in doc:
        if t == 2:
            ints, strs = [], []; walk(payload, ints, strs)
            for i in ints:
                if i in nodes and nodes[i] not in order: order.append(nodes[i])
    for sid in sorted(slide_files):
        if sid not in order: order.append(sid)
    # media ids from Data filenames
    fileids = {}
    for f in os.listdir(data_dir):
        m = re.search(r'-(\d+)\.[A-Za-z0-9]+$', f)
        if m: fileids.setdefault(int(m.group(1)), f)
    per_slide = []
    for sid in order:
        ints, strs = [], []
        for ident, t, payload in parse_archives(dec[slide_files[sid]]): walk(payload, ints, strs)
        media = sorted({i for i in ints if i in fileids})
        per_slide.append({'id': sid, 'text': useful_strings(strs), 'media': media})
    # media that sits on most slides is template chrome (logos, footers); list it once instead of per slide
    from collections import Counter
    cnt = Counter(i for s in per_slide for i in s['media'])
    shared = {i for i, c in cnt.items() if len(per_slide) >= 4 and c > len(per_slide) / 2}
    # contact sheets for every video, thumbnails per slide for images
    from PIL import Image, ImageDraw
    video_ext = ('.mp4', '.mov', '.m4v', '.avi'); have_ffmpeg = shutil.which('ffmpeg') is not None
    def sheet_for_video(path, dst):
        try:
            d = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip() or 1)
        except Exception: d = 1.0
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-vf', f'fps=12/{max(d,0.5)},scale=320:-1,tile=4x3', '-frames:v', '1', dst], capture_output=True)
        return d
    lines = [f'# Keynote extract: {os.path.basename(key)}', '', f'{len(order)} slides in presentation order. Media shared by most slides (logo/template, not listed per slide): {[fileids[i] for i in sorted(shared)]}', '']
    for k, s in enumerate(per_slide, 1):
        lines.append(f'## Slide {k} (id {s["id"]})'); lines.append('')
        lines.append('Text / notes:')
        for t in s['text']: lines.append('  - ' + t.replace('\n', '\n    '))
        lines.append(''); lines.append('Media:')
        thumbs = []
        for i in s['media']:
            if i in shared: continue
            f = fileids[i]; p = os.path.join(data_dir, f); low = f.lower()
            if low.endswith(video_ext):
                dst = os.path.join(sheets, f'slide{k:02d}_video_{i}.jpg'); dur = sheet_for_video(p, dst) if have_ffmpeg else 0
                lines.append(f'  - VIDEO {f} ({dur:.1f}s) -> contact sheet {dst}')
            elif 'small' in low or low.startswith('posterimage'):
                continue
            else:
                try:
                    im = Image.open(p); im.load(); im = im.convert('RGB'); im.thumbnail((420, 420)); thumbs.append((i, im))
                    lines.append(f'  - image {f}')
                except Exception as e:
                    lines.append(f'  - file {f} (not previewable: {e})')
        if thumbs:
            cols = min(4, len(thumbs)); rows = (len(thumbs) + cols - 1) // cols
            sh = Image.new('RGB', (cols*430, rows*450), 'white'); dr = ImageDraw.Draw(sh)
            for j, (i, im) in enumerate(thumbs):
                x = (j % cols)*430; y = (j // cols)*450; sh.paste(im, (x+5, y+25)); dr.text((x+5, y+5), str(i), fill='black')
            dst = os.path.join(sheets, f'slide{k:02d}_images.jpg'); sh.save(dst, quality=85)
            lines.append(f'  - image thumbnails -> {dst}')
        lines.append('')
    open(os.path.join(out, 'report.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    print('\n'.join(lines))

if __name__ == '__main__':
    main()
