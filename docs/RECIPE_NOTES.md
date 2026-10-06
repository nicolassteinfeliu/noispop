# Notas de uso de las recetas (de los autores de cada familia)

Generado desde los resultados de la fase 1. Niveles: event = pico -6 dBFS, bed = RMS -20 dBFS antes de gain_db.

## vehicle.py
### Consejos de uso
LEVELS AFTER NORMALIZATION. Events are normalized to -6 dBFS peak, but their RMS differs a lot:
- approach, wheel_spin, gravel: about -24 to -27 dBFS RMS
- pass-bys, wet_glide: about -26 to -30
- tunnel_passby: about -30
- snow_spray: about -33 (crest ~27 dB)
- water_splash: about -34 to -36
So spray and splash can take hotter gains: -4..-8 even under VO, -2..-4 in VO gaps.
In context at -10 dB under VO, events sit ~15-26 dB below the bed per band (averaged over the window), so the vehicle cues read mainly in VO gaps or at -4..-8 dB. What carries over the bed is 5-10k sizzle and spray, onsets, and stereo motion.

BEDS (RMS -20).
- onboard_roll: -14..-20 under VO.
- ev_drive: -16..-22.
- avas_idle: -10..-14 in the exposed remate. It is tonal and peaks around -10.8 dBFS.

SYNC AND DURATIONS (sync placement for pass-bys and approaches is already exact).
- passby: sync = closest-approach arrival. dur 1.6-3 s. peak_pos sets the approach/recede asymmetry.
  - 13.0 wet: surface wet, closest 2-4.
  - 16.5 rock arch: dry, space rock_arch, send_db -10.
  - 31.6 forest: dry, space forest.
- approach: put `at` on the cut. dur = how much lead-in you want (0.6-1.2 s). meta.start_m gives the real start distance. It is honored when reachable within 0.85-1.25x speed; otherwise the car starts closer.
- wheel_spin: at 1.21, dur 1.55, darken_at 0.51 (goes dark at ~2.0 s).
- wet_glide: at 13.0, dur 1.5-2.5.
- gravel_curve: at 16.0 (apex), dur 1.2-1.6.
- snow_spray: at 36.0. The audio starts lead_s (0.25 s) before `at`. dur 1.4-2 for the falling particles.
- water_splash: at 43.0 with speed_kmh 60, matching the tunnel pass-by so the rear-wheel splash lands +0.165 s. The tunnel tail runs ~3-4 s.
- tunnel_passby: at 43.0, dur 2. The IR tail runs ~4.5 s, so use fade_out/until if needed.

EV CHARACTER AND KEY.
- The default EV whine is physically subtle under tire roll (order 8 at about -16 dB). Use ev 1.0-2.0 on pass-bys, or ev_drive with whine 0.7-1, for an audible "electric" signature.
- AVAS is only active below 20 km/h.
- Interior perspective makes the whine 2.2x more present.
- All tonal content is in key: orders snapped to Ab/Bb/Db/Eb, AVAS Eb4, hum Bb3, inverter carrier Bb8.

CPU: about 0.8-2.4 s per 10 s of output audio.

### Parámetros extra
All catalog params are kept; added optional ones only. passby: peak_pos 0.5, aero 1, wetness, body 0.5, space 'open_exterior', send_db -18, hp_hz 120. approach: lateral_m 1.2, height_m, tail_s 0.08, extra_rise_db 4 (designer exaggeration; 0 = pure physics), space, send_db, wetness. onboard_roll: ev 0.25, aero, joints 0.12/s, variation, wetness, space, send_db, tune. wheel_spin: surface, spokes 5, space 'underpass_concrete', send_db -24. ev_drive: tune, avas, mech, inverter, width 0.9. avas_idle: note 'Eb4', hum 0.5, breath_s 5, space, send_db. wet_glide: closest_m 2, direction, peak_pos, ev 0.12, space 'city_fog_street', send_db -14. gravel_curve: radius_m 14, closest_m 5, direction, peak_pos, ev, slip 1, space, send_db. snow_spray: lead_s 0.25, speed_kmh, direction, space, send_db. water_splash: lead_s 0.12, wet_db -12, direction, speed_kmh (sets rear-wheel timing), rear_wheel. tunnel_passby: closest_m 3, direction, ev, peak_pos, width_m, height_m, send_db -5. Every recipe takes hp_hz (120 default; 100 for splash and tunnel; the passby body layer goes to 70 Hz).

