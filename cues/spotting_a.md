# Spotting — Opción A «Hiperreal»

**Geely EX2 / EX5 · 49.75 s · 24 fps · TC = HH:MM:SS:FF** (cuadro 0 = 00:00:00:00). Hoja de cues: `cues/option_a.yaml` (78 cues).

## Intención sonora

La opción A no le pone sonido a la publicidad, sino al mundo que muestra. Cada plano tiene el aire que tendría si estuviéramos ahí: hormigón húmedo bajo el paso elevado al amanecer, niebla espesa en la ciudad de los pandas, rompiente lejana bajo el acantilado, viento patagónico frente a las Torres del Paine, el zumbido grave de un túnel. Los autos son eléctricos y se escuchan así: neumáticos sobre asfalto seco, mojado, grava o nieve, aire que se abre a su paso, un AVAS apenas presente cuando están detenidos. Nunca suena un motor. El foley es preciso y escaso. Va puesto cuadro a cuadro en los contactos que se ven: el apoyo de las patas del panda, medido en el cuadro donde el pie toca el suelo; la pata contra el parabrisas; el detent del selector; el obturador; el cierre del portón; el golpe de agua en el túnel. Debajo de la locución todo queda contenido y protegido. En los huecos sin voz (la apertura, el POV del semáforo rojo, el olfateo del panda, el semáforo peatonal, el desierto, el lago, el túnel) el mundo respira un poco más. El remate (46.83–49.71) no tiene música y es el único momento expuesto: una calle vacía de día, tres pasos de panda, un olfateo, un par de gorriones y el EX2 mojado que gotea con su AVAS, hasta el corte seco a silencio en 49.708 s. No hay whooshes, subs ni brillos tonales: los buses DES y SUB no se usan. El único "aire" que acompaña un movimiento de cámara es una ráfaga natural de viento con arena (desierto, 25.71 s).

## Convenciones

- **Sonido**: receta (`familia.nombre`) con sus parámetros, bus y ganancia del cue sobre la normalización de la receta (eventos a pico −6 dBFS, camas a RMS −20 dBFS).
- **TC A → B**: inicio del cue (o su punto de sync) → corte duro (`until`) con su fade. En eventos, el TC es el punto de sync de la receta (transiente, pico, primer contacto o final según el catálogo).
- **sync frame/cut fN**: cuadro validable a ±1. Las camas que entran antes del corte (J-cut) quedan como `free`.
- **Protección VO**: `normal` por defecto. Va en **fuerte** cuando el cue tiene medios bajo la locución y **sin protección** cuando cae entero en un hueco o en el remate.
- Sub-cortes vistos en la imagen que no figuran en `cuts[]`: f56, f308, f404, f418, f747, f771, f801, f838 y f989.

## Hoja de spotting

### 0.00-1.21 PASO BAJO AL AMANECER (hueco VO 0-1.15)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:00:00 → 00:00:01:09 | Paso bajo de hormigón al amanecer, EX2 en primer plano | **Room tone** (`amb.room_tone`, space=underpass, air_db=-18, rumble_db=-8) · AMB -13 dB | Tono de hormigón bajo el paso elevado; cola L-cut 4 cuadros sobre la rueda |
| 00:00:00:00 → 00:00:01:09 | Paso bajo de hormigón al amanecer, EX2 en primer plano | **Ciudad lejana** (`amb.city_distant`, density=0.3, lp_hz=500, passbys=1, fog=true) · AMB -19 dB | Ciudad lejana al amanecer más allá de la boca del paso (hombre en silueta) |
| 00:00:00:00 → 00:00:01:07 | Paso bajo de hormigón al amanecer, EX2 en primer plano | **Goteo** (`amb.drips`, rate=2.2, space=underpass_concrete, pitch=1.0) · AMB -18 dB | Dos gotas tardías (0.82 y 0.97 s) en los pilares de la izquierda, con su reverb de hormigón |
| 00:00:00:00 → 00:00:01:07 | Paso bajo de hormigón al amanecer, EX2 en primer plano | **AVAS EV en reposo** (`veh.avas_idle`, level=0.35) · VEH -20 dB | EX2 encendido en primer plano (centro-derecha): AVAS apenas presente |

