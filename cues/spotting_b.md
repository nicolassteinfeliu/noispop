# Spotting — Opción B «Cinemática / Sensorial» (Geely EX2 / EX5)

**Intención sonora.** La opción B trata la imagen como una experiencia sensorial antes que como un registro: en lugar de ambientes literales, el mundo se construye con aire y niebla diseñados que ocupan los lados del estéreo (el bed es casi mono) y dejan libre el centro para la locución. Cada revelación de luz —el faro que despierta, la firma roja de los focos traseros, el haz cenital sobre el EX5, la tira LED, la salida del túnel— recibe un gesto propio: swell reverso que inhala hacia el corte, impacto suave o sub (siempre entre bombos, debajo de su fundamental) y brillos tonales en las notas seguras del tema (Bb, Db, Eb, F, Ab). Un motivo de marca, el «EV hum» en Bb, aparece cinco veces (0.0 apenas insinuado, 3.96 en ascenso con el faro, 9.42 como recuerdo, 23.63 completo bajo el haz) y resuelve Bb→F en el despertar final del EX2. Los movimientos de cámara se acompañan con whooshes de aire, cuerpo o tonales que siguen la dirección del movimiento; los pandas son míticos (pisadas secas con aura de hall diseñado). Contención bajo la locución (protección *strong* en todo lo de medios densos) y generosidad en los huecos sin VO y en el remate, que es puro diseño: aire diurno, pisadas cuadro a cuadro, un resoplido, el despertar y corte seco a silencio en 49.708 s. Nunca motor de combustión.

Convenciones: TC = HH:MM:SS:FF a 24 fps del punto de sync del cue (pico de un whoosh, final de un swell reverso, transiente de un impacto, inicio de una cama). Nivel = bus y `gain_db` sobre la normalización de la receta (eventos a pico −6 dBFS, camas a RMS −20 dBFS). Frames verificados sobre `media/picture.mov` (tiles en `out/spot_b/`).

| Momento héroe | TC | Gesto |
|---|---|---|
| Héroe 1 — faro despierta | 00:00:03:23 | swell reverso F4 → sub (3.958, entre bombos) + motivo *rise* + brillos F6/Bb6 |
| Héroe 2 — focos traseros GEELY EX2 | 00:00:13:07 | swell reverso Db5 → impacto suave + brillo Db7 (hueco VO) |
| Héroe 3 — haz de luz sobre el EX5 | 00:00:23:15 | swell reverso de ruido → light shaft + sub (bombo+0.156) + motivo completo |
| Héroe 4 — tira LED | 00:00:26:08 | granos tonales Bb5→Bb6 de izquierda a derecha |
| Héroe 5 — salida del túnel / logo | 00:00:43:22 | riser Shepard + agua + whoosh de salida → firma de logo + sub |
| Remate — despertar del EX2 | 00:00:48:14 | pisadas míticas → swell → despertar + sub + motivo resuelve Bb→F, corte seco |

## 0.00-1.21 APERTURA: PASO BAJO EN NIEBLA (hueco VO 0-1.15)

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:00:00 | Paso bajo en niebla al amanecer, EX2 con faros | `des.mist_texture` (brightness=0.45) — Niebla diseñada muy ancha (los lados del bed están libres) [AMB -13 dB] | abre el mundo sin literalidad; cola L-cut de 4 cuadros sobre la rueda |
| 00:00:00:02 | Paso bajo en niebla al amanecer, EX2 con faros | `des.ev_motif` (gesture=swell, root=Bb2) — Motivo EV (Bb2) entrando casi inaudible [DES -17 dB] | primera aparición de la firma de marca junto al EX2 encendido |
| 00:00:01:05 | Paso bajo en niebla al amanecer, EX2 con faros → corte 29 | `des.reverse_swell` (source=bell, note=Bb4) — Campana Bb4 en reversa que termina exacto en el corte 29 [DES -10 dB] | aspira la apertura hacia la rueda |