### Problemas conocidos
- The two tonal beds with intentional slow motion score max_autocorr ~0.75: ev_drive with accel (a 12 dB whine ramp, i.e. a trend) and avas_idle (slow irregular breathing). This is not looping: lag 1-2 s is low or negative and the high value comes from lag 0.1 s smoothness. Noise beds (onboard, interior, wet, far, ev cruise) score 0.13-0.27.
- click_candidates flags intended particle transients: gravel grains and cracks (10-32), snow spray ice and falling ticks (~80), splash drops (8-11). Wet noise beds also show ~8-16 statistical false positives per 6 s, which are Gaussian HF peaks I checked to be no audible clicks. No unintended edges: start/end samples sit below -99 dB of peak in every edge case.
- Pass-by events have L/R correlation ~0.06-0.3 because the mono source pans hard L->R. That is intended motion, not phasiness; bed correlations are 0.37-0.6.
- approach: start_m is a hint. The kinematics honor speed_kmh and end_m, and the start speed is limited to 0.85-1.25x. extra_rise_db=4 deliberately exaggerates the physical ~9 dB rise; set it to 0 for pure physics.
- Pass-bys with closest_m < 6 have an intentional body layer down to 70 Hz. water_splash and tunnel_passby use hp_hz 100. Everything else is high-passed at 120 Hz, 24 dB/oct.
- Reverb tails extend past dur: water_splash in tunnel ~4.5 s, tunnel_passby ~4.5 s, others 0.5-2.6 s. Shorten with cue fade_out/until if needed.
- sfx.audition.audition() imports every recipe module. If another agent's module is broken, the CLI audition fails; the vehicle __main__ block works around this by importing modules defensively (it does not edit their files).

## ambience.py
### Consejos de uso
Beds are normalized to RMS -20 dBFS, so loudness per dB of gain depends on spectrum. HF-centred beds (fog_air with centroid about 8.9 kHz, alpine about 2.5 kHz in the short shot) sound clearly louder at the same gain than LF beds (room_tone, city_distant, cabin, tunnel with centroids of 230-470 Hz). Use roughly 4-6 dB less gain on fog_air and alpine than on city, cabin and tunnel.