### 1.21-2.33 RUEDA (oscurece ~2.04 s, f49)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:01:05 → 00:00:02:09 | Rueda girando en primer plano (va a negro f49-52) | **Rueda girando** (`veh.wheel_spin`, speed_kmh=40, disc_whir=0.5, darken_at=0.7) · VEH -16 dB · protección VO fuerte · sync cut f29 | Rueda en primer plano: rodado + whir de disco; se apaga cuando la imagen va a negro (f49-52) |

### 2.29-2.75 ENTRE TORRES (f56-65, hueco VO 2.59-3.39)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:02:07 → 00:00:02:18 | Contrapicado veloz entre torres | **Rodado** (`veh.onboard_roll`, speed_kmh=70, surface=dry, perspective=onboard) · VEH -12 dB · envío city_day_street -8 dB · sync frame f56 | Contrapicado veloz entre torres: aero + rodado onboard, reflexiones (slap) de las fachadas |

### 2.75-3.17 EX2 DE FRENTE, DETENIDO (f66-75, hueco VO)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:02:17 → 00:00:03:04 | EX2 de frente, detenido, faros encendidos | **AVAS EV en reposo** (`veh.avas_idle`, level=0.45) · VEH -16 dB · sin protección VO (hueco) · sync cut f66 | EX2 quieto de frente, faros encendidos: AVAS cercano, dentro del hueco sin locución |

### 3.17-3.96 PASO ELEVADO, AUTO HACIA CÁMARA

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:03:22 → 00:00:04:01 | Bajo el paso elevado: EX2 avanza hacia cámara | **Auto se acerca** (`veh.approach`, speed_kmh=60, start_m=25, end_m=4, surface=dry, ev=0.4) · VEH -12 dB · protección VO fuerte · sync frame f94 | EX2 avanza por la avenida vacía y llega a cámara en f94 (último cuadro antes del faro) |

### 3.96-5.17 FARO EN LA NIEBLA (restricción)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:03:20 → 00:00:05:04 | Faro en la niebla | **Aire de niebla** (`amb.fog_air`, brightness=0.4, motion=0.3) · AMB -21 dB | Niebla casi silenciosa alrededor del faro; entra 3 cuadros antes del corte |
| 00:00:03:23 | Faro en la niebla | **Clic de relé** (`fol.relay_click`) · FOL -15 dB · sync cut f95 | Clic de relé muy sutil: el faro aparece encendido justo en el corte |

### 5.17-6.63 POV INTERIOR, SEMÁFORO ROJO (hueco VO 5.25-6.59)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:05:01 → 00:00:06:16 | POV interior: semáforo rojo, panda cruza a lo lejos | **Cabina detenida** (`amb.cabin_still`, hvac=0.25, exterior=city_fog) · AMB -12 dB | Cabina detenida: HVAC + ciudad con niebla a través del vidrio; el mundo respira en el hueco |
| 00:00:05:12 | POV interior: semáforo rojo, panda cruza a lo lejos | **Pasos de panda** (`cre.panda_steps`, steps=3, gait_s=0.45, surface=wet_asphalt, weight=0.8) · FOL -25 dB · envío city_fog_street -6 dB · sync frame f132 | Panda lejano cruzando frente a los faros del otro auto: pasos apenas audibles |

### 6.63-14.58 CALLE CON NIEBLA (cama continua, con hueco interior en la pata)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:06:14 → 00:00:14:14 | Panda cruza frente a los faros | **Room tone** (`amb.room_tone`, space=city_fog, air_db=-16, rumble_db=-8) · AMB -20 dB · protección VO fuerte · sync cut f159 | Calle con niebla (pandas, EX2, poste): baja 10 dB mientras estamos dentro del auto (pata, f179-194) |
| 00:00:06:14 → 00:00:14:14 | Panda cruza frente a los faros | **Ciudad lejana** (`amb.city_distant`, density=0.4, lp_hz=500, passbys=1, fog=true) · AMB -23 dB · protección VO fuerte · sync cut f159 | Wash de ciudad lejana bajo la niebla, mismo recorrido que A100 |

#### 6.63-7.46 panda cruzando frente a los faros

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:07:00 | Panda cruza frente a los faros | **Pasos de panda** (`cre.panda_steps`, surface=wet_asphalt, weight=1.0, step_times=[0.0, 0.25]) · FOL -13 dB · envío city_fog_street -12 dB · sync frame f168 | Apoyo de la pata trasera cercana en f168 (contacto medido) y lejana en f174 |
| 00:00:06:18 | Panda cruza frente a los faros | **Respiración de panda** (`cre.panda_breath`, type=exhale, close=false) · FOL -19 dB · envío city_fog_street -12 dB, protección VO fuerte · sync frame f162 | Exhalación tranquila del panda mientras camina, a media distancia |

