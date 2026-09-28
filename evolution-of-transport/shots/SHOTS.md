# Evolution of Transport — shot bible and generation prompts

25 s, vertical 1080×1920, 30 fps, no on-screen text. Seven shots, eight keyframes.
Every shot is generated **from its start keyframe to its end keyframe**, and the next shot
starts from that same end keyframe. The edit is then a hard cut on identical frames, so
each transformation happens inside a generated clip, never as a dissolve in the edit.

> **Reference video:** it didn't reach this session (no attachment and no file in the
> repo), so it hasn't been analysed. Everything below comes from the written brief. To
> match the reference's pacing and camera language, add the file to the repo (e.g.
> `evolution-of-transport/reference/`) and the analysis can be done frame by frame and
> this bible adjusted.

---

## 1. Pipeline

1. **Keyframes K0–K7.** Generate with an image model at 1080×1920 (or a larger 9:16 size).
   Make K0 from scratch, then make each next keyframe **as an edit of the previous one**
   ("same frame, same camera, same lighting, …"). That keeps horizon, anchors and grade
   locked. Save them to `public/keyframes/K0.png` … `K7.png`.
2. **Shots S1–S7.** Use an image-to-video model that supports **first- and last-frame
   conditioning** (start frame = Kn, end frame = Kn+1). Vertical 9:16, target length from
   the table below. Save to `public/clips/S1.mp4` … `S7.mp4`.
3. **Conform.** Upscale to 1080×1920 and 30 fps if the model outputs less. If the model
   can't produce a length close to the slot (retime must stay within 0.75–1.33×), either:
   - generate two adjacent shots as one clip (e.g. K0→K2 as a 5 s clip for S1+S2) and split
     it at the slot boundary:
     `npx remotion ffmpeg -i S1-S2.mp4 -t 3 -c:v libx264 -crf 12 S1.mp4` and
     `npx remotion ffmpeg -ss 3 -i S1-S2.mp4 -c:v libx264 -crf 12 S2.mp4`; or
   - regenerate at a length the model supports and adjust `sourceSec` in `manifest.json`.
4. **Check.** Run `npm run check`, then `npm run stills`, and review `out/review/`
   (the middle of each shot, plus 2 frames before, at and after every cut).
5. **Render.** `npm run render` → `out/evolution-of-transport.mp4` (H.264 + AAC).

## 2. Continuity rules (apply to every prompt)

**Screen direction.** Every vehicle faces and travels **left → right**. The camera is a
side-on tracking shot moving at the vehicle's speed. The vehicle stays roughly centred,
and the ground and background stream right → left. The **front of each vehicle is the
fixed anchor**, and new structure grows **backwards (to the left)** and around the
existing frame.

**Anchors** (x, y as % of frame width/height from top-left):

| Keyframe | Front wheel hub / nose | Rear hub / tail | Ground line | Camera height |
| --- | --- | --- | --- | --- |
| K0, K1 | stone wheel hub (62, 70), wheel Ø 26% width | — | y 77% | at hub height |
| K2 | velocipede front hub (62, 70), Ø 26% | rear hub (26, 71) | y 77% | hub height |
| K3 | motorcycle front hub (64, 71), Ø 22% | rear hub (22, 71) | y 77% | hub height |
| K4 | car front hub (76, 73), Ø 14% | rear hub (26, 73) | y 78% | low, 0.6 m |
| K5 | train nose tip (88, 66) | body exits frame left | guideway top y 72% | 3 m, level |
| K6 | jet nose (70, 42), front-¾ view | tail lower-left | clouds below y 70% | airborne, level with jet |
| K7 | spaceship (68, 30), rear-¾, climbing up-right | engine glow lower-left of ship | Earth limb across bottom 30% | chase camera |

**Lens and look.** 35 mm full-frame equivalent, f/2.8, 180° shutter: real motion blur on
background and spokes, wheels sharp at the hub. Shot on large-format digital cinema
camera, anamorphic-style soft highlight bloom, subtle film grain, shallow but not extreme
depth of field (the vehicle is fully in focus).

**Key light.** Sun from **frame right, behind the subject, about 30° high** through
S1–S5 (warm rim on the leading edges), then the high-altitude sun in S6–S7 from upper
right. Never flip the light side between shots.

**Wheels.** Rotation must match ground speed and run clockwise (for left-to-right
travel). The wheel count stays constant within a shot unless the prompt adds wheels.

**Human thread.** The person who pushes the stone wheel becomes the rider: prehistoric
man → 1860s velocipede rider → 1910s motorcyclist (leather cap, goggles) → driver seen
through the car's side window. From the train on, the people are inside and not
featured. Side profile only, small in frame, never a close-up face.