Context results (sfx_vs_bed is the SFX level minus the bed level in each band, measured over the window around the cue):
- room_tone underpass at 0.0, -14 dB: clearly audible from 0 to 1.0 s, where the bed's mids are empty. sfx_vs_bed is -15 to -16 dB in 150 Hz-2 kHz over the window (the VO enters at 1.0 s). dur 1.6, fade_out 0.3-0.4.
- city fog (5-12 s): city_distant at -18 is subliminal low-mid depth (-18 dB vs bed in 150 Hz-2 kHz). Pair it with fog_air at -18 to -20, which is what actually reads (air10k+ +1 dB, high5k-10k -11 dB vs bed). With passbys=1-2 you get slow swells of 2-6 s. tonal 0.3-0.5 gives a barely audible far whine.
- surf far: dur 2.5, crest_at 0.3, at 14.4, -12 dB puts the crash at about 15.15 s; mid500-2k reads at -9 dB vs bed. Use near or mid only for close shots; they include a 70 Hz thump.
- mountain_wind: -14 at 18.1 (dur 1.6) and 39.92 (dur 3). Go -10 to -12 in the VO gap 18.91-19.23.
- forest: -14 at 28.0 / 31.5, birds 1-2. Bird times are in meta.
- lake: -12 at 30.0 (VO gap 30.08-30.88). The first lap lands 0.08-0.45 s after start; mid500-2k reads at -8 dB vs bed.
- desert_wind: -12 at 25.3 (VO gap 25.47-26.43). The sand reads in 5-10 kHz.
- alpine: -14 to -16 at 36.2 (dur 0.8-1.2).
- cabin: -16 for 19.29-22.46 and 38.54-39.92. It is mostly glue under the VO; speed_kmh 60-80; pillar_wind 0.4+ only at highway speed.
- tunnel: -14 at 42.4 (dur 1.8-2); fans 0.5, drip 0.2.
- studio: -16 at 23.5.
- empty_city_day: -10 at 46.75-46.83 (fully exposed; target LUFS-S about -24 for A, -20 for B). Use fade_in >= 0.25 s, because the recipe itself only fades in over 12 ms. Chirps start 0.15-0.45 s after the cue start (times in meta). Seeds 0, 1 and 2 are all usable.
- birds_distant (event): raptor at -10 on 40.0 reads in 2-5 kHz (-5.5 dB vs bed); sparrow events read strongly in silence (+14 dB vs the empty bed). For underpass drips use -16 to -20; rate 0.6-1.0 reads as calm.

Durations: beds return exactly dur samples, in steady state from sample 0 (pre-rolled IRs and filters). birds_distant returns dur plus up to about 1.6 s of echo tail. Each recipe runs at or below 2.7 s CPU per 10 s at 10-20 s durations.

### Parámetros extra
All new parameters are optional with defaults. room_tone: motion=1.0 scales the AM depth; an unknown space falls back to underpass. city_distant: tonal=0.3 sets the probability and level of the distant tram/bus whine hint (only for dur > 2 s); space=None overrides the IR. drips: distance=0.5 (0 = near, 1 = far). surf: crest_s=None sets the crest envelope length (default clip(0.9*dur, 1.2, 3)); an unknown distance falls back to far. wind: space='open_exterior' and corr=0.6 (L/R gust correlation). mountain_wind: texture='grass'. tunnel: note='F3' sets the blade-pass note. studio: hum_note='Ab2'. birds_distant: space accepts valley_mountain|forest|city_day_street|none (default valley_mountain, or city_day_street for sparrow); distance=1.0 multiplies the distance range; species also accepts 'mixed'. cabin_still: exterior accepts city_fog|city_day|wind|forest|none.

