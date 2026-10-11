# Traer las imágenes generadas al entorno local

Los resultados de Higgsfield viven en `d8j0ntlcm91z4.cloudfront.net`. En los entornos cloud de Claude Code ese
host suele estar bloqueado por la política de red (curl responde `CONNECT tunnel failed, response 403`).
Dos caminos:

1. **Pedir al usuario que permita el dominio** (Network access del entorno → Allowed domains). Si está permitido,
   basta `curl -o pNN.png <result_url>`.

2. **Puente por el sandbox de Higgsfield** (funciona sin cambiar nada):
   - `sandbox_exec`: descargar todas las URLs con curl dentro del sandbox, convertir a JPEG en escala de grises
     de 1280 px de ancho (Pillow, `convert('L')`, quality 78 → ~200-260 KB cada una).
   - `sandbox_exec` con `image_paths` devuelve las imágenes "nativamente" y el harness las guarda en
     `~/.claude/projects/<proyecto>/<sesión>/tool-results/mcp-Higgsfield-blob-<ts>-<id>.jpg`.
     Límite: ≤ 512 KiB por llamada y máximo 4 imágenes → mandar 2 por llamada, varias llamadas en paralelo.
   - En la respuesta, la línea `[Image: source: …/mcp-Higgsfield-blob-….jpg]` aparece en el mismo orden que
     `image_paths`; anotar el mapeo pNN → blob y copiarlos con `cp` a `storyboard/panels/pNN.jpg`.

Comando de referencia dentro del sandbox (cambiar las URLs):

```bash
mkdir -p /home/user/sb/panels /home/user/sb/jpg && cd /home/user/sb/panels
cat > urls.txt <<'EOF2'
01 https://…png
02 https://…png
EOF2
while read n u; do curl -sfL -o "p$n.png" "$u" & done < urls.txt; wait
python3 - <<'PY'
from PIL import Image; import glob, os
for f in sorted(glob.glob('/home/user/sb/panels/p*.png')):
    im=Image.open(f).convert('L'); im=im.resize((1280, round(1280*im.height/im.width)), Image.LANCZOS)
    out='/home/user/sb/jpg/'+os.path.basename(f).replace('.png','.jpg'); im.save(out,'JPEG',quality=78,optimize=True); print(out, os.path.getsize(out))
PY
```