#### 7.46-8.13 pata contra el parabrisas (HERO), desde dentro

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:07:10 → 00:00:08:04 | Pata del panda contra el parabrisas (POV interior) | **Cabina detenida** (`amb.cabin_still`, hvac=0.2, exterior=city_fog) · AMB -16 dB · protección VO fuerte · sync cut f179 | Volvemos al interior: HVAC suave detrás de la pata |
| 00:00:07:11 → 00:00:08:07 | Pata del panda contra el parabrisas (POV interior) | **Pata contra el vidrio** (`cre.paw_on_glass`, press_ms=210, squeak=0.35, sniff=true, inside=true) · FOL -9 dB · protección VO fuerte · sync cut f179 | HERO: thump modal del vidrio en el corte (la pata ya apoyada), chirrido al deslizar (~f184), olfateo |

#### 8.13-10.54 filas de pandas / EX2 entre pandas

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:08:02 → 00:00:12:07 | Filas de pandas en la niebla | **Multitud de pandas** (`cre.panda_crowd`, density=0.5, distance=mid) · FOL -22 dB · protección VO fuerte · sync cut f195 | Presencia de cientos de pandas a ambos lados (roces de pelaje, resoplidos lejanos); se aleja en el perfil |
| 00:00:09:09 → 00:00:12:07 | EX2 avanza entre las filas de pandas | **AVAS EV en reposo** (`veh.avas_idle`, level=0.5) · VEH -18 dB · sync cut f226 | EX2 avanzando entre las filas (micro-pausa VO 9.22-9.38 justo antes); queda lejano detrás del perfil |
| 00:00:10:10 → 00:00:10:15 | EX2 avanza entre las filas de pandas | **Deslizamiento en mojado** (`veh.wet_glide`, speed_kmh=12, sizzle=0.5) · VEH -21 dB · sync frame f250 | Siseo lento de neumáticos en asfalto mojado, muy bajo; más cercano al final del plano (f250) |

#### 10.54-12.29 perfil de panda (hueco VO 10.27-10.94)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:10:15 → 00:00:11:02 | Perfil de panda; auto con luces rojas detrás | **Respiración de panda** (`cre.panda_breath`, type=sniff, close=true) · FOL -8 dB · sync frame f255 | Olfateo cercano del panda en primer plano, dentro del hueco sin locución |
| 00:00:11:12 | Perfil de panda; auto con luces rojas detrás | **Respiración de panda** (`cre.panda_breath`, type=exhale, close=true) · FOL -16 dB · protección VO fuerte · sync frame f276 | Exhalación lenta y cercana, bajo la locución (protección fuerte) |

### 12.29-14.00 EX2 SE DESLIZA / PASO DE RUEDA (f308) / FOCOS (13.5)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:13:00 | Paso de rueda en primer plano | **Deslizamiento en mojado** (`veh.wet_glide`, speed_kmh=20, sizzle=0.6) · VEH -10 dB · protección VO fuerte · sync frame f312 | Deslizamiento sobre asfalto mojado con el paso de rueda más cercano en f312 (13.0 s); nada extra en el reveal 13.5 |

### 14.00-14.58 POSTE + SEMÁFORO PEATONAL (hueco VO 13.18-14.59)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:14:02 | Poste y semáforo peatonal en rojo; el EX2 pasa | **Semáforo peatonal** (`fol.ped_signal`, count=1, rate_hz=1.0) · FOL -11 dB · envío city_fog_street -10 dB, sin protección VO (hueco) · sync frame f338 | Un tic del semáforo peatonal en rojo (arriba a la derecha), con la calle mojada de fondo |
| 00:00:14:07 → 00:00:14:14 | Poste y semáforo peatonal en rojo; el EX2 pasa | **Pass-by EV** (`veh.passby`, speed_kmh=18, closest_m=2.5, direction=-1, surface=wet, ev=0.4) · VEH -11 dB · sin protección VO (hueco) · sync frame f343 | El EX2 pasa lento detrás del poste de derecha a izquierda, neumáticos en mojado |