### Problemas conocidos
- Click detector false positives: the audition click metric fires on plain band-limited Gaussian noise. I measured 27 hits in 7 s of noise band-passed to 4-8 kHz, 59 for 5-7 kHz and 0 for broadband noise. The few hits in fog_air, wind_none, wind_snow and empty_city_day are of this kind: ratios of 9.2-10.5 dB, never visible as transients. All other hits are intended transients: drips, surf foam, sand saltation, leaf and grass grains, lake bubbles and droplets, bird onsets. Pure beds (room_tone, city_distant, cabin, tunnel, studio) show 0-1.
- max_autocorr_0.1-5s is above 0.3 for gusty, wave or sparse beds by design: wind 0.55-0.68, mountain about 0.5, alpine_long 0.79, surf 0.6-0.9, drips 0.69, lake_long 0.46. The metric counts any slow intended modulation as repetition. A real loop check on 10 s renders shows no repetition: autocorrelation of the >1 kHz waveform at 0.1-5 s lags is 0.01-0.09 for every bed except drips (0.10-0.14, same-point drip sources), and the detrended envelope autocorrelation is at most 0.17.
- Sparse beds have a high crest. After the renderer's RMS -20 normalization, drips peaks reach -2 to +4 dBFS (crest 24-27 dB), and lake and surf-near peak around 0 dBFS. That is fine in the float pipeline once cue gain is applied, but the 24-bit audition WAVs can clip slightly.
- Short cues use an honest gust process (normalized over the full process, not the window), so a seed can open in a lull. For example forest_low at seed 0 rises about 10 dB over its first second. Level floors on body and texture limit this; otherwise pick another seed or use the cue fade_in.
- The studio lamp hum is tuned to Ab2 (103.8 Hz) instead of a literal 100 Hz, to respect the key rule. Wind whistles and tunnel and tram tones rest on key notes, but whistles glide with gust speed (Strouhal), so they pass through other pitches briefly.
- Shared DSP issues (for the orchestrator; I did not edit dsp.py). (a) dsp.make_ir gives early-reflection taps a random polarity per channel. With valley_mountain (0 dB taps) this produces anti-phase echoes on tonal events, which measured L/R correlation -0.3 on birds. I worked around it with a private _valley_echo. (b) The synthetic IRs decorrelate the bass as much as the treble; _finish narrows content below 280 Hz (width 0.45) to give realistic coherent bass. (c) dsp.random_walk and gust_env use direct np.convolve with very long kernels (0.75 s CPU for 3 s of audio), so I used private FFT-based control-rate modulators. (d) The Haas ITD in dsp.haas causes anti-phase on 3-7 kHz tones, so the birds use pure amplitude panning. Other families may hit (a), (c) and (d) too.
- I ran no git operations. My scratch tools are in /tmp/claude-0/-home-user-noispop/11ab7cc3-d330-5fae-b33e-90e3d4689931/scratchpad/amb/ because other agents overwrote files at the scratchpad root. Audition outputs (wav, png, json, including __ctx files) are in /home/user/noispop/out/audition/ambience/.

## creature.py
### Consejos de uso
Events are peak-normalized and in most of them a low body sets the peak, so perceived loudness differs a lot between recipes:
- Steps: the 70-150 Hz thud sets the peak. Under music + VO (crossing 6.63-7.46) use body_db -6 and gain -6 to -8. At the default body and -10 dB they sit ~22-26 dB under the bed average and do not read.
- Final stinger 46.83-48.58: surface dry_asphalt, distance mid, gain -4 to -8 (auditioned at -6, steps 6, gait 0.3). Prefer step_times from the picture. Output runs ~1.5-2 s past the last contact (lift-off plus street reverb).
- paw_on_glass: sync is the contact (aim ~7.6). Under VO use body_db -4 with gain -4 to -6: claw ticks, squeak and fur then show at 1-5 kHz. At -10 it is buried. Good ranges: press_ms 200-300, squeak 0.3-0.6. Contact sample is 50 ms into the buffer; the fur starts 10 ms before contact.
- panda_breath exhale (close breath, VO gap 10.27-10.94): dur 0.5-0.7 at ~10.3-10.35, gain -6 to -10 (it reads at 2-10 kHz at -8). Huff and sniff are perceptually louder than exhale at the same peak, so trim them 2-3 dB lower. Use `length` to force exhale length.
- panda_crowd (8.13-10.54): gain -14 to -18. At -16 it fills the bed's 2-8 kHz gaps (pres2k-5k about -9 dB vs bed average, low end nearly empty). Use distance far for back rows. `layers` (fur|presence|breath|steps) lets you solo or thin layers in sync. CPU is 1.5-2.3 s per 10 s.
- fur_rustle: 0.3-0.8 s, centroid ~4 kHz, reads at -12. intensity 0.8-1 gives vigorous movement.
- geese_flyover: dur 1-3 s. Sunroof perspective (through_glass 0.5) is very muffled under the dense bed at -10 (pres2k-5k about -29 dB vs bed). For readability use through_glass 0.2-0.35 or gain -6, or let the honks carry it (honks 1-2).
- small_birds: in the silent stinger they are very present (2-10 kHz is about +10 dB over the music tail at -14). As background sparrows use -16 to -22, count 2-4, dur 2-3.
- Recommended durations: steps = last step + 0.5; breath 0.5-0.8; paw 1.0-1.5; crowd any length (beds, no loop: autocorr < 0.3); geese 1-3; birds 2-4.

