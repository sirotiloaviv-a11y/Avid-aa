# Bank Discount — 20s promo video (Remotion)

Vertical 1080×1920, 30 fps, 600 frames. Built with [Remotion](https://remotion.dev) 4 + React.
All copy is Hebrew, right-to-left, set in Heebo (loaded via `@remotion/google-fonts`).

## Render

```bash
cd bank-discount-promo
npm install
npx remotion render src/index.ts DiscountPromo out/discount-promo.mp4 --codec=h264 --crf=18
```

(`npm run render` runs the same command.) Output: `out/discount-promo.mp4`, H.264, yuv420p.

Other commands:

| Command | What it does |
| --- | --- |
| `npm run studio` | Opens Remotion Studio for live preview and editing the copy props |
| `npm run still` | Exports a poster frame (frame 560) to `out/poster.png` |
| `npm run typecheck` | `tsc --noEmit` |

On a machine without a downloadable Chrome, add
`--browser-executable=/path/to/chromium` to the render command.

## Timeline

| Time | Frames | Scene | File |
| --- | --- | --- | --- |
| 00:00–00:04 | 0–119 | Hook: white background, rising green waves, geometric accents, "חושבים על העתיד?" | `src/scenes/Scene1Hook.tsx` |
| 00:04–00:10 | 120–299 | App: phone mockup with green glow, count-up balance, chart, three feature icons springing in | `src/scenes/Scene2App.tsx` |
| 00:10–00:16 | 300–479 | Offer: green gradient (#009639→#006827), 3D digital card, white copy, pulsing and shining CTA button | `src/scenes/Scene3Offer.tsx` |
| 00:16–00:20 | 480–599 | Outro: logo scales in from blur, green underline expands, tagline, fine print | `src/scenes/Scene4Outro.tsx` |

Transitions are 15-frame overlaps at each scene boundary: fade into scene 1, a push-slide
from the left (the RTL "forward" direction) into scene 2, a zoom crossfade into scene 3,
and a fade into scene 4.

## Customising

- **Timing**: `src/timing.ts`. Change a scene's `seconds` or `enter` transition; start frames and the
  total length are computed from it. `TRANSITION_FRAMES` sets the overlap.
- **Copy**: `src/copy.ts`. The props can also be edited live in Remotion Studio.
- **Colours / font**: `src/theme.ts`.
- **Logo**: the video ships with a placeholder lockup (abstract mark + "דיסקונט" wordmark). To use the
  official logo, put the file in `public/` (e.g. `public/discount-logo.svg`) and set
  `logoSrc: 'discount-logo.svg'` in `src/copy.ts`. Every logo in the video (scenes 1, 3, 4) switches to it.

Use of the Bank Discount name, logo and slogan in a published ad requires the bank's approval.

## Structure

```
src/
  index.ts              registerRoot
  Root.tsx              <Composition id="DiscountPromo">
  DiscountPromo.tsx     lays the scenes out on the timeline
  timing.ts             parametric scene durations and transitions
  copy.ts               on-screen text + props type
  theme.ts              colours, shadows, Heebo font
  components/
    SceneTransition.tsx fade / slide / zoom in-out wrapper
    RevealText.tsx      fade-in + slide-up text
    Logo.tsx            logo image container with placeholder fallback
    PhoneMockup.tsx     banking-app screen in a phone frame
    CtaButton.tsx       pill button with pulse, halo and shine
    Icons.tsx           growth / wallet / transfer / savings / arrow icons
  scenes/               one file per scene
```