### 14.58-15.71 AÉREO COSTA (J-cut 4 cuadros, L-cut 6)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:14:10 → 00:00:15:23 | Aéreo: acantilado costero, olas | **Olas** (`amb.surf`, intensity=0.6, crest_at=0.44, distance=far) · AMB -21 dB · protección VO fuerte | Olas rompiendo al pie del acantilado; cresta a mitad de plano (f363) |
| 00:00:14:10 → 00:00:16:07 | Aéreo: acantilado costero, olas | **Viento** (`amb.wind`, strength=0.5, gustiness=0.4, whistle=0.15, texture=none) · AMB -23 dB · protección VO fuerte | Viento del acantilado; sigue bajo la curva de grava (misma costa) y termina en el arco |

### 15.71-16.29 CURVA DE GRAVA MOJADA (hueco VO 15.94-16.35)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:16:01 → 00:00:16:09 | Curva de grava mojada, contraluz | **Curva en grava** (`veh.gravel_curve`, speed_kmh=25, wet=true) · VEH -11 dB · protección VO fuerte · sync frame f385 | Grava húmeda crujiendo en la curva, máximo cuando el auto encara a cámara (f385) |

### 16.29-18.29 ARCO DE ROCA / RUTA OSCURA / HACES

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:16:13 → 00:00:17:10 | Arco de roca, auto a lo lejos | **Pass-by EV** (`veh.passby`, speed_kmh=50, closest_m=18, direction=1, surface=dry, ev=0.3) · VEH -19 dB · envío rock_arch -5 dB, protección VO fuerte · sync frame f397 | Pass-by lejano visto a través del arco (16.5 s), la roca devuelve la reflexión; sigue en la ruta oscura |
| 00:00:16:06 → 00:00:18:07 | Arco de roca, auto a lo lejos | **Viento** (`amb.wind`, strength=0.3, gustiness=0.3, whistle=0.1, texture=none) · AMB -24 dB · envío rock_arch -12 dB, protección VO fuerte · sync cut f391 | Aire frío y oscuro del acantilado |
| 00:00:18:05 → 00:00:18:09 | Haces de faros con destello | **Auto se acerca** (`veh.approach`, speed_kmh=40, start_m=40, end_m=12, surface=dry, ev=0.4) · VEH -13 dB · protección VO fuerte · sync frame f437 | Haces de faros acercándose con el destello (17.5-18.2) |

### 18.29-19.29 VALLE (hueco VO 18.91-19.23)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:18:04 → 00:00:19:08 | Valle con rayos de sol | **Viento de montaña** (`amb.mountain_wind`, strength=0.4, river=0.2, echo=true) · AMB -18 dB · protección VO fuerte | Viento suave de valle con ecos; auto diminuto abajo |
| 00:00:18:23 | Valle con rayos de sol | **Ave lejana** (`amb.birds_distant`, count=1, species=raptor) · AMB -12 dB · sync frame f455 | Un ave rapaz lejana en el hueco sin locución, con eco de valle |

### 19.29-22.46 INTERIOR MANEJANDO (EV silencioso)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:19:06 → 00:00:22:11 | Interior: hombre manejando | **Cabina EV en marcha** (`amb.cabin`, speed_kmh=60, road=0.4, hvac=0.25, pillar_wind=0.3) · AMB -24 dB · protección VO fuerte · sync cut f463 | Cabina EV en marcha: rodado sordo, HVAC, viento de pilar; casi nada (sin sonidos vocales) |
| 00:00:20:17 | Interior: hombre manejando | **Suspensión** (`fol.suspension`) · FOL -15 dB · sync frame f497 | Un golpe sordo de suspensión (junta del camino) a mitad del plano |

### 22.46-23.63 EX2 EN LA OSCURIDAD (hueco VO 22.34-22.78)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:22:10 → 00:00:23:16 | EX2 de frente en la oscuridad | **Aire de niebla** (`amb.fog_air`, brightness=0.35, motion=0.3) · AMB -20 dB · sync cut f539 | Niebla en la oscuridad alrededor del EX2 |
| 00:00:22:11 → 00:00:23:16 | EX2 de frente en la oscuridad | **AVAS EV en reposo** (`veh.avas_idle`, level=0.4) · VEH -14 dB · sync cut f539 | EX2 detenido, listo: AVAS suave |