### Parámetros extra
panda_steps: distance(close|mid|far), space(auto|preset|none), side_spread, claws, fur, body_db, detail_db. panda_breath: length, count(sniffs), space, send_db. paw_on_glass: fur, body_db. panda_crowd: space, wet, layers. fur_rustle: brightness, space, send_db. geese_flyover: direction, space. small_birds: distance, space.

### Problemas conocidos
- The audition click detector flags the intended sub-events of each footfall: contact, pad grit/tack, scuff, claw and lift-off peel/scuff. That is about 4-6 per step (stinger: 28 for 6 steps). It also flags geese feather onsets (~20-30 per 1.6 s) and crowd shuffle onsets (~1-3/s). I checked by layer attribution and by comparing against plain noise bursts: these are micro-transients of the particle textures, not discontinuities. Truncated decays were fixed with explicit fades.
- Steps, breath and huff are point sources: L/R correlation is 0.86-1.0, and the only width comes from the street/cabin reverb. Use cue `pan` (curves allowed) to move the crossing panda across frame.
- Steps output is longer than dur: last contact + stance (~0.6-0.75 s lift-off) + reverb tail. Contacts placed by steps/gait_s at or beyond dur are dropped; step_times are never dropped.
- cues/recipe_catalog.yaml (not my file) fails yaml.safe_load at line 95: `fol.light_contactor:{kind...` needs a space after the colon. I verified my 7 recipes' kind/sync against the catalog with a regex instead; all match.
- Spectrograms show very faint (~-70 dBFS, ~50 dB under the chirps) low-frequency envelope sidebands under some sparrow chirps. They are inaudible and are removed further by the 120 Hz HP and the mix.
- Geese through the sunroof (through_glass 0.5) barely read under the dense bed at -10 dB. That is right for the perspective, but the spotter needs to raise gain or lower through_glass if they should be noticed.
- panda_crowd at density 1.5 uses ~2.3 s CPU per 10 s, near the 3 s budget. At density <= 1.0 it is <= 2.0 s.

## foley.py
### Consejos de uso
Everything is normalized to a -6 dBFS peak, so how loud a sound feels depends on its crest. Very peaky (crest 27-30 dB): phone_shutter, relay_click, gear_selector, droplets. Mid (crest 17-22 dB): led_fizz (~22), hands_wheel (~21), tailgate (~23). Dense (crest ~16-18 dB): suspension. In 10 ms windows at the spotter gains, the clicks sit about 0 to -12 dB against the bed in 2-10 kHz. They read as transients but are subtle. Suggestions: phone_shutter -8/-9 instead of -11. relay_click can stay at -15, it is meant to be barely there. gear_selector -9 is fine. light_contactor clack reads at -11. Its hum is masked under music below 800 Hz, so raise hum (0.7-0.9) for a more audible lamp. tailgate_close: at -10 the latch reads (+4 dB in 2-5 kHz) but the lowering motor sits ~-14 dB under the bed under VO. Use motor_db -3..-4 or gain -7 for an audible whir. The latch lands exactly at motor_s+10 ms, the motor starts 10 ms in, and the tail (valley echo taps at 310/540/860 ms) runs ~1.7 s past the latch, so 'until' trims it. droplets (exposed stinger, bed silent): -12 is delicate; -6..-8 brings the stinger toward the -24 LUFS target, and width 1.3 works (lr_corr 0.6-0.8). led_fizz lives above the bed's ~12.5 kHz ceiling and reads clearly at -19; its stereo is moderately wide (corr 0.5), and the pan curve works. hands_wheel: 1.0-1.5 s; at -14 under VO it sits around -22 dB in 0.5-5 kHz, so use -10 for presence. suspension is mostly felt (60-150 Hz); the mid knock gives the definition, use -12..-15. ped_signal dur 0.5 with count 1 is fine; its city_fog reverb is included at -9, so the cue's extra send -10 can be dropped or lowered. Suggested dur ranges: shutter 0.3-0.5, tailgate motor_s+0.3, gear 0.3-0.5, relay 0.1-0.3, contactor 1.2-2.0, droplets 0.5-3, suspension 0.4-0.7, tap 0.2-0.5, fizz 0.5-2, hands 0.8-2. Regenerate all auditions (25 renders, 11 with --at context, 2+ seeds for key recipes): python -m sfx.recipes.foley [tag-filter ...]. Output goes to out/audition/foley/.

