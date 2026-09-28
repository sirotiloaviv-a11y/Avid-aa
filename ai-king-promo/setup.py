#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scaffold the "מלך ה-AI נחשף" Remotion promo (20s, 1080x1920 @ 30fps).

Usage:
    python3 setup.py [TARGET_DIR] [--install] [--force]

Writes the whole TypeScript/React Remotion project into TARGET_DIR (default:
the directory this script lives in) and copies the photos from ./assets into
TARGET_DIR/public/images. Existing files are left alone unless --force is given.
With --install it also runs `npm install`.
"""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Photo files shipped next to this script -> where the project expects them.
ASSETS = {
    "assets/aviv-face.png": "public/images/aviv-face.png",
    "assets/ai-king-mask.jpg": "public/images/ai-king-mask.jpg",
    "assets/ai-king-poster.jpg": "public/images/ai-king-poster.jpg",
}

FILES = {}

FILES['package.json'] = r'''{
  "name": "ai-king-promo",
  "version": "1.0.0",
  "private": true,
  "description": "20s vertical BREAKING NEWS promo: the AI King's identity revealed",
  "scripts": {
    "start": "remotion studio",
    "build": "remotion render NewsPromo out/ai-king-promo.mp4",
    "still": "remotion still NewsPromo out/reveal-still.png --frame=230",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@remotion/cli": "4.0.290",
    "@remotion/google-fonts": "4.0.290",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "remotion": "4.0.290"
  },
  "devDependencies": {
    "@types/react": "18.3.12",
    "typescript": "5.6.3"
  }
}
'''

FILES['tsconfig.json'] = r'''{
  "compilerOptions": {
    "target": "ES2018",
    "module": "commonjs",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "lib": ["DOM", "ES2020"],
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "noUnusedLocals": true
  },
  "include": ["src"],
  "exclude": ["remotion.config.ts"]
}
'''

FILES['remotion.config.ts'] = r'''// Applies to CLI renders only (`npm run build`), not to the Node APIs.
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setCodec("h264");
Config.setCrf(18);
Config.setOverwriteOutput(true);
'''

FILES['.prettierrc'] = r'''{ "printWidth": 120, "singleQuote": false, "trailingComma": "all" }
'''

FILES['.gitignore'] = r'''node_modules/
out/
.DS_Store
'''

FILES['README.md'] = r'''# מלך ה-AI נחשף — Remotion promo

A 20-second vertical (1080x1920 @ 30fps) "BREAKING NEWS" identity-reveal promo.

```bash
npm install
npm start          # Remotion Studio: preview and edit props live
npm run build      # renders out/ai-king-promo.mp4
npm run still      # renders a single frame of the reveal to out/reveal-still.png
```

| Time   | Scene                 | File                          |
|--------|-----------------------|-------------------------------|
| 0-4s   | Hook: breaking badge  | `src/scenes/Scene1Hook.tsx`   |
| 4-10s  | Reveal: mask splits   | `src/scenes/Scene2Reveal.tsx` |
| 10-16s | Impact: stat cards    | `src/scenes/Scene3Impact.tsx` |
| 16-20s | Outro: CTA            | `src/scenes/Scene4Outro.tsx`  |

- All Hebrew copy, the social handle and image paths live in `src/copy.ts`
  (also editable from the Studio props panel).
- Images are read from `public/images/`. If you swap them, retune
  `framing` in `src/copy.ts` so the mask and face line up at the split.
- For music, drop a file in `public/` and set `music` in `src/copy.ts`
  (e.g. `"audio/theme.mp3"`); it fades in and out automatically.
- Scene lengths and animation beats are in `src/timing.ts`; colours and
  the Heebo font in `src/theme.ts`.
'''

FILES['src/NewsPromo.tsx'] = r'''import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile } from "remotion";
import { Background } from "./components/Background";
import { BreakingNewsHeader } from "./components/BreakingNewsHeader";
import { GlitchCuts } from "./components/GlitchCut";
import { SceneFade } from "./components/SceneFade";
import { Scanlines } from "./components/Scanlines";
import { TickerBar } from "./components/TickerBar";
import type { PromoProps } from "./copy";
import { Scene1Hook } from "./scenes/Scene1Hook";
import { Scene2Reveal } from "./scenes/Scene2Reveal";
import { Scene3Impact } from "./scenes/Scene3Impact";
import { Scene4Outro } from "./scenes/Scene4Outro";
import { CLAMP, COLORS, FONT_FAMILY } from "./theme";
import { CUTS, DURATION, GLITCH_SPAN, HEADER, SCENES, SCENE_FADE, TICKER } from "./timing";

const SCENE_LIST = [
  { name: "1 · Hook", timing: SCENES.hook, Component: Scene1Hook },
  { name: "2 · Reveal", timing: SCENES.reveal, Component: Scene2Reveal },
  { name: "3 · Impact", timing: SCENES.impact, Component: Scene3Impact },
  { name: "4 · Outro", timing: SCENES.outro, Component: Scene4Outro },
];

// Main controller: shared backdrop, the four scenes, persistent news chrome, and cut glitches.
export const NewsPromo: React.FC<PromoProps> = (props) => {
  return (
    <AbsoluteFill
      style={{ backgroundColor: COLORS.ink, fontFamily: FONT_FAMILY, direction: "rtl", overflow: "hidden" }}
    >
      <Background />

      {SCENE_LIST.map(({ name, timing, Component }, i) => (
        <Sequence key={name} name={name} from={timing.from} durationInFrames={timing.duration}>
          <SceneFade durationInFrames={timing.duration} fadeIn={i === 0 ? 4 : SCENE_FADE} fadeOut={SCENE_FADE}>
            <Component {...props} />
          </SceneFade>
        </Sequence>
      ))}

      <Sequence name="Header" from={HEADER.from} durationInFrames={HEADER.until - HEADER.from} layout="none">
        <BreakingNewsHeader
          channelName={props.channelName}
          badge={props.breakingBadge}
          english={props.breakingEnglish}
          liveLabel={props.liveLabel}
          clock={props.clock}
          durationInFrames={HEADER.until - HEADER.from}
        />
      </Sequence>

      <Sequence name="Ticker" from={TICKER.from} durationInFrames={TICKER.until - TICKER.from} layout="none">
        <TickerBar label={props.tickerLabel} items={props.tickerItems} durationInFrames={TICKER.until - TICKER.from} />
      </Sequence>

      <GlitchCuts cuts={CUTS} span={GLITCH_SPAN} />
      <Scanlines />

      {props.music ? (
        <Audio
          src={staticFile(props.music)}
          volume={(f) => interpolate(f, [0, 10, DURATION - 20, DURATION], [0, 0.9, 0.9, 0], CLAMP)}
        />
      ) : null}
    </AbsoluteFill>
  );
};
'''

FILES['src/Root.tsx'] = r'''import React from "react";
import { Composition } from "remotion";
import { NewsPromo } from "./NewsPromo";
import { defaultPromoProps } from "./copy";
import { DURATION, FPS, HEIGHT, WIDTH } from "./timing";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="NewsPromo"
      component={NewsPromo}
      durationInFrames={DURATION}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={defaultPromoProps}
    />
  );
};
'''

FILES['src/components/Background.tsx'] = r'''import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";

// Horizontal gold light streaks, like the ones flanking the poster art.
const STREAKS = [
  { y: 360, width: 420, side: "left", phase: 0 },
  { y: 400, width: 260, side: "left", phase: 1.3 },
  { y: 520, width: 380, side: "right", phase: 2.1 },
  { y: 560, width: 220, side: "right", phase: 0.7 },
  { y: 1320, width: 340, side: "left", phase: 2.8 },
  { y: 1400, width: 400, side: "right", phase: 1.9 },
] as const;

export const Background: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 90% 60% at 50% 42%, #152033 0%, #0D1522 45%, ${COLORS.ink} 80%)`,
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(rgba(212,175,55,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(212,175,55,0.06) 1px, transparent 1px)",
          backgroundSize: "90px 90px",
          backgroundPosition: `0px ${frame * 0.6}px`,
          WebkitMaskImage: "radial-gradient(ellipse at center, black 25%, transparent 75%)",
          maskImage: "radial-gradient(ellipse at center, black 25%, transparent 75%)",
        }}
      />
      {STREAKS.map((s, i) => {
        const opacity = 0.35 + 0.35 * Math.sin(frame / 18 + s.phase);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: s.y,
              left: s.side === "left" ? 0 : undefined,
              right: s.side === "right" ? 0 : undefined,
              width: s.width,
              height: 2,
              opacity,
              background: `linear-gradient(${s.side === "left" ? "90deg" : "270deg"}, transparent, ${COLORS.gold} 60%, ${COLORS.lightGold})`,
              boxShadow: `0 0 18px ${COLORS.gold}`,
            }}
          />
        );
      })}
      <AbsoluteFill
        style={{ background: "radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,0.85) 100%)" }}
      />
    </AbsoluteFill>
  );
};
'''

FILES['src/components/BreakingNewsHeader.tsx'] = r'''import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { CLAMP, COLORS, SAFE, redGlow } from "../theme";

type Props = {
  channelName: string;
  badge: string;
  english: string;
  liveLabel: string;
  clock: string;
  durationInFrames: number;
};

// Persistent top-of-screen broadcast chrome: channel bug, LIVE pill, and the red breaking bar.
export const BreakingNewsHeader: React.FC<Props> = ({
  channelName,
  badge,
  english,
  liveLabel,
  clock,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 16, stiffness: 140 } });
  const barEnter = spring({ frame: frame - 6, fps, config: { damping: 18, stiffness: 120 } });
  const exit = interpolate(frame, [durationInFrames - 10, durationInFrames], [0, 1], CLAMP);
  const pulse = 0.5 + 0.5 * Math.sin(frame / 5);
  const dotOn = Math.floor(frame / 15) % 2 === 0;

  return (
    <div
      style={{
        position: "absolute",
        top: SAFE.top,
        left: SAFE.side,
        right: SAFE.side,
        opacity: enter * (1 - exit),
        transform: `translateY(${(1 - enter) * -80 - exit * 40}px)`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div
          style={{
            border: `2px solid ${COLORS.gold}`,
            padding: "8px 22px",
            color: COLORS.gold,
            fontSize: 30,
            fontWeight: 800,
            letterSpacing: 3,
            direction: "ltr",
            background: "rgba(10,12,14,0.7)",
          }}
        >
          {channelName}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            direction: "ltr",
            background: COLORS.crimson,
            padding: "8px 22px",
            borderRadius: 8,
            color: COLORS.white,
            fontSize: 30,
            fontWeight: 800,
            boxShadow: redGlow(0.6 + 0.4 * pulse),
          }}
        >
          <div style={{ width: 16, height: 16, borderRadius: 8, background: COLORS.white, opacity: dotOn ? 1 : 0.2 }} />
          {liveLabel}
          <span style={{ fontWeight: 500, opacity: 0.85 }}>{clock}</span>
        </div>
      </div>

      <div style={{ display: "flex", marginTop: 18, overflow: "hidden", borderRadius: 6 }}>
        <div
          style={{
            background: COLORS.crimson,
            color: COLORS.white,
            fontSize: 60,
            fontWeight: 900,
            padding: "10px 34px",
            whiteSpace: "nowrap",
            transform: `translateX(${(1 - barEnter) * 700}px)`,
            boxShadow: redGlow(0.5 + 0.8 * pulse),
            zIndex: 1,
          }}
        >
          {badge}
        </div>
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: `linear-gradient(90deg, ${COLORS.grey}, ${COLORS.ink})`,
            borderBottom: `4px solid ${COLORS.gold}`,
            color: COLORS.gold,
            fontSize: 38,
            fontWeight: 800,
            letterSpacing: 6,
            direction: "ltr",
            opacity: barEnter,
          }}
        >
          {english}
        </div>
      </div>
    </div>
  );
};
'''

FILES['src/components/CtaButton.tsx'] = r'''import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, GOLD_GRADIENT } from "../theme";

// Gold pill call-to-action with a heartbeat pulse and a recurring shine sweep.
export const CtaButton: React.FC<{ label: string; delay?: number }> = ({ label, delay = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = frame - delay;

  const enter = spring({ frame: local, fps, config: { damping: 10, stiffness: 140 } });
  const pulse = local > 15 ? 1 + 0.035 * Math.sin((local - 15) / 5) : 1;
  const shine = local > 12 ? (((local - 12) % 40) / 40) * 170 - 35 : -35;

  return (
    <div
      style={{
        position: "relative",
        overflow: "hidden",
        display: "inline-flex",
        alignItems: "center",
        gap: 24,
        padding: "30px 90px",
        borderRadius: 999,
        background: GOLD_GRADIENT,
        color: COLORS.ink,
        fontSize: 64,
        fontWeight: 900,
        transform: `scale(${enter * pulse})`,
        opacity: Math.min(1, enter * 1.5),
        boxShadow:
          "0 0 60px rgba(212,175,55,0.55), inset 0 -6px 0 rgba(0,0,0,0.18), inset 0 4px 0 rgba(255,255,255,0.35)",
      }}
    >
      <span>{label}</span>
      <span style={{ fontSize: 56 }}>←</span>
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: `${shine}%`,
          width: 90,
          transform: "skewX(-20deg)",
          background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.65), transparent)",
        }}
      />
    </div>
  );
};
'''

FILES['src/components/GlitchCut.tsx'] = r'''import React from "react";
import { AbsoluteFill, random, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";

const BAR_COLORS = [COLORS.crimson, COLORS.gold, "#00E5FF", COLORS.white];

// A short burst of displaced colour bars and a white flash centred on each scene cut.
export const GlitchCuts: React.FC<{ cuts: readonly number[]; span: number }> = ({ cuts, span }) => {
  const frame = useCurrentFrame();
  const cut = cuts.find((c) => Math.abs(frame - c) <= span);
  if (cut === undefined) {
    return null;
  }

  const d = frame - cut;
  const strength = 1 - Math.abs(d) / (span + 1);
  const flash = d === 0 ? 0.6 : d === 1 ? 0.25 : 0;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {new Array(10).fill(0).map((_, i) => {
        const r = (k: string) => random(`cut-${cut}-${frame}-${i}-${k}`);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: `${r("top") * 100}%`,
              height: `${0.6 + r("h") * 7}%`,
              transform: `translateX(${(r("x") - 0.5) * 360 * strength}px)`,
              background: BAR_COLORS[Math.floor(r("c") * BAR_COLORS.length)],
              opacity: (0.25 + r("o") * 0.5) * strength,
              mixBlendMode: "screen",
            }}
          />
        );
      })}
      <AbsoluteFill style={{ backgroundColor: COLORS.white, opacity: flash }} />
    </AbsoluteFill>
  );
};
'''

FILES['src/components/GlitchReveal.tsx'] = r'''import React from "react";
import { random, useCurrentFrame } from "remotion";

type Props = {
  intensity: number; // 0 = clean, 1 = fully glitched
  seed?: string;
  slices?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
};

const layer: React.CSSProperties = { position: "absolute", inset: 0 };

// RGB-split and horizontal slice displacement over any content (images or text).
export const GlitchReveal: React.FC<Props> = ({ intensity, seed = "glitch", slices = 7, style, children }) => {
  const frame = useCurrentFrame();
  const k = Math.max(0, Math.min(1, intensity));
  const tick = Math.floor(frame / 2); // new displacement every other frame reads as digital, not smooth
  const r = (key: string) => random(`${seed}-${tick}-${key}`);

  if (k < 0.01) {
    return (
      <div style={{ position: "relative", ...style }}>
        <div style={{ width: "100%", height: "100%" }}>{children}</div>
      </div>
    );
  }

  const jitter = (r("jitter") - 0.5) * 24 * k;

  return (
    <div style={{ position: "relative", ...style }}>
      <div style={{ width: "100%", height: "100%", transform: `translateX(${jitter}px)` }}>{children}</div>
      <div
        style={{
          ...layer,
          transform: `translate(${-16 * k}px, ${3 * k}px)`,
          opacity: 0.7 * k,
          mixBlendMode: "screen",
          filter: "grayscale(1) sepia(1) saturate(9) hue-rotate(-50deg)",
        }}
      >
        {children}
      </div>
      <div
        style={{
          ...layer,
          transform: `translate(${16 * k}px, ${-3 * k}px)`,
          opacity: 0.6 * k,
          mixBlendMode: "screen",
          filter: "grayscale(1) sepia(1) saturate(9) hue-rotate(150deg)",
        }}
      >
        {children}
      </div>
      {new Array(slices).fill(0).map((_, i) => {
        if (r(`show-${i}`) > k) {
          return null;
        }
        const top = r(`top-${i}`) * 92;
        const height = 2 + r(`h-${i}`) * 12;
        return (
          <div
            key={i}
            style={{
              ...layer,
              clipPath: `inset(${top}% 0 ${Math.max(0, 100 - top - height)}% 0)`,
              transform: `translateX(${(r(`x-${i}`) - 0.5) * 160 * k}px)`,
            }}
          >
            {children}
          </div>
        );
      })}
    </div>
  );
};
'''

FILES['src/components/GoldCard.tsx'] = r'''import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { ImpactCard } from "../copy";
import { CLAMP, COLORS, GOLD_BORDER, goldGlow, goldText } from "../theme";
import { Icon } from "./Icons";

type Props = ImpactCard & { delay: number; index: number };

// An achievement card: sweeps in from the right, counts its stat up, then catches a shine.
export const GoldCard: React.FC<Props> = ({
  icon,
  title,
  subtitle,
  statValue,
  statPrefix = "",
  statSuffix = "",
  statText,
  delay,
  index,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = frame - delay;

  const enter = spring({ frame: local, fps, config: { damping: 14, stiffness: 110 } });
  const count = interpolate(local, [8, 38], [0, statValue ?? 0], { ...CLAMP, easing: Easing.out(Easing.cubic) });
  const stat = statText ?? `${statPrefix}${Math.round(count)}${statSuffix}`;
  const shine = interpolate(local, [18, 44], [-40, 140], CLAMP);
  const iconSpin = interpolate(enter, [0, 1], [-90, 0]);
  const float = Math.sin((frame + index * 20) / 22) * 4;

  return (
    <div
      style={{
        padding: 3,
        borderRadius: 30,
        background: GOLD_BORDER,
        opacity: enter,
        transform: `translateX(${(1 - enter) * 700}px) translateY(${float}px) perspective(1200px) rotateY(${(1 - enter) * -35}deg)`,
        boxShadow: `0 20px 60px rgba(0,0,0,0.6), 0 0 ${30 * enter}px rgba(212,175,55,0.25)`,
      }}
    >
      <div
        style={{
          position: "relative",
          overflow: "hidden",
          height: 254,
          borderRadius: 27,
          display: "flex",
          alignItems: "center",
          gap: 30,
          padding: "0 36px",
          background: `linear-gradient(135deg, rgba(31,36,45,0.97), rgba(10,12,14,0.97))`,
        }}
      >
        <div
          style={{
            width: 150,
            height: 150,
            flexShrink: 0,
            borderRadius: 75,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `3px solid ${COLORS.gold}`,
            background: "radial-gradient(circle, rgba(212,175,55,0.22), rgba(10,12,14,0.9) 70%)",
            transform: `rotate(${iconSpin}deg)`,
            boxShadow: "0 0 30px rgba(212,175,55,0.35)",
          }}
        >
          <Icon name={icon} size={82} color={COLORS.lightGold} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: COLORS.white, fontSize: 54, fontWeight: 900, lineHeight: 1.1 }}>{title}</div>
          <div style={{ color: COLORS.mutedText, fontSize: 30, fontWeight: 400, marginTop: 8, lineHeight: 1.25 }}>
            {subtitle}
          </div>
        </div>
        <div
          style={{
            ...goldText,
            direction: "ltr",
            fontSize: statText ? 110 : 84,
            fontWeight: 900,
            minWidth: 190,
            textAlign: "center",
            filter: goldGlow(0.8),
          }}
        >
          {stat}
        </div>
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: `${shine}%`,
            width: 120,
            transform: "skewX(-20deg)",
            background: "linear-gradient(90deg, transparent, rgba(246,226,122,0.22), transparent)",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: 120,
            height: 6,
            background: COLORS.crimson,
          }}
        />
      </div>
    </div>
  );
};
'''

FILES['src/components/Icons.tsx'] = r'''import React from "react";
import { COLORS } from "../theme";

export type IconName = "chip" | "globe" | "crown" | "bolt";

const PATHS: Record<IconName, React.ReactNode> = {
  chip: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <ellipse cx="12" cy="12" rx="4" ry="9" />
      <path d="M3 12h18M4.8 7h14.4M4.8 17h14.4" />
    </>
  ),
  crown: (
    <>
      <path d="M4 18 3 7l5 4 4-7 4 7 5-4-1 11Z" />
      <path d="M4 21h16" />
    </>
  ),
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7Z" />,
};

export const Icon: React.FC<{
  name: IconName;
  size?: number;
  color?: string;
  strokeWidth?: number;
}> = ({ name, size = 64, color = COLORS.gold, strokeWidth = 1.6 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {PATHS[name]}
  </svg>
);

// The AI King crest: a gold crown with sapphires and an "AI" chip, echoing the mask art.
export const CrownLogo: React.FC<{ size?: number }> = ({ size = 300 }) => (
  <svg width={size} height={size * 0.85} viewBox="0 0 200 170">
    <defs>
      <linearGradient id="crown-gold" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={COLORS.lightGold} />
        <stop offset="50%" stopColor={COLORS.gold} />
        <stop offset="100%" stopColor={COLORS.darkGold} />
      </linearGradient>
    </defs>
    <path
      d="M22 130 12 42l50 40 38-66 38 66 50-40-10 88Z"
      fill="url(#crown-gold)"
      stroke={COLORS.lightGold}
      strokeWidth="2"
      strokeLinejoin="round"
    />
    <rect x="18" y="134" width="164" height="22" rx="5" fill="url(#crown-gold)" />
    {[
      [12, 42],
      [100, 16],
      [188, 42],
    ].map(([cx, cy]) => (
      <circle key={cx} cx={cx} cy={cy} r="9" fill={COLORS.sapphire} stroke={COLORS.lightGold} strokeWidth="3" />
    ))}
    {[40, 70, 130, 160].map((cx) => (
      <circle key={cx} cx={cx} cy="145" r="5" fill={COLORS.sapphire} />
    ))}
    <rect x="76" y="78" width="48" height="40" rx="5" fill={COLORS.ink} stroke={COLORS.lightGold} strokeWidth="2.5" />
    <text
      x="100"
      y="107"
      textAnchor="middle"
      fontSize="24"
      fontWeight="900"
      fill={COLORS.lightGold}
      fontFamily="sans-serif"
    >
      AI
    </text>
  </svg>
);
'''

FILES['src/components/Scanlines.tsx'] = r'''import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

// Broadcast texture: fine scanlines plus a film grain that re-seeds every frame.
export const Scanlines: React.FC<{ opacity?: number }> = ({ opacity = 1 }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity }}>
      <AbsoluteFill
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(0,0,0,0.16) 0px, rgba(0,0,0,0.16) 2px, transparent 2px, transparent 4px)",
        }}
      />
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: 0.07 }}>
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed={frame % 12} />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
    </AbsoluteFill>
  );
};
'''

FILES['src/components/SceneFade.tsx'] = r'''import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { CLAMP } from "../theme";

// Fades a scene in and out at its own edges; frames are relative to the parent Sequence.
export const SceneFade: React.FC<{
  durationInFrames: number;
  fadeIn?: number;
  fadeOut?: number;
  children: React.ReactNode;
}> = ({ durationInFrames, fadeIn = 8, fadeOut = 8, children }) => {
  const frame = useCurrentFrame();
  const inP = fadeIn > 0 ? interpolate(frame, [0, fadeIn], [0, 1], CLAMP) : 1;
  const outP = fadeOut > 0 ? interpolate(frame, [durationInFrames - fadeOut, durationInFrames], [1, 0], CLAMP) : 1;
  const scale = 1 + 0.04 * (1 - inP) + 0.03 * (1 - outP);

  return <AbsoluteFill style={{ opacity: inP * outP, transform: `scale(${scale})` }}>{children}</AbsoluteFill>;
};
'''

FILES['src/components/TickerBar.tsx'] = r'''import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { CLAMP, COLORS, SAFE } from "../theme";

type Props = {
  label: string;
  items: string[];
  durationInFrames: number;
  speed?: number; // percent of one loop per frame
};

// Bottom news crawl. Hebrew crawls move left-to-right, so new items enter from the left.
export const TickerBar: React.FC<Props> = ({ label, items, durationInFrames, speed = 0.09 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 18, stiffness: 120 } });
  const exit = interpolate(frame, [durationInFrames - 10, durationInFrames], [0, 1], CLAMP);
  // The strip holds two identical copies, so shifting by 50% of its width loops seamlessly.
  const offset = (frame * speed) % 50;

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: SAFE.bottom,
        height: 96,
        display: "flex",
        borderTop: `3px solid ${COLORS.gold}`,
        borderBottom: `1px solid ${COLORS.darkGold}`,
        opacity: 1 - exit,
        transform: `translateY(${(1 - enter) * 180}px)`,
        boxShadow: "0 -10px 40px rgba(0,0,0,0.6)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "0 36px",
          background: COLORS.crimson,
          color: COLORS.white,
          fontSize: 42,
          fontWeight: 900,
          zIndex: 1,
          boxShadow: "0 0 30px rgba(229,9,20,0.6)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          flex: 1,
          position: "relative",
          overflow: "hidden",
          background: `linear-gradient(90deg, ${COLORS.ink}, ${COLORS.grey})`,
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: 0,
            display: "flex",
            alignItems: "center",
            direction: "ltr",
            whiteSpace: "nowrap",
            transform: `translateX(${offset - 50}%)`,
          }}
        >
          {[0, 1].map((copy) => (
            <div key={copy} style={{ display: "flex" }}>
              {items.map((item, i) => (
                <span
                  key={i}
                  style={{ display: "flex", alignItems: "center", color: COLORS.white, fontSize: 40, fontWeight: 700 }}
                >
                  <span dir="rtl" style={{ padding: "0 30px" }}>
                    {item}
                  </span>
                  <span style={{ color: COLORS.gold, fontSize: 26 }}>◆</span>
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
'''

FILES['src/copy.ts'] = r'''import type { IconName } from "./components/Icons";

export type ImpactCard = {
  icon: IconName;
  title: string;
  subtitle: string;
  // Either a number that counts up (with optional prefix/suffix) or fixed text.
  statValue?: number;
  statPrefix?: string;
  statSuffix?: string;
  statText?: string;
};

export type PromoProps = {
  channelName: string;
  breakingBadge: string;
  breakingEnglish: string;
  liveLabel: string;
  clock: string;
  tickerLabel: string;
  tickerItems: string[];
  hook: {
    kicker: string;
    headline: string;
    subline: string;
    unknownLabel: string;
  };
  reveal: {
    scanningLabel: string;
    classifiedStamp: string;
    titlePrefix: string;
    name: string;
    verifiedLabel: string;
    simulationBadge: string;
  };
  impact: {
    title: string;
    cards: ImpactCard[];
  };
  outro: {
    tagline: string;
    cta: string;
    handle: string;
    socials: string[];
    finePrint: string;
  };
  // Paths are relative to /public and resolved with staticFile().
  images: {
    face: string;
    mask: string;
    poster: string; // "" to skip the outro backdrop
  };
  // Crop tuning for the photos; adjust these if you swap images.
  // Offsets are in pixels of the 860x1000 reveal frame; the defaults line the
  // mask's eyes and nose up with the face photo so the split runs down the nose.
  framing: {
    faceObjectPosition: string;
    faceScale: number;
    maskScale: number;
    maskOffsetX: number;
    maskOffsetY: number;
    splitAt: number; // % from the left where the mask stops after the reveal
    monitorObjectPosition: string; // mask crop in the hook's live monitor
    avatarObjectPosition: string;
    avatarScale: number;
  };
  music: string; // e.g. "audio/theme.mp3" in /public, "" for silence
};

export const defaultPromoProps: PromoProps = {
  channelName: "AI KING NEWS",
  breakingBadge: "מבזק מיוחד",
  breakingEnglish: "BREAKING NEWS",
  liveLabel: "LIVE",
  clock: "20:00",
  tickerLabel: "עכשיו",
  tickerItems: [
    "זהותו של מלך ה-AI נחשפה לראשונה",
    "אביב סנאנס הוא האיש מאחורי המסכה",
    "מהפכת ה-AI כבר כאן",
    "עולמות שלמים נוצרים מאפס",
    "עקבו לעדכונים נוספים",
  ],
  hook: {
    kicker: "דיווח בלעדי",
    headline: "זהותו הסודית של מלך ה-AI",
    subline: "עומדת להיחשף ברגעים אלה",
    unknownLabel: "זהות: לא ידועה",
  },
  reveal: {
    scanningLabel: "סורק זהות",
    classifiedStamp: "מסווג",
    titlePrefix: "מלך ה-AI נחשף:",
    name: "אביב סנאנס",
    verifiedLabel: "זהות אומתה",
    simulationBadge: "הדמיה",
  },
  impact: {
    title: "למה קוראים לו מלך ה-AI?",
    cards: [
      {
        icon: "chip",
        title: "מהפכת ה-AI",
        subtitle: "מוביל את השינוי, לא מחכה לו",
        statValue: 24,
        statSuffix: "/7",
      },
      {
        icon: "globe",
        title: "יצירת עולמות",
        subtitle: "וידאו, תמונה ועולמות שלמים מאפס",
        statText: "∞",
      },
      {
        icon: "crown",
        title: "שליטה בטכנולוגיה",
        subtitle: "כלים, מודלים ואוטומציות בשליטה מלאה",
        statValue: 100,
        statSuffix: "%",
      },
    ],
  },
  outro: {
    tagline: "אביב סנאנס - מלך ה-AI",
    cta: "עקבו עכשיו",
    handle: "@aviv.sananes",
    socials: ["Instagram", "TikTok", "YouTube"],
    finePrint: "* הדמיה. סרטון פרסומי בסגנון מבזק חדשות; אינו דיווח חדשותי אמיתי.",
  },
  images: {
    face: "images/aviv-face.png",
    mask: "images/ai-king-mask.jpg",
    poster: "images/ai-king-poster.jpg",
  },
  framing: {
    faceObjectPosition: "50% 30%",
    faceScale: 1,
    maskScale: 1.45,
    maskOffsetX: 85,
    maskOffsetY: -168,
    splitAt: 54.6,
    monitorObjectPosition: "50% 55%",
    avatarObjectPosition: "50% 30%",
    avatarScale: 1.45,
  },
  music: "",
};
'''

FILES['src/index.ts'] = r'''import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
'''

FILES['src/scenes/Scene1Hook.tsx'] = r'''import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  random,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { PromoProps } from "../copy";
import { CLAMP, COLORS, goldText, redGlow } from "../theme";

// 0-4s: alarm lights, a flashing "breaking" badge, and live footage of the masked king.
export const Scene1Hook: React.FC<PromoProps> = ({ breakingBadge, breakingEnglish, hook, images, framing }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Alarm lights alternate left/right like a police bar.
  const alarm = 0.5 + 0.5 * Math.sin(frame * 0.35);

  const badgeIn = spring({ frame, fps, config: { damping: 11, stiffness: 160 } });
  const badgeScale = interpolate(badgeIn, [0, 1], [2.2, 1]);
  const badgeFlash = frame < 36 ? (Math.floor(frame / 4) % 2 === 0 ? 1 : 0.3) : 1;
  const englishSpacing = interpolate(frame, [6, 40], [40, 14], { ...CLAMP, easing: Easing.out(Easing.cubic) });

  const monitorIn = spring({ frame: frame - 16, fps, config: { damping: 15, stiffness: 110 } });
  const tick = Math.floor(frame / 2);
  const shakeX = (random(`hook-sx-${tick}`) - 0.5) * 8;
  const shakeY = (random(`hook-sy-${tick}`) - 0.5) * 6;
  const rollY = ((frame * 11) % 900) - 120;
  const recOn = Math.floor(frame / 12) % 2 === 0;

  const words = hook.headline.split(" ");
  const sublineChars = Math.round(interpolate(frame, [74, 100], [0, hook.subline.length], CLAMP));

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at 0% 0%, rgba(229,9,20,${0.55 * alarm}) 0%, transparent 55%), radial-gradient(circle at 100% 0%, rgba(229,9,20,${0.55 * (1 - alarm)}) 0%, transparent 55%)`,
          boxShadow: `inset 0 0 ${140 + 100 * alarm}px rgba(229,9,20,${0.25 + 0.2 * alarm})`,
        }}
      />

      {/* Breaking badge */}
      <div
        style={{
          position: "absolute",
          top: 120,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <div
          style={{
            background: COLORS.crimson,
            color: COLORS.white,
            fontSize: 118,
            fontWeight: 900,
            padding: "6px 56px 14px",
            transform: `scale(${badgeScale}) skewX(-6deg)`,
            opacity: badgeIn * badgeFlash,
            boxShadow: redGlow(1 + alarm),
            lineHeight: 1.1,
          }}
        >
          {breakingBadge}
        </div>
        <div
          style={{
            ...goldText,
            marginTop: 18,
            fontSize: 50,
            fontWeight: 900,
            letterSpacing: englishSpacing,
            direction: "ltr",
            opacity: interpolate(frame, [6, 20], [0, 1], CLAMP),
          }}
        >
          {breakingEnglish}
        </div>
      </div>

      {/* Live monitor */}
      <div
        style={{
          position: "absolute",
          top: 420,
          left: 110,
          width: 860,
          height: 740,
          padding: 4,
          borderRadius: 28,
          background: `linear-gradient(135deg, ${COLORS.lightGold}, ${COLORS.darkGold})`,
          opacity: monitorIn,
          transform: `scale(${interpolate(monitorIn, [0, 1], [0.85, 1])})`,
          boxShadow: "0 30px 80px rgba(0,0,0,0.7)",
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            overflow: "hidden",
            borderRadius: 24,
            background: COLORS.ink,
          }}
        >
          <Img
            src={staticFile(images.mask)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: framing.monitorObjectPosition,
              filter: "grayscale(0.35) contrast(1.15) brightness(0.8)",
              transform: `scale(${1.08 + frame * 0.0015}) translate(${shakeX}px, ${shakeY}px)`,
            }}
          />
          <AbsoluteFill
            style={{
              backgroundImage:
                "repeating-linear-gradient(0deg, rgba(0,0,0,0.3) 0px, rgba(0,0,0,0.3) 2px, transparent 2px, transparent 5px)",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: rollY,
              height: 90,
              background: "linear-gradient(transparent, rgba(255,255,255,0.08), transparent)",
            }}
          />
          <AbsoluteFill style={{ background: "linear-gradient(transparent 55%, rgba(10,12,14,0.85))" }} />
          {/* Viewfinder corners */}
          {[
            { top: 24, left: 24, borderTop: true, borderLeft: true },
            { top: 24, right: 24, borderTop: true, borderRight: true },
            { bottom: 24, left: 24, borderBottom: true, borderLeft: true },
            { bottom: 24, right: 24, borderBottom: true, borderRight: true },
          ].map(({ borderTop, borderLeft, borderRight, borderBottom, ...pos }, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                ...pos,
                width: 60,
                height: 60,
                borderTop: borderTop ? `4px solid ${COLORS.gold}` : undefined,
                borderLeft: borderLeft ? `4px solid ${COLORS.gold}` : undefined,
                borderRight: borderRight ? `4px solid ${COLORS.gold}` : undefined,
                borderBottom: borderBottom ? `4px solid ${COLORS.gold}` : undefined,
              }}
            />
          ))}
          <div
            style={{
              position: "absolute",
              top: 44,
              left: 100,
              direction: "ltr",
              display: "flex",
              alignItems: "center",
              gap: 12,
              color: COLORS.white,
              fontSize: 30,
              fontWeight: 800,
            }}
          >
            <div
              style={{ width: 20, height: 20, borderRadius: 10, background: COLORS.crimson, opacity: recOn ? 1 : 0.2 }}
            />
            REC
          </div>
          <div
            style={{
              position: "absolute",
              top: 44,
              right: 100,
              color: COLORS.gold,
              fontSize: 30,
              fontWeight: 800,
              direction: "ltr",
            }}
          >
            CAM 01
          </div>
          <div
            style={{
              position: "absolute",
              bottom: 44,
              left: "50%",
              transform: "translateX(-50%)",
              whiteSpace: "nowrap",
              background: "rgba(229,9,20,0.92)",
              color: COLORS.white,
              fontSize: 40,
              fontWeight: 800,
              padding: "8px 30px",
              borderRadius: 8,
            }}
          >
            {hook.unknownLabel} ?
          </div>
        </div>
      </div>

      {/* Headline */}
      <div style={{ position: "absolute", top: 1195, left: 70, right: 70, textAlign: "center" }}>
        <div
          style={{
            display: "inline-block",
            color: COLORS.crimson,
            fontSize: 36,
            fontWeight: 900,
            letterSpacing: 2,
            borderBottom: `3px solid ${COLORS.crimson}`,
            paddingBottom: 4,
            opacity: interpolate(frame, [36, 46], [0, 1], CLAMP),
          }}
        >
          {hook.kicker}
        </div>
        <div style={{ marginTop: 14, color: COLORS.white, fontSize: 74, fontWeight: 900, lineHeight: 1.12 }}>
          {words.map((w, i) => {
            const p = spring({ frame: frame - 44 - i * 4, fps, config: { damping: 14, stiffness: 150 } });
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  margin: "0 10px",
                  opacity: p,
                  transform: `translateY(${(1 - p) * 40}px)`,
                }}
              >
                {w}
              </span>
            );
          })}
        </div>
        <div style={{ ...goldText, marginTop: 14, fontSize: 52, fontWeight: 800, minHeight: 64 }}>
          {hook.subline.slice(0, sublineChars)}
          <span style={{ opacity: frame >= 74 && Math.floor(frame / 8) % 2 === 0 ? 1 : 0 }}>|</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
'''

FILES['src/scenes/Scene2Reveal.tsx'] = r'''import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { GlitchReveal } from "../components/GlitchReveal";
import type { PromoProps } from "../copy";
import { CLAMP, COLORS, goldGlow, goldText } from "../theme";
import { REVEAL_BEATS as B } from "../timing";

const FRAME = { top: 300, width: 860, height: 1000 };

// 4-10s: scan the mask, glitch, then split it open to reveal the face beneath, and name him.
export const Scene2Reveal: React.FC<PromoProps> = ({ reveal, images, framing }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scan = interpolate(frame, [B.scanStart, B.scanEnd], [0, 100], CLAMP);
  const scanning = frame >= B.scanStart && frame < B.split;
  const glitch =
    interpolate(frame, [B.glitchStart, B.split, B.splitSettled], [0, 1, 0], CLAMP) +
    interpolate(frame, [140, 143, 146], [0, 0.35, 0], CLAMP);

  // Share of the frame (from the left) still covered by the mask: 100% → splitAt.
  const splitIn = spring({ frame: frame - B.split, fps, config: { damping: 13, stiffness: 90 } });
  const maskShare = interpolate(splitIn, [0, 1], [100, framing.splitAt]);

  const stampIn = spring({ frame: frame - 10, fps, config: { damping: 9, stiffness: 200 } });
  const stampOut = interpolate(frame, [B.split - 4, B.split], [1, 0], CLAMP);
  const push = interpolate(frame, [0, 180], [1, 1.07]);
  const flash = interpolate(frame, [B.split, B.split + 6], [0.85, 0], CLAMP);
  const ringSpin = frame * 0.3;

  const titleIn = spring({ frame: frame - B.titleIn, fps, config: { damping: 15, stiffness: 140 } });
  const nameIn = spring({ frame: frame - B.nameIn, fps, config: { damping: 12, stiffness: 100 } });
  const nameGlitch = interpolate(frame, [B.nameIn, B.nameIn + 20], [1, 0], CLAMP);
  const verifiedIn = spring({ frame: frame - B.verifiedIn, fps, config: { damping: 12, stiffness: 160 } });

  return (
    <AbsoluteFill>
      {/* Gold rings behind the portrait, as on the poster */}
      {[1040, 900].map((d, i) => (
        <div
          key={d}
          style={{
            position: "absolute",
            width: d,
            height: d,
            left: (1080 - d) / 2,
            top: FRAME.top + FRAME.height / 2 - d / 2,
            borderRadius: "50%",
            border: `${i === 0 ? 2 : 3}px ${i === 0 ? "dashed" : "solid"} rgba(212,175,55,${i === 0 ? 0.35 : 0.5})`,
            transform: `rotate(${i === 0 ? ringSpin : -ringSpin}deg)`,
            boxShadow: i === 1 ? "0 0 40px rgba(212,175,55,0.2)" : undefined,
          }}
        />
      ))}

      <div
        style={{
          position: "absolute",
          top: FRAME.top,
          left: (1080 - FRAME.width) / 2,
          width: FRAME.width,
          height: FRAME.height,
          padding: 4,
          borderRadius: 28,
          background: `linear-gradient(135deg, ${COLORS.lightGold}, ${COLORS.darkGold})`,
          boxShadow: "0 40px 90px rgba(0,0,0,0.75), 0 0 50px rgba(212,175,55,0.25)",
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            overflow: "hidden",
            borderRadius: 24,
            background: COLORS.ink,
          }}
        >
          <GlitchReveal intensity={glitch} seed="reveal" slices={9} style={{ width: "100%", height: "100%" }}>
            <div style={{ position: "relative", width: "100%", height: "100%", transform: `scale(${push})` }}>
              <Img
                src={staticFile(images.face)}
                style={{
                  position: "absolute",
                  inset: 0,
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                  objectPosition: framing.faceObjectPosition,
                  transform: `scale(${framing.faceScale})`,
                  filter: "contrast(1.08) saturate(1.05)",
                }}
              />
              <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 ${100 - maskShare}% 0 0)` }}>
                <Img
                  src={staticFile(images.mask)}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    transform: `translate(${framing.maskOffsetX}px, ${framing.maskOffsetY}px) scale(${framing.maskScale})`,
                  }}
                />
              </div>
            </div>
          </GlitchReveal>

          {/* Seam between mask and face (tracks the push-in applied to the photos) */}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `calc(${50 + (maskShare - 50) * push}% - 3px)`,
              width: 6,
              background: `linear-gradient(${COLORS.lightGold}, ${COLORS.gold}, ${COLORS.darkGold})`,
              boxShadow: `0 0 30px ${COLORS.gold}, 0 0 60px ${COLORS.gold}`,
              opacity: maskShare < 99.5 ? 1 : 0,
            }}
          />

          {/* Identity scan */}
          {scanning && (
            <>
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  top: 0,
                  height: `${scan}%`,
                  background: "linear-gradient(transparent 70%, rgba(212,175,55,0.22))",
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  top: `${scan}%`,
                  height: 4,
                  background: COLORS.lightGold,
                  boxShadow: `0 0 24px ${COLORS.gold}, 0 0 60px ${COLORS.gold}`,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  top: 36,
                  left: 0,
                  right: 0,
                  textAlign: "center",
                  color: COLORS.lightGold,
                  fontSize: 38,
                  fontWeight: 800,
                  textShadow: "0 2px 10px rgba(0,0,0,0.9)",
                }}
              >
                {reveal.scanningLabel}...{" "}
                <span style={{ direction: "ltr", display: "inline-block" }}>{Math.round(scan)}%</span>
              </div>
            </>
          )}

          {/* Classified stamp */}
          <div
            style={{
              position: "absolute",
              top: "42%",
              left: "50%",
              transform: `translate(-50%, -50%) rotate(-12deg) scale(${interpolate(stampIn, [0, 1], [2.4, 1])})`,
              opacity: stampIn * stampOut * 0.92,
              border: `8px solid ${COLORS.crimson}`,
              color: COLORS.crimson,
              fontSize: 130,
              fontWeight: 900,
              padding: "0 40px",
              borderRadius: 10,
              background: "rgba(10,12,14,0.35)",
              whiteSpace: "nowrap",
            }}
          >
            {reveal.classifiedStamp}
          </div>

          <AbsoluteFill style={{ background: "linear-gradient(transparent 65%, rgba(10,12,14,0.9))" }} />

          <div
            style={{
              position: "absolute",
              top: 22,
              right: 22,
              border: `2px solid ${COLORS.gold}`,
              background: "rgba(10,12,14,0.75)",
              color: COLORS.gold,
              fontSize: 30,
              fontWeight: 800,
              padding: "4px 18px",
            }}
          >
            {reveal.simulationBadge}
          </div>

          <div
            style={{
              position: "absolute",
              bottom: 34,
              left: "50%",
              transform: `translateX(-50%) scale(${verifiedIn})`,
              opacity: verifiedIn,
              display: "flex",
              alignItems: "center",
              gap: 14,
              whiteSpace: "nowrap",
              border: `2px solid ${COLORS.gold}`,
              background: "rgba(10,12,14,0.85)",
              color: COLORS.lightGold,
              fontSize: 40,
              fontWeight: 800,
              padding: "10px 32px",
              borderRadius: 999,
              boxShadow: "0 0 30px rgba(212,175,55,0.4)",
            }}
          >
            <span
              style={{
                color: COLORS.ink,
                background: COLORS.gold,
                borderRadius: 999,
                width: 46,
                height: 46,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 32,
              }}
            >
              ✓
            </span>
            {reveal.verifiedLabel}
          </div>
        </div>
      </div>

      {/* Lower third: the reveal */}
      <div
        style={{
          position: "absolute",
          top: FRAME.top + FRAME.height + 26,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <div
          style={{
            background: COLORS.crimson,
            color: COLORS.white,
            fontSize: 56,
            fontWeight: 900,
            padding: "2px 34px 8px",
            transform: `skewX(-6deg) translateY(${(1 - titleIn) * 30}px)`,
            opacity: titleIn,
          }}
        >
          {reveal.titlePrefix}
        </div>
        <GlitchReveal intensity={nameGlitch} seed="name" slices={5} style={{ marginTop: 6 }}>
          <div
            style={{
              ...goldText,
              fontSize: 150,
              fontWeight: 900,
              lineHeight: 1.05,
              whiteSpace: "nowrap",
              letterSpacing: interpolate(nameIn, [0, 1], [24, 0]),
              filter: goldGlow(1.4),
              opacity: nameIn,
              transform: `scale(${interpolate(nameIn, [0, 1], [1.35, 1])})`,
            }}
          >
            {reveal.name}
          </div>
        </GlitchReveal>
      </div>

      <AbsoluteFill style={{ backgroundColor: COLORS.white, opacity: flash, pointerEvents: "none" }} />
    </AbsoluteFill>
  );
};
'''

FILES['src/scenes/Scene3Impact.tsx'] = r'''import React from "react";
import { AbsoluteFill, Img, interpolate, random, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { GoldCard } from "../components/GoldCard";
import type { PromoProps } from "../copy";
import { CLAMP, COLORS, GOLD_BORDER } from "../theme";
import { IMPACT_BEATS as B } from "../timing";

const PARTICLES = new Array(28).fill(0).map((_, i) => ({
  x: random(`p-x-${i}`) * 1080,
  y: random(`p-y-${i}`) * 1920,
  size: 3 + random(`p-s-${i}`) * 6,
  speed: 0.6 + random(`p-v-${i}`) * 1.6,
  phase: random(`p-ph-${i}`) * Math.PI * 2,
}));

// 10-16s: why he wears the crown — three achievement cards with counting stats.
export const Scene3Impact: React.FC<PromoProps> = ({ impact, images, framing }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const avatarIn = spring({ frame, fps, config: { damping: 12, stiffness: 120 } });
  const titleIn = spring({ frame: frame - B.titleIn, fps, config: { damping: 15, stiffness: 130 } });
  const underline = interpolate(frame, [B.titleIn + 8, B.titleIn + 28], [0, 1], CLAMP);

  return (
    <AbsoluteFill>
      {PARTICLES.map((p, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: p.x,
            top: (((p.y - frame * p.speed * 3) % 1920) + 1920) % 1920,
            width: p.size,
            height: p.size,
            borderRadius: p.size,
            background: COLORS.lightGold,
            opacity: 0.25 + 0.35 * Math.sin(frame / 10 + p.phase),
            boxShadow: `0 0 ${p.size * 3}px ${COLORS.gold}`,
          }}
        />
      ))}

      <div
        style={{
          position: "absolute",
          top: 300,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <div
          style={{
            width: 172,
            height: 172,
            padding: 5,
            borderRadius: "50%",
            background: `conic-gradient(from ${frame * 4}deg, ${COLORS.lightGold}, ${COLORS.darkGold}, ${COLORS.gold}, ${COLORS.lightGold})`,
            transform: `scale(${avatarIn})`,
            boxShadow: "0 0 50px rgba(212,175,55,0.45)",
          }}
        >
          <div
            style={{ width: "100%", height: "100%", borderRadius: "50%", overflow: "hidden", background: COLORS.ink }}
          >
            <Img
              src={staticFile(images.face)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                objectPosition: framing.avatarObjectPosition,
                transform: `scale(${framing.avatarScale})`,
              }}
            />
          </div>
        </div>
        <div
          style={{
            marginTop: 26,
            color: COLORS.white,
            fontSize: 68,
            fontWeight: 900,
            textAlign: "center",
            padding: "0 60px",
            lineHeight: 1.15,
            opacity: titleIn,
            transform: `translateY(${(1 - titleIn) * 40}px)`,
          }}
        >
          {impact.title}
        </div>
        <div style={{ marginTop: 18, height: 5, width: 420 * underline, borderRadius: 3, background: GOLD_BORDER }} />
      </div>

      <div
        style={{
          position: "absolute",
          top: 690,
          left: 60,
          right: 60,
          display: "flex",
          flexDirection: "column",
          gap: 34,
        }}
      >
        {impact.cards.map((card, i) => (
          <GoldCard key={i} {...card} index={i} delay={B.firstCard + i * B.cardStagger} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
'''

FILES['src/scenes/Scene4Outro.tsx'] = r'''import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { CtaButton } from "../components/CtaButton";
import { CrownLogo } from "../components/Icons";
import type { PromoProps } from "../copy";
import { CLAMP, COLORS, goldGlow, goldText } from "../theme";

// 16-20s: crest, tagline, call to action and the fine print.
export const Scene4Outro: React.FC<PromoProps> = ({ outro, images }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoIn = spring({ frame, fps, config: { damping: 10, stiffness: 110 } });
  const [nameLine, roleLine] = outro.tagline.includes(" - ") ? outro.tagline.split(" - ", 2) : [outro.tagline, ""];
  const nameIn = spring({ frame: frame - 10, fps, config: { damping: 14, stiffness: 120 } });
  const roleIn = spring({ frame: frame - 18, fps, config: { damping: 14, stiffness: 120 } });
  const lines = interpolate(frame, [18, 40], [0, 1], CLAMP);
  const socialsIn = interpolate(frame, [42, 56], [0, 1], CLAMP);
  const fineIn = interpolate(frame, [50, 64], [0, 1], CLAMP);

  return (
    <AbsoluteFill>
      {images.poster ? (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Img
            src={staticFile(images.poster)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "blur(16px) brightness(0.32) saturate(1.2)",
              transform: `scale(${1.15 + frame * 0.0012})`,
            }}
          />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill
        style={{
          background: `linear-gradient(${COLORS.ink} 0%, rgba(10,12,14,0.4) 35%, rgba(10,12,14,0.4) 65%, ${COLORS.ink} 100%)`,
        }}
      />

      {/* Expanding rings from the crest */}
      {[0, 1, 2].map((i) => {
        const t = ((frame + i * 20) % 60) / 60;
        const d = 260 + t * 700;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: 540 - d / 2,
              top: 470 - d / 2,
              width: d,
              height: d,
              borderRadius: "50%",
              border: `3px solid ${COLORS.gold}`,
              opacity: (1 - t) * 0.5 * logoIn,
            }}
          />
        );
      })}

      <div style={{ position: "absolute", top: 330, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
        <div
          style={{
            transform: `scale(${logoIn}) rotate(${(1 - logoIn) * -14}deg)`,
            filter: goldGlow(1.6),
          }}
        >
          <CrownLogo size={300} />
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          top: 660,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <div
          style={{
            ...goldText,
            fontSize: 140,
            fontWeight: 900,
            lineHeight: 1.1,
            whiteSpace: "nowrap",
            filter: goldGlow(1.3),
            opacity: nameIn,
            transform: `translateY(${(1 - nameIn) * 50}px)`,
          }}
        >
          {nameLine}
        </div>
        {roleLine ? (
          <div style={{ display: "flex", alignItems: "center", gap: 26, marginTop: 8, opacity: roleIn }}>
            <div
              style={{
                width: 150 * lines,
                height: 3,
                background: `linear-gradient(270deg, ${COLORS.gold}, transparent)`,
              }}
            />
            <div style={{ color: COLORS.white, fontSize: 84, fontWeight: 800, whiteSpace: "nowrap" }}>{roleLine}</div>
            <div
              style={{
                width: 150 * lines,
                height: 3,
                background: `linear-gradient(90deg, ${COLORS.gold}, transparent)`,
              }}
            />
          </div>
        ) : null}
      </div>

      <div
        style={{
          position: "absolute",
          top: 1080,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <CtaButton label={outro.cta} delay={26} />
        <div
          style={{
            marginTop: 40,
            color: COLORS.white,
            fontSize: 54,
            fontWeight: 700,
            direction: "ltr",
            opacity: socialsIn,
          }}
        >
          {outro.handle}
        </div>
        <div style={{ display: "flex", gap: 18, marginTop: 26, direction: "ltr", opacity: socialsIn }}>
          {outro.socials.map((s) => (
            <div
              key={s}
              style={{
                border: `2px solid ${COLORS.darkGold}`,
                color: COLORS.gold,
                fontSize: 32,
                fontWeight: 700,
                padding: "8px 26px",
                borderRadius: 999,
                background: "rgba(10,12,14,0.6)",
              }}
            >
              {s}
            </div>
          ))}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 250,
          left: 90,
          right: 90,
          textAlign: "center",
          color: COLORS.mutedText,
          fontSize: 27,
          fontWeight: 400,
          lineHeight: 1.4,
          opacity: fineIn * 0.85,
        }}
      >
        {outro.finePrint}
      </div>
    </AbsoluteFill>
  );
};
'''

FILES['src/theme.ts'] = r'''import type { CSSProperties } from "react";
import { loadFont } from "@remotion/google-fonts/Heebo";

const { fontFamily } = loadFont("normal", {
  weights: ["300", "400", "500", "700", "800", "900"],
  subsets: ["hebrew", "latin"],
});

export const FONT_FAMILY = fontFamily;

export const COLORS = {
  gold: "#D4AF37",
  darkGold: "#997A15",
  lightGold: "#F6E27A",
  ink: "#0A0C0E",
  crimson: "#E50914",
  grey: "#1F242D",
  white: "#FFFFFF",
  mutedText: "#AEB5C0",
  sapphire: "#1E3A8A",
} as const;

export const GOLD_GRADIENT = `linear-gradient(180deg, ${COLORS.lightGold} 0%, ${COLORS.gold} 45%, ${COLORS.darkGold} 100%)`;
export const GOLD_BORDER = `linear-gradient(135deg, ${COLORS.lightGold} 0%, ${COLORS.gold} 30%, ${COLORS.darkGold} 60%, ${COLORS.lightGold} 100%)`;

// Gradient-filled text. text-shadow would show through the transparent fill,
// so pair it with goldGlow() (a filter) rather than a text-shadow.
export const goldText: CSSProperties = {
  backgroundImage: GOLD_GRADIENT,
  WebkitBackgroundClip: "text",
  backgroundClip: "text",
  color: "transparent",
  WebkitTextFillColor: "transparent",
};

export const goldGlow = (strength = 1) =>
  `drop-shadow(0 0 ${Math.round(14 * strength)}px rgba(212,175,55,0.55)) drop-shadow(0 6px 4px rgba(0,0,0,0.85))`;

export const redGlow = (strength = 1) =>
  `0 0 ${Math.round(40 * strength)}px rgba(229,9,20,${Math.min(0.9, 0.6 * strength).toFixed(2)})`;

export const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Keep text clear of the phone UI that covers the top and bottom of vertical feeds.
export const SAFE = { top: 70, side: 60, bottom: 220 } as const;
'''

FILES['src/timing.ts'] = r'''export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

const sec = (s: number) => Math.round(s * FPS);

export const DURATION = sec(20); // 600 frames

// Four back-to-back scenes, 0-4s / 4-10s / 10-16s / 16-20s.
export const SCENES = {
  hook: { from: 0, duration: sec(4) },
  reveal: { from: sec(4), duration: sec(6) },
  impact: { from: sec(10), duration: sec(6) },
  outro: { from: sec(16), duration: sec(4) },
} as const;

// Frames where one scene cuts to the next; a glitch burst is centred on each.
export const CUTS = [SCENES.reveal.from, SCENES.impact.from, SCENES.outro.from];

export const SCENE_FADE = 8; // cross-fade length at each scene edge
export const GLITCH_SPAN = 6; // glitch burst reaches this many frames either side of a cut

// Persistent broadcast chrome (absolute frames).
export const HEADER = { from: SCENES.reveal.from - 10, until: SCENES.outro.from };
export const TICKER = { from: 24, until: SCENES.outro.from };

// Beats inside the reveal scene (frames relative to the scene start).
export const REVEAL_BEATS = {
  scanStart: 4,
  scanEnd: 40,
  glitchStart: 34,
  split: 56,
  splitSettled: 76,
  titleIn: 72,
  nameIn: 86,
  verifiedIn: 118,
} as const;

// Beats inside the impact scene.
export const IMPACT_BEATS = {
  titleIn: 4,
  firstCard: 24,
  cardStagger: 16,
} as const;
'''


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    unknown = flags - {"--install", "--force"}
    if unknown or len(args) > 1:
        print(__doc__)
        return 2
    target = Path(args[0]).resolve() if args else HERE
    force = "--force" in flags

    written = skipped = 0
    for rel, content in FILES.items():
        dest = target / rel
        if dest.exists() and not force:
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written += 1

    missing = []
    for src_rel, dest_rel in ASSETS.items():
        src, dest = HERE / src_rel, target / dest_rel
        if not src.exists():
            missing.append(dest_rel)
            continue
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)

    print(f"Remotion project in {target}: {written} file(s) written, {skipped} already present"
          + (" (use --force to overwrite)" if skipped else ""))
    if missing:
        print("Missing images; add them before rendering:")
        for m in missing:
            print(f"  {m}")

    if "--install" in flags:
        npm = shutil.which("npm")
        if not npm:
            print("npm not found; install Node.js 18+ and run `npm install` in the project.")
            return 1
        subprocess.run([npm, "install"], cwd=target, check=True)

    print("\nNext steps:")
    if target != Path.cwd():
        print(f"  cd {target}")
    if "--install" not in flags:
        print("  npm install")
    print("  npm start        # preview in Remotion Studio")
    print("  npm run build    # render out/ai-king-promo.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