### 23.63-25.21 EX5 HAZ CENITAL (estudio)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:23:15 → 00:00:25:06 | EX5 bajo haz de luz cenital (estudio) | **Estudio vacío** (`amb.studio`, hum=0.3) · AMB -20 dB · protección VO fuerte · sync cut f567 | Escenario grande y vacío: aire + zumbido mínimo de lámparas |
| 00:00:23:15 → 00:00:25:05 | EX5 bajo haz de luz cenital (estudio) | **Contactor de luz** (`fol.light_contactor`, hum=0.5) · FOL -11 dB · sync cut f567 | Contactor de luz de estudio en el cuadro exacto en que se enciende el haz (f567, imagen sobreexpuesta) |

### 25.21-25.46 RUTA OSCURA, FAROS VELOCES

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:25:11 → 00:00:25:17 | Aéreo de desierto, roca en primer plano | **Pass-by EV** (`veh.passby`, speed_kmh=90, closest_m=2.0, direction=1, surface=wet, ev=0.4) · VEH -13 dB · sync cut f611 | Los faros se acercan rápido y el auto pasa la cámara justo en el corte al desierto |

### 25.46-26.33 AÉREO DESIERTO (hueco VO 25.47-26.43)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:25:08 → 00:00:26:11 | Aéreo de desierto, roca en primer plano | **Viento de desierto** (`amb.desert_wind`, strength=0.45, sand=0.4) · AMB -14 dB | Viento seco con arena; L-cut 3 cuadros dentro del interior (el desierto sigue tras el vidrio) |
| 00:00:25:10 | Ruta oscura, faros veloces | **Viento** (`amb.wind`, strength=0.6, gustiness=0.8, whistle=0.1, texture=sand) · AMB -12 dB · sync frame f610 | Ráfaga natural cuando la cámara roza la roca en primer plano (máximo f617), sale por la izquierda |

### 26.33-28.08 TIRA LED + PARLANTE (aire de cabina)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:26:07 → 00:00:28:02 | Tira LED azul del tablero | **Cabina EV en marcha** (`amb.cabin`, speed_kmh=40, road=0.25, hvac=0.35, pillar_wind=0.15) · AMB -23 dB · protección VO fuerte · sync cut f632 | Aire de cabina; en el parlante (f659-673) no se agrega nada: es de la música |
| 00:00:26:08 → 00:00:27:11 | Tira LED azul del tablero | **Fizz de LED** (`fol.led_fizz`) · FOL -19 dB · sync cut f632 | Fizz finísimo de la tira LED, siguiendo el travelling de izquierda a derecha |

### 28.08-29.08 AÉREO BOSQUE

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:27:23 → 00:00:29:05 | Aéreo de bosque | **Bosque** (`amb.forest`, rustle=0.5, birds=1, wind=0.35) · AMB -18 dB · protección VO fuerte | Copas de árboles con viento y un pájaro lejano; cruza 3 cuadros con el frío del volcán |

### 29.08-30.29 EX5 HACIA CÁMARA, VOLCÁN (hueco VO desde 30.08)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:29:01 → 00:00:30:08 | EX5 hacia cámara, volcán nevado | **Aire alpino** (`amb.alpine`, strength=0.4) · AMB -25 dB · protección VO fuerte · sync cut f698 | Aire frío de montaña con el volcán nevado detrás |
| 00:00:30:06 → 00:00:30:09 | EX5 hacia cámara, volcán nevado | **Auto se acerca** (`veh.approach`, speed_kmh=45, start_m=30, end_m=7, surface=dry, ev=0.4) · VEH -17 dB · protección VO fuerte · sync frame f726 | EX5 avanza hacia cámara: rodado y aire, sin motor |

### 30.29-31.58 CAMINO JUNTO AL LAGO (hueco VO 30.08-30.88) + SELECTOR

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:30:05 → 00:00:31:03 | EX5 junto al lago, atardecer | **Orilla de lago** (`amb.lake`, lap=0.45, wind=0.25) · AMB -14 dB | Orilla del lago al atardecer: chapoteo suave + brisa, en el hueco sin locución |
| 00:00:30:07 → 00:00:31:03 | EX5 junto al lago, atardecer | **Rodado** (`veh.onboard_roll`, speed_kmh=50, surface=dry, perspective=far) · VEH -21 dB · sync cut f727 | Rodado lejano del EX5 en el camino costero |
| 00:00:31:02 → 00:00:31:14 | Consola y selector (interior) | **Cabina EV en marcha** (`amb.cabin`, speed_kmh=50, road=0.35, hvac=0.3, pillar_wind=0.2) · AMB -20 dB · sync frame f747 | Interior en la consola (sub-corte f747) |
| 00:00:31:04 | Consola y selector (interior) | **Selector de marcha** (`fol.gear_selector`, style=rotary) · FOL -9 dB · sync frame f748 | Detent preciso del selector rotativo de cristal de la consola, al abrir el plano de la mano |