## 1.21-2.33 RUEDA GIRANDO (va a oscuro f52-56)

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:01:14 | Rueda girando (oscurece f52-56), torres desde f57 | `des.whoosh` (style=spin, direction=1, brightness=0.5) — Whoosh 'spin' con pico cuando la cámara entra al centro de la llanta (f38) [DES -14 dB] | el giro como gesto, no como rodado |
| 00:00:01:17 | Rueda girando (oscurece f52-56), torres desde f57 | `des.glint` (note=F6) — Brillo F6 sobre el primer destello naranjo que cruza la llanta [DES -16 dB] | tonal y en la tonalidad (Db/Bbm) |
| 00:00:01:23 | Rueda girando (oscurece f52-56), torres desde f57 | `des.glint` (note=Ab6) — Segundo brillo Ab6 en el último destello antes de oscurecer, con eco a tempo [DES -17 dB] | cierra el gesto de la rueda |
| 00:00:02:06 | Rueda girando (oscurece f52-56), torres desde f57 | `des.air_suck` (brightness=0.4) — Aspiración reversa que termina en el cuadro más oscuro (f54) [DES -12 dB] | la imagen se 'traga' la luz antes de las torres |

## 2.33-3.96 TORRES / EX2 DE FRENTE / PASO ELEVADO (hueco VO 2.59-3.39)

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:02:18 | EX2 de frente, quieto | `des.whoosh` (style=air, direction=1, brightness=0.6) — Whoosh de aire L->R con pico en el corte 66 (torres -> EX2 de frente) [DES -9 dB] | acompaña el contrapicado veloz, en el hueco de VO |
| 00:00:03:03 | EX2 de frente, quieto → corte 76 | `des.whoosh` (style=air, direction=-1, brightness=0.5) — Whoosh R->L al corte 76 (EX2 -> paso elevado), pico llevado al bombo 3.128 (0.94 cuadro antes) [DES -9 dB] | corte y música respiran juntos |
| 00:00:03:23 | Paso elevado, EX2 avanza hacia cámara → corte 95 | `des.reverse_swell` (source=bell, note=F4) — Campana F4 en reversa mientras el EX2 llega a cámara, termina en el corte 95 [DES -12 dB] | inhala hacia el HÉROE 1 |

## 3.96-5.17 HÉROE 1: FARO DESPERTANDO EN LA NIEBLA

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:03:23 | Faro despertando en la niebla | `des.sub_impact` — Sub con caída de pitch en el corte al faro (3.958, entre bombos 3.629 y 4.145) [SUB -8 dB] | peso del despertar, debajo del bombo |
| 00:00:03:23 | Faro despertando en la niebla | `des.ev_motif` (gesture=rise, root=Bb2) — Motivo EV en gesto 'rise' (Bb->F) desde el corte; florece en el hueco 5.25-6.59 [DES -12 dB] | la firma de marca 'despierta' con el faro |
| 00:00:04:04 | Faro despertando en la niebla | `des.glint` (note=F6) — Brillo F6 en el pulso de luz del faro (f100) [DES -12 dB] | el bloom de la luz se oye como vidrio |
| 00:00:04:10 | Faro despertando en la niebla | `des.glint` (note=Bb6) — Brillo Bb6 en el segundo pulso (f106) [DES -15 dB] | completa el acorde F/Bb del bloom |

