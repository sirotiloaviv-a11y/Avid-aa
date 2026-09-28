# THE AI KING REVEALED — מלך ה-AI נחשף

A 60-second cinematic trailer built with [Remotion](https://www.remotion.dev)
(React → MP4). 1920×1080, 30 fps, 1800 frames.

```bash
npm install          # also synthesises placeholder audio into public/audio/
npm start            # Remotion Studio — scrub, preview, tweak
npm run build        # → out/the-ai-king-revealed.mp4
# or
npx remotion render AIKingTrailer out/the-ai-king-revealed.mp4
```

It renders complete from a fresh clone. Every footage slot has a procedural
stand-in and every sound has a synthesised placeholder, so you can upgrade the
trailer one asset at a time.

## Story & timing

| Time | Frames | Act | What happens |
|---|---|---|---|
| 00:00–00:10 | 0–299 | **I · Cyber-underworld** | Dead-signal cold open → neon megacity in rain, tearing glitches, subliminal frames of the masked King → whip-zoom |
| 00:10–00:25 | 300–749 | **II · The reveal** | King surfaces under a golden halo, heartbeat + mask glitches, a gold seam splits mask from man (the key-art frame), mask lifts off in a flash-bang, name card |
| 00:25–00:50 | 750–1499 | **III · Chaos** | SWAT breach → server hack → street explosion → helicopter hunt → King walks from a fireball → chase → accelerating rapid-cut montage ("NO FACE. NO NAME. NO LIMITS.") → silence: "UNTIL NOW." → strobe riser → white-out |
| 00:50–01:00 | 1500–1799 | **IV · Climax** | "THE AI KING / REVEALED" title slam → key art assembles live with the Hebrew title → finished poster + COMING SOON → billing block → Ø stinger |

Every glitch, flash and cut reads its frame from **`src/config/timeline.ts`**,
and so does every sound effect. Move a cue there and picture and sound move
together.

## Project layout

```
src/
  index.ts                 registerRoot
  Root.tsx                 compositions: AIKingTrailer + Acts/Act1…Act4 (for fast preview)
  Trailer.tsx              master timeline: 4 acts + grade + sound
  config/
    constants.ts           fps, size, act boundaries, colour palette
    timeline.ts            cue sheet (absolute frames) + montage cut generator
    assets.ts              images, video slots, audio files, face-alignment data
    fonts.ts               Cinzel / Orbitron / Heebo (Hebrew) / Oswald via @remotion/google-fonts
  scenes/                  one component per act; AI video prompts live above each shot
  audio/SoundDesign.tsx    every <Audio/>: score, rain, risers, braams, impacts, whooshes…
  components/
    effects/               Glitch (RGB split + slices), FlashBang, WhipZoom, NeonRain,
                           Explosion, SirenLights, Letterbox, FilmGrain, Vignette, Scanlines
    text/                  Caption (tracking trailer cards + Hebrew subs), GlitchText (decode),
                           GoldTitle (metal + sheen + slam), WordSlam
    media/                 MediaSlot (footage or fallback), KingPortrait (eye-aligned portraits)
    backgrounds/           procedural stand-ins: CityScape, GoldHalo, Corridor+HUD,
                           CodeWall, SpeedTunnel, Searchlight
scripts/generate-placeholder-audio.mjs   dependency-free WAV synthesiser
public/images/             mask, face and key-art stills
public/video/              put generated clips here
public/audio/              generated on install (git-ignored)
```

## Upgrading the assets

**Footage.** Each scene file has a ready-to-paste Runway / Sora / Luma prompt
above every shot (`AI VIDEO PROMPT — slot \`…\``). Generate the clip, put it in
`public/video/`, and set the slot in `src/config/assets.ts`:

```ts
swatBreach: video('swat-breach.mp4'),
```

**The reveal.** `KingPortrait` places the mask and the face so their eye lines
and face sizes match on screen. That alignment is what lets the mask split
down the middle and lift off to reveal the face underneath. If you swap either
photo, update its numbers in `PORTRAIT_FRAMING` (eye-line centre and
eye-to-chin distance, as fractions of the image). For the cleanest result, use
a background-removed PNG of the face.

**Sound.** Replace any file in `public/audio/` with licensed music or SFX of
the same name. The generator never overwrites existing files. To use other
names or formats, change the paths in `AUDIO` in `assets.ts`. Run
`npm run audio -- --force` to regenerate the placeholders.

**Placeholder tags.** Set `SHOW_PLACEHOLDER_TAGS = false` in `constants.ts` to
hide the "PLACEHOLDER · slot" labels for a clean preview render.

## Useful commands

```bash
npx remotion render Act2-Reveal out/reveal.mp4          # render one act
npx remotion still AIKingTrailer out/frame.png --frame=1640   # grab any frame
npm run typecheck
```