### 31.58-33.37 BOSQUE: PASS-BY LEJANO + EX5 DE FRENTE

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:31:13 → 00:00:33:09 | Contrapicado en bosque, auto arriba | **Bosque** (`amb.forest`, rustle=0.4, birds=1, wind=0.3) · AMB -21 dB · sync cut f758 | Bosque de pinos a contraluz |
| 00:00:31:20 → 00:00:32:03 | Contrapicado en bosque, auto arriba | **Pass-by EV** (`veh.passby`, speed_kmh=60, closest_m=12, direction=-1, surface=dry, ev=0.3) · VEH -14 dB · envío forest -8 dB, protección VO fuerte · sync frame f764 | Contrapicado: el auto pasa arriba entre los troncos, con el bosque como espacio |
| 00:00:32:02 → 00:00:33:09 | EX5 de frente por el bosque | **Rodado** (`veh.onboard_roll`, speed_kmh=60, surface=dry, perspective=close) · VEH -18 dB · protección VO fuerte · sync frame f771 | Travelling frontal del EX5 por el bosque: rodado cercano |
| 00:00:33:07 → 00:00:33:09 | EX5 de frente por el bosque | **Pass-by EV** (`veh.passby`, speed_kmh=60, closest_m=2.0, direction=1, surface=dry, ev=0.4) · VEH -14 dB · protección VO fuerte · sync frame f799 | El EX5 roza la cámara (f796-800) y corta seco al plano de ciudad |

### 33.37-35.33 CIUDAD: DESDE OTRO AUTO + CAPÓ (hueco VO 34.72-35.23)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:33:08 → 00:00:34:22 | EX2 en la ciudad, por el parabrisas | **Cabina EV en marcha** (`amb.cabin`, speed_kmh=50, road=0.45, hvac=0.2, pillar_wind=0.35) · AMB -20 dB · protección VO fuerte · sync frame f801 | Interior del otro auto en la ciudad (vemos al EX2 a través del parabrisas y la ventana) |
| 00:00:34:02 → 00:00:34:22 | EX2 visto desde otro auto | **Pass-by EV** (`veh.passby`, speed_kmh=25, closest_m=2.5, direction=-1, surface=dry, ev=0.4) · VEH -18 dB · envío cabin_small -10 dB, protección VO fuerte · sync frame f818 | El EX2 pasa al lado (34.0-34.5), escuchado amortiguado desde el otro auto |
| 00:00:34:21 → 00:00:35:08 | Capó del EX2 en primer plano | **Rodado** (`veh.onboard_roll`, speed_kmh=60, surface=dry, perspective=onboard) · VEH -14 dB · sync frame f838 | Capó cercano (35.0): viento y rodado onboard en el hueco sin locución |

### 35.33-35.75 EX2 SALE DEL ARCO AL ATARDECER

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:35:17 → 00:00:35:18 | EX2 sale de la roca al atardecer | **Auto se acerca** (`veh.approach`, speed_kmh=40, start_m=20, end_m=9, surface=dry, ev=0.4) · VEH -18 dB · envío rock_arch -12 dB, protección VO fuerte · sync frame f857 | Cola corta de rodado: el EX2 sale de la roca hacia el sol |

### 35.75-36.88 NIEVE + MONTAÑAS

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:35:15 → 00:00:36:21 | EX2 en la nieve (spray) | **Aire alpino** (`amb.alpine`, strength=0.45) · AMB -23 dB · protección VO fuerte | Silencio frío de nieve y viento de altura (nieve y ruta de montaña) |
| 00:00:35:19 → 00:00:36:09 | EX2 en la nieve (spray) | **Spray de nieve** (`veh.snow_spray`, intensity=0.9) · VEH -11 dB · sync frame f859 | La rueda levanta nieve (spray máximo f859-866): crunch + partículas |
| 00:00:36:17 → 00:00:36:21 | Ruta con montañas nevadas | **Pass-by EV** (`veh.passby`, speed_kmh=55, closest_m=2.5, direction=-1, surface=dry, ev=0.4) · VEH -17 dB · protección VO fuerte · sync frame f881 | En la ruta con montañas nevadas el EX2 pasa pegado a cámara de derecha a izquierda (f879-883) |