## 5.17-8.13 POV / PANDA CRUZANDO / PATA EN EL PARABRISAS

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:05:01 | POV por el parabrisas: panda cruzando lejos, semáforo rojo (entra 3 cuadros antes del corte 124) | `des.drone` (note=Bb1, brightness=0.25) — Dron Bb1 muy discreto, J-cut de 3 cuadros [AMB -21 dB] | suspensión mítica ante el panda en la niebla |
| 00:00:05:10 | POV por el parabrisas: panda cruzando lejos, semáforo rojo | `cre.panda_steps` — Tres pisadas lejanas con hall diseñado en el hueco de VO 5.25-6.59 [FOL -14 dB] | el panda lejano (izquierda) se 'siente' antes de verlo cerca |
| 00:00:06:16 | Panda caminando frente a los faros | `cre.panda_steps` — Pisadas estilizadas: mano delantera f160, pata trasera f168.6, con envío a hall -14 dB [FOL -11 dB] | peso mítico, secas pero con aura |
| 00:00:07:11 | Panda caminando frente a los faros → corte 179 | `des.reverse_swell` (source=bell, note=Ab4) — Campana Ab4 en reversa hacia el corte 179 [DES -14 dB] | lead-in al contacto de la pata |
| 00:00:07:11 | Pata del panda en el parabrisas (POV interior) | `cre.paw_on_glass` — Pata contra el parabrisas desde dentro (ya apoyada en el cuadro 179; desliza hacia arriba f180-186) [FOL -10 dB] | contacto íntimo con la criatura |
| 00:00:07:11 | Pata del panda en el parabrisas (POV interior) | `des.glint` (note=Db7) — Brillo de vidrio Db7 muy suave sobre el contacto [DES -18 dB] | el vidrio 'canta' apenas, estilizado |

## 8.13-14.58 FILAS DE PANDAS / EX2 / PERFIL / DESLIZAMIENTO (niebla continua)

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:08:00 | Filas de pandas en la niebla (entra 3 cuadros antes del corte 195) | `des.mist_texture` (brightness=0.5) — Textura de niebla ancha continua desde las filas de pandas hasta el semáforo (cruza con el dron) [AMB -19 dB] | misma calle, mismo aire |
| 00:00:09:10 | EX2 avanzando entre los pandas | `des.ev_motif` (gesture=swell, root=Bb2) — Insinuación del motivo EV en el corte al EX2 entre los pandas (9.417) [DES -16 dB] | recuerda la firma sin protagonismo |
| 00:00:10:16 | Perfil del panda, luces rojas detrás | `des.breath_designed` — Respiración difuminada con reverb, pico en f256, dentro del hueco VO 10.27-10.94 [DES -9 dB] | el panda de perfil respira como un ser mítico |
| 00:00:12:21 | EX2 deslizándose / rueda (f308) / focos traseros (f319) | `des.whoosh` (style=body, direction=1, brightness=0.4) — Whoosh de cuerpo: el EX2 se desliza y pasa la rueda cercana (sub-corte f308) [DES -12 dB] | movimiento sin motor, sólo masa y aire |
| 00:00:13:07 | EX2 deslizándose / rueda (f308) / focos traseros (f319) | `des.reverse_swell` (source=bell, note=Db5) — Campana Db5 en reversa hacia el reveal de focos traseros (sub-corte f319 = bombo 13.296) [DES -11 dB] | prepara el HÉROE 2 |
| 00:00:13:07 | EX2 deslizándose / rueda (f308) / focos traseros (f319) | `des.soft_impact` (brightness=0.5) — Impacto suave sin sub cuando aparece la firma luminosa 'GEELY EX2' (hueco VO 13.18-14.59) [DES -7 dB] | el reveal pesa sin ser trailer |
| 00:00:13:07 | EX2 deslizándose / rueda (f308) / focos traseros (f319) | `des.glint` (note=Db7) — Brillo Db7 con eco a tempo sobre la barra de luz roja [DES -9 dB] | la luz trasera se vuelve sonido |