### Parámetros extra
All optional with defaults; every recipe also takes **_. phone_shutter: gap_ms, space, send_db. tailgate_close: cinch_s=0.3, distance_m=4, space=valley_mountain, send_db=-18, motor_db=-6 (motor level relative to the latch peak), tune=True (steady motor pitch snapped to Ab2/Bb2/Db3, mesh orders 6/8 or 8/12, cinch a fifth up, rewind an octave up). gear_selector: second=True, second_ms, space, send_db; style also takes 'column'. ped_signal: distance_m=18, space=city_fog_street, send_db=-9, tune=True (tone modes become Bb5 932 Hz + F7 2794 Hz). relay_click: space, send_db=-24. light_contactor: hum_hz=103.83 (Ab2), hum_s=1.5, arc=0.4, space=studio_stage, send_db=-10. droplets: trickle=0.5, spread=0.7, space=city_day_street, send_db=-24, first_s; surface takes metal or glass. suspension: double=True, speed_kmh=50, wheelbase_m=2.75, space, send_db. screen_tap: count=1, space, send_db. led_fizz: ramp=0.35, density=1.0, hp_hz=7500 (clamped 6-12k), pops=5, corr=0.5. hands_wheel: slides=2, grip=True, intensity=0.5, space, send_db.

### Problemas conocidos
- The audition click detector flags noise textures as candidates: tailgate seed 0 at 0.047/0.06/0.12 s from the gas-strut hiss (narrowband Gaussian peaks, ~8-9.5 dB local crest at -12 to -17 dB re peak, no discontinuities); droplets (53-76), led_fizz (51-59) and hands_wheel (23-24) from intended grains or crackle. Every other listed time is an intended transient: clicks, bounces, cabin early reflections ~5 ms after the attack, tap lift, latch secondary detent.
- Key-safety deviations from the literal brief, on purpose: the lamp hum defaults to Ab2 103.83 Hz instead of 100 Hz, with harmonics 5 and 7 attenuated; ped_signal tone modes default to Bb5 932 Hz + F7 2794 Hz instead of 1000/2700 Hz; the tailgate motor's steady pitch and mesh orders are snapped to safe notes. Pass tune=False or hum_hz=100 for the literal values. Short percussive modal clicks (gear, shutter, relay, latch) are left untuned (inharmonic, jittered).
- tailgate_close: the low end of the motor is HP'd at 120 Hz, and only the latch body thud goes down to 70 Hz. The lowering whir is physically quiet next to the latch peak (motor_db -6), so it is mostly masked under VO at the spotted -10 dB.
- Long-tail recipes (light_contactor, ped_signal, tailgate_close) return buffers of 2.3-3.1 s because of reverb tails (studio_stage RT ~2.2 s, valley echoes, city_fog_street). Cues should use until/fade_out as option A already does.
- Spotting A notes say no finger touches the screen at 38.5-39.9 s, so fol.screen_tap is implemented and auditioned at 39.0 s but not used in option A. fol.hands_wheel is also not in option A yet; it was auditioned at 20.0 s.
- Event-to-event variation is deliberately moderate for tightly specified mechanisms: seed-to-seed waveform correlation is 0.46-0.64 for relay/tap/suspension/tailgate and near 0 for textures. Each event is re-synthesized from the rng (frequency +-2-5 %, tau +-15-20 %, gain +-1.5 dB, timing jitter).