### 36.88-37.83 GANSOS POR EL TECHO PANORÁMICO

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:36:20 → 00:00:37:20 | Gansos por el techo panorámico | **Cabina EV en marcha** (`amb.cabin`, speed_kmh=50, road=0.3, hvac=0.25, pillar_wind=0.2) · AMB -22 dB · protección VO fuerte · sync cut f885 | Interior bajo el techo de vidrio |
| 00:00:36:21 → 00:00:37:23 | Gansos por el techo panorámico | **Bandada de gansos** (`cre.geese_flyover`, birds=8, honks=2, through_glass=0.5) · FOL -14 dB · protección VO fuerte · sync cut f885 | Bandada de gansos: aleteos y dos graznidos escasos, apagados por el vidrio |

### 37.83-38.54 AÉREO BOSQUE/LAGO: nada (0.7 s bajo música y locución;

_Sin sonido agregado._


### 38.54-39.92 INTERIOR CON PANTALLA

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:38:12 → 00:00:39:22 | Interior EX5 con pantalla | **Cabina EV en marcha** (`amb.cabin`, speed_kmh=50, road=0.35, hvac=0.3, pillar_wind=0.25) · AMB -20 dB · protección VO fuerte · sync cut f925 | Cabina del EX5 con la gran pantalla (ningún dedo la toca: sin toque de pantalla) |

### 39.92-42.58 TORRES DEL PAINE + CELULAR + PORTÓN

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:39:19 → 00:00:42:14 | Hombre frente a las Torres del Paine | **Viento de montaña** (`amb.mountain_wind`, strength=0.55, river=0.25, echo=true) · AMB -17 dB · protección VO fuerte | Viento patagónico abierto, río lejano; corta seco al túnel |
| 00:00:40:23 | Hombre fotografía con el celular | **Obturador de celular** (`fol.phone_shutter`, style=modern) · FOL -11 dB · sync frame f983 | Obturador del celular cuando el encuadre se estabiliza (f977-988), antes de bajar el teléfono |
| 00:00:42:13 → 00:00:42:18 | Portón eléctrico bajando y cerrando | **Portón eléctrico** (`fol.tailgate_close`, motor_s=1.33, latch=true) · FOL -10 dB · sync frame f1021 | Portón eléctrico: motor desde f989 (empieza a bajar) y cierre en f1021, en la micro-pausa VO 42.50-42.62 |

### 42.58-43.92 TÚNEL (hueco VO 42.85-43.49)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:42:13 → 00:00:44:02 | Túnel: EX5 hacia la salida, spray | **Túnel** (`amb.tunnel`, fans=0.4, drip=0.2) · AMB -14 dB · sync cut f1022 | Túnel oscuro: ventiladores, goteo, reverb larga; L-cut 4 cuadros en el destello blanco |
| 00:00:43:09 → 00:00:44:02 | Túnel: EX5 hacia la salida, spray | **Pass-by en túnel** (`veh.tunnel_passby`, speed_kmh=50, wet=true) · VEH -10 dB · sync frame f1041 | EX5 cruza el túnel de izquierda a derecha, más cercano en f1041 |
| 00:00:42:23 → 00:00:44:02 | Túnel: EX5 hacia la salida, spray | **Golpe de agua** (`veh.water_splash`, intensity=0.8, space=tunnel) · VEH -9 dB · sync frame f1031 | La rueda pisa el agua (primera nube de spray f1031) dentro del hueco sin locución |

### 43.92-46.83 PLACA FINAL: nada (la música manda)

_Sin sonido agregado._