## 14.58-19.29 AÉREO COSTERO / GRAVA / ARCO / HACES / VALLE

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:14:22 | Aéreo costero: acantilado y olas | `des.whoosh` (style=air, direction=1, brightness=0.45) — Whoosh de aire largo (1.6 s) que entra desde el semáforo y acompaña el deslizamiento del aéreo costero [DES -14 dB] | escala y altura |
| 00:00:16:12 | Arco de roca / ruta oscura (f404) / haces de faros (f418) | `des.whoosh` (style=deep, direction=1, brightness=0.3) — Whoosh profundo L->R con pico cuando el auto cruza el arco (16.5); arranca en la grava dentro del hueco 15.94-16.35 [DES -10 dB] | la roca resuena |
| 00:00:17:10 | Arco de roca / ruta oscura (f404) / haces de faros (f418) | `des.glint` (note=F6) — Racimo de brillos 1/3: F6 cuando aparece el haz (sub-corte f418, hueco VO 17.28-17.66) [DES -10 dB] | destello de faros sin sub |
| 00:00:17:19 | Arco de roca / ruta oscura (f404) / haces de faros (f418) | `des.glint` (note=Ab6) — Racimo 2/3: Ab6 cuando el destello empieza a florecer (f427) [DES -14 dB] | el destello crece por grados, sin golpe |
| 00:00:18:00 | Arco de roca / ruta oscura (f404) / haces de faros (f418) | `des.glint` (note=Db7) — Racimo 3/3: Db7 con eco a tempo en el máximo del destello (f432, 18.0) [DES -13 dB] | corona el destello y deja una estela |
| 00:00:18:22 | Valle con rayos de sol | `des.wind_swell` (brightness=0.45) — Swell de viento diseñado sobre el valle con rayos de sol, pico en el hueco VO 18.91-19.23; L-cut 4 cuadros al interior [DES -12 dB] | inmensidad |

## 19.29-23.63 INTERIOR RELAJADO / EX2 EN LA OSCURIDAD

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:19:04 | Interior: hombre manejando, sonríe (entra 3 cuadros antes del corte 463) | `des.drone` (note=Bb1, brightness=0.2) — Dron muy suave bajo el interior y el EX2 en la oscuridad; se corta en seco en el haz (567) [AMB -22 dB] | respiro y luego vacío antes del HÉROE 3 |
| 00:00:19:04 | Interior: hombre manejando, sonríe (entra 3 cuadros antes del corte 463) | `des.mist_texture` (brightness=0.3) — Aire suave (textura opaca) en el interior [AMB -23 dB] | cabina en calma, sin literalidad |
| 00:00:23:15 | EX2 de frente en la oscuridad → corte 567 | `des.reverse_swell` (source=noise, note=Bb4) — Swell reverso de ruido que nace en el hueco VO 22.34-22.78 y termina en el corte 567 [DES -10 dB] | inhalación hacia el haz de luz |

## 23.63-25.21 HÉROE 3: HAZ DE LUZ SOBRE EL EX5

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:23:15 | EX5 bajo el haz de luz cenital | `des.light_shaft` — Haz de luz: barrido 9->1.5 kHz + pad vítreo Bbm(add9) en el corte al EX5 [DES -8 dB] | la luz cenital se 'oye' bajar |
| 00:00:23:15 | EX5 bajo el haz de luz cenital | `des.sub_impact` — Sub en 23.625 = bombo 23.469 + 0.156 s (ventana libre) [SUB -7 dB] | peso del reveal del EX5 |
| 00:00:23:15 | EX5 bajo el haz de luz cenital | `des.ev_motif` (gesture=rise, root=Bb2) — Motivo EV completo (rise Bb->F) bajo el haz [DES -11 dB] | tercera aparición de la firma, la más clara |
| 00:00:25:10 | Ruta oscura, faros acercándose | `des.whoosh` (style=tonal, direction=0, brightness=0.5) — Whoosh tonal corto: los faros se acercan por la ruta oscura, pico en f610 [DES -12 dB] | llegada frontal, centrada |