**Colour arc** (grade targets):

| Shot | Palette | Light |
| --- | --- | --- |
| S1 | ochre, amber, dust haze (#C8893E, #8A5A2B) | golden hour, 3500 K, heavy atmospheric dust |
| S2 | warm sepia, oiled wood (#7A5230), iron | same golden hour |
| S3 | desaturated warm, brass, leather, green-brown countryside | late afternoon, soft haze |
| S4 | steel grey (#6E7780), teal shadows, orange furnace/sodium accents (#E07A2E) | overcast industrial dusk, smoke-diffused sun |
| S5 | cool steel blue (#3E6C9A), glass, white LED | blue hour city, reflections |
| S6 | pale cyan sky (#9FD3F0) deepening to cobalt | bright high-altitude daylight |
| S7 | navy to black (#050B1E), Earth blue (#2A6FDB), engine cyan-white (#9FE8FF) | hard sunlight, deep space |

**Global negative prompt (add to every generation).** text, captions, letters, numbers,
logos, watermark, signature, UI, subtitles, split screen, frame border, cartoon, CGI
look, plastic, toy, miniature, tilt-shift, extra wheels, wheels spinning backwards,
floating wheels, melting geometry, warped limbs, extra fingers, distorted face, crossfade,
double exposure, jump cut, camera shake, fisheye, dutch angle, low resolution.

**Global style suffix (append to every prompt).** photorealistic, cinematic, 9:16
vertical, 35mm lens, 180-degree shutter motion blur, physically based materials, real
reflections and contact shadows, volumetric atmosphere, subtle film grain, high dynamic
range, no text.

---

## 3. Keyframes (image model)

**K0 — start of S1.** Photorealistic cinematic film still, vertical 9:16. A muscular
prehistoric man in rough animal hides, barefoot, dusty skin, stands in side profile at
frame left (x 20–45%), leaning his shoulder and both palms into a massive round stone
wheel, pushing it to the right. The wheel is roughly chiselled granite, a square hole at
the hub, chipped edge, hub at 62% width and 70% height, diameter about a quarter of the
frame width. Dry cracked earth ground, sparse dead shrubs, distant mesas, dust kicked up
at the wheel's contact point. Low golden-hour sun from the right behind the subject,
warm rim light on the man and the wheel's edge, amber dust haze. Camera at hub height,
side-on.

**K1 — end of S1 / start of S2.** Same frame as K0, same camera, same light. The man has
taken two steps: his palms are still on the back of the wheel, mid-push, weight forward.
The wheel is rolling, with dust streaming behind it and the background motion-blurred
right-to-left. The hub is exactly at (62%, 70%).

**K2 — end of S2 / start of S3.** Same camera, same light, same ground line. In place of
the stone wheel, a wooden-spoked wheel with an iron tyre, hub exactly at (62%, 70%), is
the front wheel of an 1860s wooden velocipede ("boneshaker") with cranks on the front hub,
an iron frame, a wooden rear wheel at (26%, 71%) and a leather saddle. The same man, now
in 1860s clothing (linen shirt, waistcoat, flat cap, trousers, boots), is seated and
pedalling, side profile. Warm sepia golden hour and a dirt road; the landscape is now
grassland with a wooden fence line.

**K3 — end of S3 / start of S4.** Same camera height, same light side. A 1910s vintage
motorcycle: a single-cylinder engine with cooling fins, brass fittings, a leather saddle,
a belt drive, spoked wheels with narrow pneumatic tyres, a front hub at (64%, 71%) and a
rear hub at (22%, 71%), and a teardrop fuel tank. The rider wears a leather helmet, goggles
and a leather jacket. The engine exhaust leaves a thin smoke trail. It's a country road at
late afternoon, and the first factory chimneys are faint on the horizon.

**K4 — end of S4 / start of S5.** The camera has pulled back and lowered to 0.6 m. A sleek
silver sports car (a generic, unbranded modern grand-tourer: long bonnet, low roofline,
polished aluminium bodywork, dark tinted windows with the driver visible in profile) is
travelling left to right. Its front hub is at (76%, 73%) and its rear hub at (26%, 73%).
Behind it is an industrial landscape: brick and steel factories, smokestacks with drifting
smoke, gantry cranes, and an orange furnace glow and sodium lights against an overcast
teal-grey dusk. The car reflects the orange lights along its flank, with strong motion
blur on the road.

**K5 — end of S5 / start of S6.** The camera is at 3 m, level and side-on. A white and
silver aerodynamic high-speed train on an elevated concrete guideway, with its long
pointed nose tip at (88%, 66%). The body runs off the left edge of the frame, with a
continuous window band and skirted bogies. Behind it is a modern city at blue hour:
glass towers, LED-lit facades and a light-trail blur. Reflections of the city streak
along the train's glossy body, and the guideway top sits at 72% height.

**K6 — end of S6 / start of S7.** Airborne, the camera level with the aircraft. A
white-silver jet airliner (generic, unbranded, swept wings, two underwing engines) in a
front-three-quarter view, climbing and banking gently toward frame right, with its nose
at (70%, 42%). A sea of bright cumulus is below at 70% height, and the sky is a cyan
gradient deepening to cobalt at the top. The sun is at upper right, catching specular
highlights on the fuselage, with thin contrails and wingtip vortices.

**K7 — end of S7 (final frame).** Near space, seen in a rear-three-quarter chase view. A
sleek futuristic spaceship, evolved from the airliner's silhouette (a blended wing-body,
the same white-silver panels now with dark heat-shield tiles and a slimmer nose), sits at
(68%, 30%) climbing toward upper right. Three main engines glow cyan-white, with a soft
exhaust plume trailing lower-left. Earth's curved limb fills the bottom 30% of the frame:
deep-blue ocean, cloud swirls, a thin blue atmospheric glow. The background is black
space with faint stars, and hard sunlight from the right lights one side of the ship.

---

## 4. Shots (image-to-video, start frame → end frame)

### S1 · 0–3 s · Stone wheel · start K0 → end K1 · generate 3 s
**Camera.** Side-on tracking dolly moving right at walking pace, locked at hub height, with
a very slight push-in (about 3%).
**Prompt.** A prehistoric man in animal hides strains to push a massive round stone wheel
to the right across dry cracked earth. The wheel rolls heavily and grinds over pebbles.
Dust bursts from the contact point and drifts in the golden backlight. His feet slip
slightly, his muscles tense, and his breath is visible in the dust. The camera tracks
alongside at the same speed; the ground and distant mesas slide right-to-left with
motion blur. Warm amber golden hour, rim light from the right, rough stone texture,
realistic weight and momentum.
**Keep.** The hub stays at (62%, 70%) and the wheel turns clockwise in step with ground
speed.
**SFX.** wind-dust, stone-roll.

### S2 · 3–5 s · Stone → wood → velocipede · start K1 → end K2 · generate 2 s (or as part of S1+S2)
**Camera.** The same tracking shot continues without pause, with the same framing.
**Prompt.** Without stopping, the rolling stone wheel transforms: cracks run radially
across the stone and split it into wooden spokes, the stone rim resolves into a bent
wooden felloe wrapped in an iron tyre, and the hub stays exactly in place. From the
hub, an iron frame grows backwards (to the left) toward the man, a second wooden wheel
forms beneath him, a leather saddle rises under him and cranks sprout from the front
hub. His hides become 1860s clothing as he settles onto the saddle and begins pedalling.
The dry earth becomes a dirt road through golden grassland. It is one continuous
physical transformation, not a dissolve. Warm sepia golden light and the same sun
direction.
**Keep.** The front hub stays at (62%, 70%) the whole time. Rotation never stops, and the
rider's feet follow the pedals.
**SFX.** wood-creak (3.0 s), bicycle-chain (4.0 s).

### S3 · 5–8 s · Velocipede → vintage motorcycle · start K2 → end K3 · generate 3 s
**Camera.** Tracking side-on, with a slight pull-back (about 8%) as the wheelbase lengthens.
**Prompt.** The rider pedals the wooden velocipede to the right. Mechanical parts assemble
around the existing frame piece by piece: the wooden spokes thin into steel wire spokes,
narrow pneumatic tyres inflate around the rims, the frame extends backwards into a
lower steel cradle, a finned single-cylinder engine builds itself in the centre of the
frame part by part, a teardrop fuel tank closes over the top tube, a belt drive links
the engine to the rear wheel and brass fittings catch the light. The pedals fold away
into footrests. The rider's clothing becomes a leather jacket, helmet and goggles. The
engine coughs and a thin puff of exhaust appears. The grassland road turns into a
country road, and factory chimneys appear on the far horizon. Late-afternoon desaturated
warm light.
**Keep.** The front hub drifts only to (64%, 71%). The structure grows around the frame
rather than replacing it, and wheel rotation stays continuous.
**SFX.** engine-assemble (5.2 s), vintage-engine-start (7.0 s).

### S4 · 8–11 s · Motorcycle → silver sports car, industrial world · start K3 → end K4 · generate 3 s
**Camera.** Tracking side-on while pulling back and lowering to 0.6 m, so the car fills the
width.
**Prompt.** The vintage motorcycle accelerates to the right and transforms into a sleek
silver sports car. The front wheel widens into a low-profile tyre on an alloy rim and
moves slightly forward. Polished aluminium body panels unfold backwards from the engine,
the tank stretches into a long bonnet, a low glass canopy closes over the rider (now
the driver, seen in profile through the side window) and a second rear wheel forms
under the new rear bodywork. The countryside turns into an industrial landscape: brick
factories, smokestacks venting smoke, cranes and orange furnace glow under an overcast
teal-grey dusk. The car's mirror-like flank reflects the orange lights, with heavy
motion blur on the road and background.
**Keep.** The leading edge stays on the right. The camera pull-back must feel continuous,
the car's proportions must be real, and the wheels must be grounded with correct
rotation.
**SFX.** factory-ambience (8.0 s), car-rev-pass (8.4 s).

### S5 · 11–15 s · Car → high-speed train, modern city · start K4 → end K5 · generate 4 s
**Camera.** Tracking side-on while rising smoothly from 0.6 m to 3 m and pulling back.
**Prompt.** The silver sports car stretches: the nose extends forward and sharpens into a
long aerodynamic point, the body lengthens backwards into a continuous white-and-silver
fuselage with a window band, skirts drop over the wheels, which become bogies, and the
road lifts and becomes an elevated concrete guideway. The whole vehicle is now a
high-speed train racing right. The factories resolve into a modern city at blue hour
with glass towers, LED facades and light trails. City lights streak along the train's
glossy body, and speed lines of reflection and motion blur build throughout.
**Keep.** The nose leads on the right, the train body trails off frame left, the guideway
top reaches 72% height, and the transformation is continuous with no cut.
**SFX.** city-ambience (11.0 s), train-whoosh (11.2 s).

### S6 · 15–20 s · Train → jet, takeoff · start K5 → end K6 · generate 5 s
**Camera.** It starts side-on tracking. Over 5 s it arcs smoothly forward around the
vehicle and rises with it, ending front-three-quarter and airborne, level with the jet.
The move is continuous, with no speed ramps.
**Prompt.** The high-speed train's nose lifts. The front cars compress into an aircraft
fuselage, and swept wings unfold outward from the body panels with visible mechanical
sections sliding out, engines forming beneath them. A tail fin rises at the rear, and
the rest of the train detaches and falls behind out of frame. The guideway's lights
become runway edge lights streaking past. The jet rotates and lifts off, and the
landing gear retracts. It climbs through a thin cloud layer into bright high-altitude
daylight while the camera swings from the side to a front-three-quarter view. The sky
shifts from blue hour to bright cyan, the sun catches the fuselage, and wingtip vortices
and heat shimmer trail from the engines.
**Keep.** The travel direction stays screen-right throughout the arc, the wings deploy
symmetrically, and it ends on K6.
**SFX.** wing-servo (15.5 s), jet-takeoff (16.5 s), wind-altitude (19.0 s).

### S7 · 20–25 s · Jet → spaceship, into orbit · start K6 → end K7 · generate 5 s
**Camera.** A chase camera orbits from front-¾ to rear-¾ while tilting up with the climb,
and ends looking past the ship toward space with Earth's limb below.
**Prompt.** The jet pitches up and transforms into a futuristic spaceship. The wings sweep
back and blend into the body, dark heat-shield tiles ripple across the underside, the
nose slims, the underwing engines merge into three rear main engines and ignite with
blinding cyan-white glow, and a shock-diamond exhaust plume forms. The ship climbs
steeply up and to the right, the clouds fall away below, the sky darkens from cobalt to
black, stars appear and Earth's curved horizon with its thin blue atmosphere comes into
view along the bottom of the frame. Hard sunlight from the right, engine light
illuminates the ship's tail, and there is a subtle lens flare from the sun.
**Keep.** The ship's silhouette must visibly descend from the jet (same panel colours).
Motion stays up and to the right, and it ends on K7 and holds briefly.
**SFX.** rocket-ignition (20.6 s), space-drone (22.5 s).

---

## 5. Sound

No licensed music or effects were available in this session, and nothing was downloaded.
The edit already places every cue (`shots/manifest.json` → `music`, `sfx`) and skips any
file that is missing. Drop licensed files in at these paths:

- `public/audio/music.mp3`: a 25 s cinematic build that starts with sparse
  percussion and low strings over the stone age, adds pulse at the motorcycle (5 s),
  builds with the industrial section (8 s), lifts at takeoff (16.5 s) and resolves into
  an airy pad in space (22 s). Fades are applied in the edit.
- `public/audio/sfx/*.mp3`: 15 cues, named in the manifest, each timed to its shot.

Sources with clear licences include your own stock subscription (Artlist, Epidemic
Sound, Musicbed) or CC0 effects (freesound.org, filtered by CC0).
