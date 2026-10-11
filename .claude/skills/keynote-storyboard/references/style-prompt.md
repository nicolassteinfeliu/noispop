# Estilo de dibujo y prompts para las viñetas

## Modelo y costo
- Higgsfield `generate_image_batch` (hasta 12 por llamada), `model: "gpt_image_2_5"`, `aspect_ratio: "16:9"`.
  Cuesta ~0,25 créditos por viñeta (verificar con `generate_image` + `get_cost: true` antes de gastar).
- No usar `use_unlim` salvo que el usuario lo pida. `get_preferences` dice si hay que crear proyecto (normalmente no).

## Prefijo de estilo (ponerlo al inicio de CADA prompt, sin cambios)
Black and white storyboard panel hand-drawn by a professional film storyboard artist: graphite pencil and ink
line drawing on white paper, loose confident sketch strokes, cross-hatching and soft pencil shading, pure
grayscale, NO color at all. Single cinematic 16:9 frame. No captions, no words, no letters, no numbers. Scene: ...

## Reglas que hacen que el storyboard se lea
- Personajes con un rasgo fijo repetido en cada prompt ("MODEL 1, young woman with long voluminous wavy hair";
  "MODEL 2, young woman with a short sleek chin-length bob"). Sin eso, cada viñeta dibuja a otra persona.
- Un panel por beat o por efecto. Los efectos se sintetizan con recursos de storyboard clásico:
  - cambio de look / utilería en el beat → un cuadro partido por una línea en rayo ("before-and-after split
    drawn as one frame divided by a jagged lightning-shaped line … identical pose both halves").
  - zoom back que revela → cuadro dentro del cuadro con flechas a las esquinas ("frame within a frame … arrows from
    the inner rectangle corners pointing outward").
  - giro de cámara 360° → flecha circular alrededor del objeto pivote.
  - push-in / travelling / grúa → flechas de storyboard ("storyboard camera arrows … pointing inward").
  - montaje rápido de muchos planos → mosaico de 6 cuadros verticales sobre fondo oscuro.
  - pantalla dividida → "horizontal split-screen frame divided in two equal halves by a thin straight line".
  - morph de piso / locación → mitad y mitad con línea punteada en el borde.
  - toma "imposible" (dron, brazo robótico) → cenital o travelling bajo entre objetos, con flecha.
- Sobreimpresos de precio o texto: pedir "a clean empty rounded rectangle sketched as a placeholder box for an
  on-screen super, left blank" en el tercio inferior. El texto real se pone en el HTML, nunca en la imagen.
- Tarjeta de cierre: pedir una caja vacía centrada; el logo y el claim van como texto HTML encima (`endcard: true`).
- Siempre pedir "No captions, no words, no letters, no numbers": los modelos escriben mal el español.

## Revisión visual
Antes de componer, revisar todas las viñetas en hojas de contacto (4 por hoja). Rehacer solo las que estén en
color, con texto, con el personaje equivocado o sin el recurso de storyboard pedido. Un reintento con el mismo
prompt y un detalle más explícito suele bastar.