## 25.46-28.08 DESIERTO / HÉROE 4 TIRA LED / PARLANTE

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:25:16 | Aéreo de desierto, roca en primer plano | `des.whoosh` (style=air, direction=-1, brightness=0.6) — Whoosh de aire cuando la cámara pasa rozando la roca (f616, sale por la izquierda), en el hueco VO 25.47-26.43 [DES -7 dB] | vuelo aéreo |
| 00:00:26:08 | Tira LED azul en el tablero | `des.led_sweep` — Granos tonales ascendentes que recorren la tira LED de izquierda (pilar) a derecha (fondo) durante el travelling f632-657 [DES -10 dB] | HÉROE 4, la luz como melodía |
| 00:00:27:11 | Parlante Flyme Sound | `des.spatial_bloom` — Pulso filtrado que florece en reverb ancha en el corte al parlante [DES -12 dB] | el sonido Flyme 'abre' el espacio |

## 28.08-33.75 BOSQUE AÉREO / EX5 / LAGO / SELECTOR / BOSQUE

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:28:14 | Aéreo de bosque con destello | `des.whoosh` (style=air, direction=1, brightness=0.5) — Whoosh largo sobre las copas, pico en el barrido más rápido (f686) [DES -13 dB] | vuelo rasante sobre el bosque |
| 00:00:28:23 | EX5 de frente con volcán nevado (entra 3 cuadros antes del corte 698) | `des.mist_texture` (brightness=0.35) — Cama de aire muy baja bajo EX5/lago/bosque, termina en el corte a ciudad [AMB -23 dB] | continuidad sin ambiente literal |
| 00:00:30:02 | EX5 de frente con volcán nevado | `des.whoosh` (style=body, direction=0, brightness=0.35) — Swell de cuerpo: el EX5 avanza hacia cámara con el volcán detrás (arranca en el corte 698) [DES -12 dB] | aproximación con masa |
| 00:00:30:15 | Lago al atardecer / mano y selector (f747) | `des.wind_swell` (brightness=0.5) — Swell de viento sobre el camino junto al lago, en el hueco VO 30.08-30.88 [DES -10 dB] | luz de atardecer, aire abierto |
| 00:00:31:05 | Lago al atardecer / mano y selector (f747) | `fol.gear_selector` (style=rotary) — Detent del selector cuando los dedos se acomodan (sub-corte f747, gesto en f749) [FOL -12 dB] | precisión táctil |
| 00:00:31:05 | Lago al atardecer / mano y selector (f747) | `des.ui_tone` (note=Eb7) — Tick tonal Eb7 sobre el detent [DES -16 dB] | el gesto mecánico se vuelve interfaz elegante |
| 00:00:33:07 | Bosque: contrapicado / EX5 de frente (f771), pasa a cámara (f799) | `des.whoosh` (style=body, direction=-1, brightness=0.4) — Whoosh de cuerpo R->L: el EX5 pasa rozando la cámara en el bosque (f799, rueda en f800) [DES -11 dB] | pass-by estilizado sin motor |

## 33.75-36.88 MONTAJE CIUDAD / NIEVE

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:33:18 | EX2 en ciudad: travelling (f810) / capó (f838) | `des.whoosh` (style=air, direction=-1, brightness=0.55) — Whoosh al corte 810: el EX2 entra por la derecha y barre hacia la izquierda en el travelling [DES -12 dB] | ritmo de montaje |
| 00:00:34:22 | EX2 en ciudad: travelling (f810) / capó (f838) | `des.whoosh` (style=tonal, direction=1, brightness=0.45) — Deslizamiento tonal sobre el capó (sub-corte f838) en el hueco VO 34.72-35.23 [DES -10 dB] | reflejos que se deslizan |
| 00:00:35:08 | EX2 de atrás junto al acantilado, destello | `des.whoosh` (style=air, direction=0, brightness=0.5) — Whoosh al corte 848 (EX2 de atrás junto al acantilado, destello) [DES -12 dB] | mantiene el pulso del montaje |
| 00:00:35:18 | EX2 en la nieve, spray de la rueda | `des.whoosh` (style=air, direction=-1, brightness=0.7) — Whoosh brillante al corte 858 (nieve) [DES -12 dB] | entra el frío |
| 00:00:35:18 | EX2 en la nieve, spray de la rueda | `veh.snow_spray` (direction=-1) — Spray de nieve de la rueda a nivel bajo (ya visible en el cuadro 858) [VEH -16 dB] | textura física debajo del brillo |
| 00:00:35:20 | EX2 en la nieve, spray de la rueda | `des.glint` (note=F7) — Chispas cristalinas F7 sobre la nube de nieve (f860) [DES -14 dB] | la nieve como cristal |
| 00:00:36:08 | EX2 de lado con montañas nevadas | `des.whoosh` (style=air, direction=1, brightness=0.5) — Whoosh L->R al corte 872 (EX2 de lado con montañas) [DES -12 dB] | último golpe de aire del montaje |

