# Generated footage goes here

Drop AI-generated clips in this folder, then point the matching slot at them in
`src/config/assets.ts`, e.g.

```ts
introCity: video('intro-city.mp4'),
```

Each slot's generation prompt is written as a comment above the scene component
that uses it (`src/scenes/*.tsx`). Slots left as `null` render a procedural
stand-in, so you can swap footage in one shot at a time.
