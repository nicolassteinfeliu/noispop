---
name: keynote-storyboard
description: Convierte un Keynote (.key) de guión con notas, fotos y videos de referencia en un storyboard dibujado en blanco y negro (estilo dibujante de storyboard, lápiz y tinta) de hasta 30 láminas, listo para mostrar a un publicista o cliente antes de filmar, entregado como página (Artifact) y PDF. Usa esta skill siempre que el usuario suba o mencione un archivo .key / Keynote / "guión" / "resumen story" y pida storyboard, viñetas, láminas, "dibujos de las escenas", previsualización, o quiera "ver la historia antes de filmar"; también cuando pida regenerar o actualizar un storyboard ya hecho con esta skill, aunque no diga la palabra storyboard. Requiere Higgsfield (generate_image_batch, sandbox_exec) y Python 3 con Pillow; ffmpeg para ver los videos.
---

# Keynote → storyboard en blanco y negro

El flujo completo se hizo por primera vez para el spot "Hites Verano 2026" y quedó en
`storyboard/` de aquella sesión; los scripts de esta skill son la versión reutilizable.
La idea es que el usuario suba el `.key`, se vaya, y vuelva a encontrar el PDF y el link.
Por eso: no hagas preguntas que bloqueen. Toma decisiones razonables, dilas al final.

## 1. Leer el Keynote completo (notas + videos + fotos)

```bash
python3 -I <skill>/scripts/keynote_extract.py <archivo.key> <scratchpad>/key
```

Escribe `report.md` con el orden real de las láminas, el texto y las notas de cada una, y qué
videos/fotos usa cada lámina, más `sheets/`: una hoja de contacto de 12 fotogramas por video
(`slideNN_video_<id>.jpg`) y una hoja de miniaturas de las fotos de cada lámina (`slideNN_images.jpg`).
Lee el reporte y mira TODAS las hojas (con Read, varias por llamada). Los videos son la referencia
visual de cada efecto; sin verlos, el storyboard se inventa el efecto.

Por qué un script propio: `.key` es un zip con objetos protobuf comprimidos con snappy; `iwa.py` los
descomprime en Python puro, sin dependencias. El orden de láminas sale de `Document.iwa`, y la
relación lámina→archivo se deduce de los ids numéricos en los nombres de `Data/`.

## 2. Decidir qué manda

Los guiones suelen tener una lámina "guión madre" (el texto general) y luego láminas por escena con
videos y una anotación más específica. **La anotación de la lámina con video manda sobre el guión
escrito** cuando se contradicen (el usuario lo pidió explícitamente en el primer uso: "la cámara se
acerca" en la nota vs. "se aleja" en el guión). Guarda las anotaciones en `annotations.md` tal cual,
con una nota de prioridad, para poder verificar después.

## 3. Planificar las láminas (≤ 30, normalmente 25-29)

Una lámina por beat o por efecto; el límite es del usuario, respétalo contando también la tarjeta de
cierre. Cada efecto se sintetiza con un recurso de storyboard clásico (antes/después partido por un
rayo, cuadro dentro del cuadro para un zoom back, flecha circular para un 360°, mosaico para un
montaje, pantalla dividida, mitad y mitad con línea punteada para un morph). La lista completa de
recursos y el prefijo de estilo están en `references/style-prompt.md`; léelo antes de escribir prompts.

Fija los personajes con un rasgo visual repetido en todos los prompts (pelo largo ondulado / bob corto)
y escribe los prompts en inglés (el modelo dibuja mejor) pidiendo siempre "no text". Los
sobreimpresos de precio y el logo nunca van en la imagen: se piden como caja vacía y el texto se pone
en el HTML.

## 4. Generar en Higgsfield

`generate_image_batch` con `gpt_image_2_5`, `16:9`, 12 por llamada, varias llamadas en el mismo turno;
luego `jobs_wait` por grupo. Preflight de costo con `generate_image` + `get_cost: true`
(≈0,25 créditos por viñeta) y revisa `balance` antes de gastar. Después `show_generation_by_ids` una
sola vez con todos los jobs.

## 5. Traer las imágenes y revisarlas

El CDN de resultados suele estar bloqueado por la red del entorno. El puente que funciona está en
`references/transfer-from-higgsfield.md` (descargar en el sandbox de Higgsfield, convertir a JPEG gris
1280 px, devolverlas con `image_paths` de a 2, copiarlas desde `tool-results/`). Al verlas, comprueba:
blanco y negro, sin texto, personaje correcto, recurso de storyboard presente. Rehaz solo las fallidas.

## 6. Escribir los textos y armar la entrega

Escribe `data.json` (esquema en `references/data-schema.md`): por viñeta, acción, **efecto/proceso tal
como lo describen las notas**, cámara y audio/sobreimpreso; por escena, nombre, timecode estimado,
LOC y referencias. Español neutro-chileno si el cliente escribe así (reposera, quitasol, taco, polera).

```bash
python3 -I <skill>/scripts/build_storyboard.py <dir> --pdf
```

Produce `index.html` (cuerpo para el Artifact), `print.html` y `storyboard.pdf` (A4 vertical, 4 viñetas
por página, una escena por página). Revisa el PDF con `pdftoppm -r 40` y una hoja de miniaturas.

Verificación: si el entorno tiene el tool Workflow (o subagentes), lanza revisores por escena que
intenten refutar la fidelidad de `data.json` contra `annotations.md` más un revisor de idioma; aplica
los findings de severidad alta/media antes de publicar.

Entrega: publica el Artifact (`file_path: index.html`, `files` con `panels/*.jpg`, `icon: "film"`),
manda `storyboard.pdf` con SendUserFile, y resume en 10 líneas: láminas por escena, efectos
sintetizados, decisiones tomadas y créditos gastados. Si el usuario pide cambios en una escena,
regenera solo esas viñetas, actualiza `data.json` y republica el mismo Artifact (misma `url`).