## 36.88-38.54 GANSOS / AÉREO DE BOSQUE

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:36:18 | Gansos por el techo panorámico (entra 3 cuadros antes del corte 885) | `des.mist_texture` (brightness=0.7) — Textura aérea brillante bajo los gansos (J-cut 3 cuadros, L-cut 4) [AMB -20 dB] | cielo frío y alto |
| 00:00:37:08 | Gansos por el techo panorámico | `des.whoosh` (style=flutter, direction=1, brightness=0.5) — Whoosh 'flutter' (aleteo diseñado, sin graznidos) sobre la bandada vista por el techo panorámico [DES -12 dB] | vuelo estilizado |

## 38.54-42.58 MAPA / TORRES DEL PAINE / FOTO / PORTÓN

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:39:02 | Interior EX5: pantalla con mapa | `des.ui_tone` (note=Ab6) — Tono UI suave Ab6 cuando la pantalla con el mapa entra en cuadro (f938) [DES -17 dB] | tecnología discreta |
| 00:00:39:11 | Interior EX5: pantalla con mapa | `des.ui_tone` (note=Eb7) — Segundo tono Eb7 cuando el mapa queda de frente (f947) [DES -19 dB] | respuesta, no alarma |
| 00:00:39:19 | Hombre de perfil frente a las Torres del Paine (entra 3 cuadros antes del corte 958) | `des.mist_texture` (brightness=0.4) — Aire de montaña diseñado y muy bajo bajo la foto y el portón; termina en el corte al túnel [AMB -23 dB] | continuidad |
| 00:00:40:04 | Hombre de perfil frente a las Torres del Paine | `des.wind_swell` (brightness=0.5) — Swell de viento ancho sobre las Torres del Paine (pico a mitad del plano f958-970) [DES -13 dB] | contemplación |
| 00:00:40:21 | Hombre fotografía el paisaje; portón bajando (f989-1021) | `fol.phone_shutter` (style=modern) — Obturador nítido del celular (f981, antes de que baje el portón) [FOL -10 dB] | el hombre captura el paisaje |
| 00:00:42:13 | Hombre fotografía el paisaje; portón bajando (f989-1021) | `fol.tailgate_close` — Portón eléctrico bajando desde f989 (motor 1.3 s, limpio y bajo) con cierre en f1021, un cuadro antes del túnel [FOL -15 dB] | lujo silencioso |
| 00:00:42:13 | Hombre fotografía el paisaje; portón bajando (f989-1021) | `des.soft_impact` (brightness=0.3) — Golpe suave diseñado bajo el cierre del portón [DES -17 dB] | cierre con peso, puntuación antes del túnel |