## python
### Consejos de uso
Levels after renderer normalization (events peak -6 dBFS):

- **Sustained, loud for their peak:** ev_motif (RMS -17..-20), sub_impact (-21), awakening/logo (-22), glints (-22..-24), reverse_swell bell (-23).
- **Peaky, quieter:** soft_impact (-29..-32), light_shaft (-30), whoosh (-27..-30), wind_swell (-27..-31), spatial_bloom (-28). These need about 3-6 dB more gain_db for the same loudness.

Readability over the bed, measured in a window around the sync, mid and side separately:

- **Air whoosh, glints, LED sweep, mist, light shaft, wind swell, breath:** read mainly in the free stereo sides and 2-16 kHz, even at -12..-19 under VO.
- **Body / deep / flutter whooshes and spatial_bloom:** energy sits in dense bands, so use -8..-11 in VO gaps.
- **ev_motif under VO at -12:** sits about 5 dB under the bed in low-mids and side mids. That is a subtle, felt layer; raise to -8..-10 if the brand signature must be clearly heard. `presence` (default 1.0) adds octave partials 8/16 for readability; 0 gives the literal 1,2,3,4,6 stack.

Durations and tails:

- **whoosh:** 0.5-1.6 s. Tail ≈ dur + 0.25 + 0.6*tail; sync = measured peak ≈ peak_pos*dur.
- **reverse_swell:** 0.7-1.5 s; `beats` (2 or 3) overrides dur. Notes are snapped to the key; source 'bell' for tonal transitions, 'noise' for an inhale.
- **riser:** 1-2.5 s; it lands on Bb exactly at `at`.
- **glint:** decay 0.7-1.4. With delay the audio runs about 3.2*decay + 2.3 s, so use cue fade_out/until.
- **led_sweep:** dur = LED travel time; count 8-12.
- **ev_motif:** rise needs dur ≥ 1.6 s (glide_at default 0.42*dur, glide 0.8 s, both overridable). resolve adds a 1.4 s bloom tail; cut it with until.
- **light_shaft:** 1.5-2.5 s.
- **logo_signature:** 2.5 s; resolves on Bb at resolve_at = 1.017 s.
- **awakening:** 1.2 s with about 1.2 s of tail; the cue's until at 49.708 cuts it.
- **ui_tone:** 0.4-0.8 s.
- **breath_designed:** 0.8-1.4 s.
- **wind_swell:** 1.2-2 s.
- **drone / mist_texture:** any length; beds RMS -20, no loop.

Layer doubling in option B:

- **48.583:** B700 awakening already contains a low bloom (F1, LP 80) and a motif resolve, while B710 sub_impact and B720 ev_motif resolve are also there. To avoid doubling, use awakening params sub≈0.3-0.4, motif≈0.3 (or 0), or drop B720.
- **44.042:** logo_signature has its own Bb1 sub bloom (`sub`, default 0.6) alongside B640 sub_impact. Use sub 0.3 if B640 stays.

Other:

- **drone:** for the music-free stinger, set hp_hz 40-50 and sub 0.6-0.9 to let the Bb1 fundamental speak; the default HP 70 keeps it implied under the kick.
- **sub_impact:** fundamental capped at 45 Hz; layers above 140 Hz go to the hall/transient. On the SUB bus (LP 100) only the clean pitch-dropping sine plus its tanh 3rd harmonic (≈ 102-114 Hz, partly attenuated) remain.
- **CPU:** ≤ 2.6 s per 10 s of rendered audio. Worst cases are light_shaft (about 1.1 s for a 2 s cue) and awakening (about 0.7 s).

