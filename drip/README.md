# DRIP — scroll-driven product site

A static product site for DRIP, a UV-C water bottle. The hero is one scroll-driven
scene: the bottle, the black shape and the copy are driven by a single GSAP
timeline scrubbed by ScrollTrigger, so every motion follows the scroll position,
including scrolling back up.

## Run

No build step and no npm install. All libraries and fonts are vendored.

```bash
cd drip
python3 -m http.server 8000
# open http://localhost:8000
```

Any static server works. Opening `index.html` from `file://` does **not** work,
because ES modules need HTTP.

## Structure

| Path | What it is |
| --- | --- |
| `index.html` | Markup, brand SVGs (wordmark and flat bottle), cart drawer |
| `styles.css` | Static layout (default) plus the `.is-cinematic` scroll layout |
| `js/scene.js` | Keyframes (landscape and portrait) and the scrubbed timeline |
| `js/bottle3d.js` | Procedural three.js bottle: lathe body, cap, metal ring, canvas-texture label |
| `js/shop.js` | Color selection, demo cart (localStorage), drawer |
| `js/main.js` | Wiring, rendering on demand, lazy 3D loading, fallbacks |
| `vendor/` | three.js r170 (minified), RoomEnvironment, GSAP 3.15 + ScrollTrigger |
| `fonts/` | Inter / Inter Display (OFL) |

## The scroll scene

- The sticky stage spans 450vh on landscape screens and 400vh on portrait ones.
- Positions are expressed as fractions of the stage, so the 3D bottle and the
  HTML type share one grid. `gsap.matchMedia` swaps the landscape and portrait
  keyframe sets and rebuilds the timeline.
- Act 1: close-up, diagonal bottle next to "The Future of Hydration". The bottle
  turns and settles at the centre while "UV-C Water Bottle" comes in.
- Act 2: the bottle moves aside and three short design notes play one at a time.
- Act 3: the full bottle stands next to the color picker and "Shop the Bottle".
  Then the sticky stage releases into the details section and the footer.

## Fallbacks and performance

- **`prefers-reduced-motion`, or no JS:** a static, fully usable layout with no
  pinning and no scrubbing.
- **No WebGL:** a flat SVG bottle follows the same timeline.
- three.js (~170 KB gzipped) is loaded after first paint. The flat bottle shows
  until the first 3D frame is ready.
- The scene renders only when the timeline or the color changes. Shaders are
  compiled up front, and the pixel ratio is capped.

## Commerce

No commerce backend is connected. The cart works (add, quantity, remove,
persisted in localStorage), but **checkout only states that no order was placed
and no payment was taken**. The $59 price is a placeholder. Capacity, materials
and UV-C specifications are intentionally not stated.

## Licenses

three.js: MIT (`vendor/LICENSE-three.txt`). GSAP: standard GSAP license (see the
file headers). Inter: SIL OFL (`fonts/LICENSE-Inter.txt`).