### 46.83-48.58 REMATE: PANDA EN CALLE VACÍA DE DÍA (sin música)

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:46:16 → 00:00:49:17 | REMATE: panda en calle vacía de día | **Calle vacía de día** (`amb.empty_city_day`, traffic=0.25, birds=1, wind=0.2) · AMB -8 dB · sin protección VO (hueco) | Calle vacía de día: tráfico muy lejano, brisa; entra 4 cuadros antes del corte y baja 5 dB en el EX2 |
| 00:00:46:21 → 00:00:48:17 | REMATE: panda en calle vacía de día | **Pasos de panda** (`cre.panda_steps`, surface=dry_asphalt, weight=1.0, step_times=[0.0, 0.4583, 1.4583]) · FOL -11 dB · envío city_day_street -14 dB, sin protección VO (hueco) · sync frame f1125 | Pasos medidos en el contacto con el suelo: trasera f1125, trasera lejana f1136, delantera f1160 |
| 00:00:47:18 → 00:00:48:13 | REMATE: panda en calle vacía de día | **Respiración de panda** (`cre.panda_breath`, type=sniff, close=false) · FOL -11 dB · envío city_day_street -14 dB, sin protección VO (hueco) · sync frame f1146 | Un olfateo a media distancia entre el segundo y el tercer paso |
| 00:00:47:02 → 00:00:48:18 | REMATE: panda en calle vacía de día | **Gorriones** (`cre.small_birds`, count=2) · FOL -18 dB · sin protección VO (hueco) · sync frame f1130 | Gorriones en los árboles de la vereda derecha, escasos |

### 48.58-49.71 EX2 MOJADO EN PRIMER PLANO -> CORTE A SILENCIO

| TC (24 fps) | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:48:14 → 00:00:49:17 | REMATE: EX2 mojado en primer plano | **Gotas sobre carrocería** (`fol.droplets`, rate=5.0, surface=metal) · FOL -12 dB · sin protección VO (hueco) · sync cut f1166 | Gotas que escurren sobre el capó mojado, muy cerca |
| 00:00:48:13 → 00:00:49:17 | REMATE: EX2 mojado en primer plano | **AVAS EV en reposo** (`veh.avas_idle`, level=0.4) · VEH -11 dB · sin protección VO (hueco) · sync cut f1166 | AVAS del EX2 cercano, faros encendidos; corte duro a silencio en 49.708 s |

## Notas de spotting (imagen = verdad)

- **Pasos del panda (6.63–7.46)**: el contacto con el suelo se midió en la imagen. La pata trasera cercana apoya en f168 y la lejana en f174. No hay más apoyos visibles en el plano.
- **Pata en el parabrisas**: la pata ya está apoyada en el primer cuadro (f179), así que el thump va en el corte. El deslizamiento visible hacia f184 coincide con `press_ms: 210` (chirrido).
- **Paso de rueda (13.0)**: hay un sub-corte en f308. El punto más cercano es f312. Sobre el reveal de focos (13.5) no se agrega nada.
- **Selector (31.0)**: la mano aparece en el sub-corte f747 y el detent va en f748, apenas abre el plano. La mano no toca el selector en cuadro; el clic se lee como el selector de cristal de la consola.
- **Portón (41–42.6)**: el portón empieza a bajar en f989 y sigue en movimiento hasta f1021, así que el cierre va en el último cuadro antes del túnel. Cae justo en la micro-pausa de locución 42.50–42.62 s.
- **Ruta con montañas (36.33–36.88)**: es asfalto, no nieve. El EX2 pasa pegado a cámara de derecha a izquierda (f879–883), así que va un pass-by seco en lugar de "rodado en nieve". La nieve queda en el plano anterior (spray f859).
- **Pantalla (38.54–39.92)**: ningún dedo la toca, así que no lleva `fol.screen_tap`.
- **Remate**: el contacto con el suelo se midió en la imagen. Trasera f1125, trasera lejana f1136 (rueda del talón al dedo hasta f1145) y delantera f1160.
- **Tomas elegidas (`seed`)**: en los pass-by lentos o lejanos se eligió la toma cuyo pico de energía cae a ±1 cuadro del sync. En el goteo de la apertura se eligió la toma con menos resonancia sostenida: la receta `amb.drips` tiende a dejar un tono de 2–3 kHz sonando.

## Verificación (render sin mezcla, 69 de 78 cues; faltan las 9 recetas de foley, todavía no implementadas)

- Sync medido de transientes y picos: todos a ±1 cuadro.
- Locución: un 5 % de las celdas de tercio de octava (250 Hz–5 kHz) queda a menos de 6 dB del bed durante la voz. Casi todas son huecos del propio bed, con una mediana de −60 dB frente a −45 dB típicos.
- Remate: unos −25.8 LUFS sin las gotas (objetivo ≈ −24 con `fol.droplets`). Pasos con pico ≈ −16 dBFS. Silencio digital después de 49.708 s.
- Las camas de cabina del LED/parlante y de la pantalla quedan casi inaudibles bajo música y voz, por diseño ("solo aire de cabina").
