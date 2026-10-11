# data.json para build_storyboard.py

```json
{
  "title": "Marca Campaña Storyboard",          // <title> de la página; nombre corto, sin dos puntos
  "brand": "Marca",                              // se usa en la tarjeta de cierre (endcard)
  "spot": "Spot TV / digital · 30 segundos · Verano 2026",
  "source": "Keynote resumen_story.key (anotaciones de las láminas con video)",
  "cast": [ {"name": "Modelo 1", "desc": "rasgo fijo + en qué escenas aparece"} ],
  "legend": [ {"k": "Chasquido", "v": "qué significa el recurso en este comercial"} ],
  "scenes": [
    {
      "num": 1, "name": "Nombre corto", "tc": "0:00 – 0:04",
      "loc": "LOC OFF: \"...\" o Sobreimpreso: ...",      // opcional
      "refs": "referencias de la lámina (videos/fotos)",   // opcional
      "panels": [
        {"img": "p01.jpg", "shot": "Plano detalle",      // etiqueta corta del encuadre o recurso
         "action": "qué se ve",                           // en el idioma del cliente
         "fx": "cómo se hace el efecto, tal como lo describen las notas",
         "cam": "movimiento de cámara",
         "audio": "música / LOC / sobreimpreso",
         "endcard": false}                                // true solo en la tarjeta de cierre
      ]
    }
  ]
}
```

- Las imágenes van en `<dir>/panels/` con los nombres usados en `img` (JPEG 16:9, escala de grises).
- `python3 -I build_storyboard.py <dir> --pdf` escribe `index.html` (cuerpo para el Artifact, sin doctype),
  `print.html` (documento completo) y `storyboard.pdf` (A4 vertical, 4 viñetas por página, cada escena en
  página nueva) usando el Chromium de Playwright (`/opt/pw-browsers/chromium-*/chrome-linux/chrome`).
- Publicar el Artifact con `file_path: <dir>/index.html` y `files: {"panels/pNN.jpg": "<dir>/panels/pNN.jpg", ...}`.