## 42.58-43.92 HÉROE 5: TÚNEL HACIA LA LUZ

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:43:00 | Túnel oscuro hacia la salida, spray de agua | `veh.water_splash` (direction=1) — Agua levantada por la rueda (spray visible desde f1030, pleno en f1032), en el hueco VO 42.85-43.49 [VEH -7 dB] | textura húmeda en el túnel |
| 00:00:43:22 | Túnel oscuro hacia la salida, spray de agua → corte 1054 | `des.riser` — Riser Shepard que nace sobre el cierre del portón y termina en la salida del túnel (43.917) [DES -12 dB] | tensión hacia la luz |
| 00:00:43:22 | Salida del túnel a blanco | `des.whoosh` (style=air, direction=0, brightness=0.7) — Whoosh de salida con pico en el blanco del corte 1054 [DES -9 dB] | la cámara atraviesa la luz |

## 43.92-46.83 LOGO GEELY

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:44:01 | Logo GEELY / geely.cl | `des.logo_signature` — Firma del logo (impacto suave + shimmer en Bb que resuelve) cuando el logo aparece (corte 1057); se apaga antes de 46.6 [DES -6 dB] | cierre de marca |
| 00:00:44:01 | Logo GEELY / geely.cl | `des.sub_impact` — Sub del logo: el bed tiene 16 dB menos de graves aquí y no hay bombo después de 43.163 [SUB -8 dB] | el logo 'aterriza' |

## 46.83-49.71 REMATE DISEÑADO (sin música)

| TC | Plano | Sonido | Por qué |
|---|---|---|---|
| 00:00:46:14 | REMATE: panda cruza una calle vacía de día (entra 6 cuadros antes del corte 1124) | `amb.empty_city_day` — Calle vacía de día, baja, J-cut de 6 cuadros (nace cuando termina la música); baja 4 dB en el despertar; corte seco en f1193 [AMB -14 dB] | luz de día |
| 00:00:46:14 | REMATE: panda cruza una calle vacía de día (entra 6 cuadros antes del corte 1124) | `des.mist_texture` (brightness=0.75) — Aire diurno estilizado (textura brillante y ancha) [AMB -16 dB] | el remate sigue en el registro diseñado |
| 00:00:46:20 | REMATE: panda cruza una calle vacía de día | `des.drone` (note=Bb1, brightness=0.3) — Dron Bb1 quieto bajo el panda [AMB -17 dB] | suspensión antes de la resolución |
| 00:00:47:00 | REMATE: panda cruza una calle vacía de día | `cre.panda_steps` — Pisadas míticas cuadro a cuadro: trasera f1128, trasera f1141, delantera f1145, delantera f1158; secas con hall diseñado interno (sin envío de cue para que nada suene después de 1193) [FOL -5 dB] | el panda camina como leyenda |
| 00:00:47:22 | REMATE: panda cruza una calle vacía de día | `cre.panda_breath` (type=huff) — Un único resoplido entre la 3ª y la 4ª pisada [FOL -9 dB] | presencia viva del animal |
| 00:00:48:14 | REMATE: panda cruza una calle vacía de día → corte 1166 | `des.reverse_swell` (source=bell, note=Bb4) — Campana Bb4 en reversa hacia el corte 1166 [DES -9 dB] | lleva el motivo a su resolución |
| 00:00:48:14 | REMATE: frente del EX2 mojado, faros | `des.awakening` — Despertar del EX2: bloom FM vítreo + gotas tonales + motivo que resuelve Bb->F en el primer cuadro del frente mojado [DES -4 dB] | clímax sensorial del remate |
| 00:00:48:14 | REMATE: frente del EX2 mojado, faros | `des.sub_impact` — Sub del despertar (decay 1.0 s para que llegue bajo al corte final) [SUB -6 dB] | peso del EX2 |
| 00:00:48:14 | REMATE: frente del EX2 mojado, faros | `des.ev_motif` (gesture=resolve, root=Bb2) — Motivo EV en gesto 'resolve' (Bb->F), quinta y última aparición; corte seco a silencio en 49.708 [DES -10 dB] | la firma de marca cierra el spot |

_Total: 80 cues. Cue sheet: `cues/option_b.yaml`._