### Parámetros extra
whoosh: note, tone, comb, reverb_db, tail, rot_hz | sub_impact: drive, hall_db, transient | reverse_swell: beats, brightness, wet_db | riser: center, octaves, brightness | glint: index, space_db | led_sweep: start_note, fizz, grain_decay, accel | ev_motif: glide_at, glide_s, grain, whistle_db, presence, space_db | light_shaft: sweep_s, f_top, f_bot, pad, sparkle | mist_texture: corr, peaks | drone: sub, motion, hp_hz | spatial_bloom: note, brightness, chord | logo_signature: sub, shimmer, resolve_at | awakening: sub, glass, drops, motif | ui_tone: decay, echo | breath_designed: pitch, blur, peak_pos, size | wind_swell: peak_pos, whistle

### Problemas conocidos
- cues/recipe_catalog.yaml (orchestrator-owned) does not parse with yaml.safe_load: lines 95 `fol.light_contactor:{` and 141 `des.breath_designed:{` lack a space after the colon (ScannerError). Anything that loads the catalog as YAML will fail; I did not edit it.
- dsp.make_ir (orchestrator-owned) builds tails by summing LP/BP/HP band splits of one noise with different decays. This leaves visible notch lines in every reverb tail at about 400 Hz and 4-5 kHz (seen in my first auditions and likely in other families). I worked around it with a private STFT-based IR generator (_smooth_ir), including a 'designed_hall' replica with the same RT 5/5/3.5 s, 35 ms predelay and corr 0.05 as dsp.ir_preset('designed_hall'). The catalog's 'designed_hall' sends therefore use this replica, not the dsp preset itself. Fixing dsp.make_ir would help the other families.
- des.drone max_autocorr_0.1-5s is 0.8-0.9, above the 0.3 bed target. This is inherent to a tonal drone with beating partials: the metric's 0.1 s lag sees the smooth, slowly beating envelope. It is not looping: beat rates are random per partial (0.06-0.45 Hz) and drift ±20 %, with independent gain drifts. Long-lag (1-5 s) envelope autocorrelation is about 0.2-0.56 depending on seed. des.mist_texture meets the target (0.14-0.20).
- The audition click detector flags about 1-1.5 candidates/s in des.mist_texture and a few in whoosh/soft_impact tails and the riser end. I inspected them: all sit right at the 9-10 dB threshold with sample-difference ratios of only 3-7, i.e. Gaussian band-noise envelope peaks, not discontinuities (plain band-limited noise also triggers 0-3 per 6.7 s). Flutter (19) and glint/light_shaft/led candidates are the intended feather crackle, sparkle grains and ping-pong repeats of the glass tick.
- Ratio-3.5 glass FM (glint, led_sweep grains, awakening glass bloom, logo cluster) inherently puts inharmonic sidebands on out-of-collection pitch classes at ≤ -16 dB relative to the strongest peak. This is the spec'd glass timbre; all fundamentals, bell partials, motif/drone/pad partials and tonal targets are in Bb Db Eb F Ab (C only as the light_shaft add9). The ev_motif resolve keeps a residual C (3rd partial of F) at about -17 dB. A user-requested glint ratio of 1.4 gives out-of-key sidebands; the default reverse_swell bell no longer uses ratio-1.4 FM, apart from a 25 ms strike at -14 dB.
- ev_motif presence>0 (default 1.0) adds octave partials 8 and 16 to the catalog's 1,2,3,4,6 stack, for mix readability. They are octaves, so always in key; set presence=0 for the literal spec.
- whoosh body/deep/air have L/R correlation about -0.04 to 0.16 over the whole event (moving hard-panned source plus blooming independent-noise side). They are events, not beds; there is no polarity cancellation, and the mono sum loses only about 3 dB at the bloom. The deep style's width was reduced to limit wide lows.
- Tails extend well beyond dur for glints with delay (up to about 5.5 s rendered), motif resolve (about 3.9 s), logo (about 4.1 s) and soft/sub impacts (3.7-4.5 s), with long fades. Cue fade_out/until should define the useful end. Events with sync=end (reverse_swell, riser, air_suck) end exactly on the last sample and have no tail by design.
