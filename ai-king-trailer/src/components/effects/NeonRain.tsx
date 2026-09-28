import React, {useMemo} from 'react';
import {AbsoluteFill, random, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS} from '../../config/constants';

type Props = {
  count?: number;
  angle?: number; // degrees of wind slant
  speed?: number;
  opacity?: number;
  seed?: string;
};

const TINTS = [COLORS.neonCyan, COLORS.neonMagenta, '#9fb4ff', '#ffffff', COLORS.neonViolet];

/**
 * Procedural neon rain. Fully deterministic per frame (no state), so it
 * scrubs and renders in parallel correctly.
 */
export const NeonRain: React.FC<Props> = ({count = 260, angle = 12, speed = 1, opacity = 0.8, seed = 'rain'}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();

  const drops = useMemo(
    () =>
      Array.from({length: count}).map((_, i) => {
        const depth = random(`${seed}-d-${i}`); // 0 far → 1 near
        return {
          x: random(`${seed}-x-${i}`) * (width + 400) - 200,
          offset: random(`${seed}-o-${i}`) * (height + 400),
          len: 40 + depth * 140,
          velocity: (38 + depth * 60) * speed,
          thickness: 1 + depth * 2.2,
          alpha: 0.25 + depth * 0.75,
          tint: TINTS[Math.floor(random(`${seed}-t-${i}`) * TINTS.length)],
          blur: depth > 0.85 ? 2 : 0,
        };
      }),
    [count, seed, width, height, speed],
  );

  return (
    <AbsoluteFill style={{pointerEvents: 'none', opacity, transform: `rotate(${angle}deg) scale(1.3)`}}>
      {drops.map((d, i) => {
        const y = ((frame * d.velocity + d.offset) % (height + 400)) - 200;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: d.x,
              top: y,
              width: d.thickness,
              height: d.len,
              opacity: d.alpha,
              borderRadius: d.thickness,
              background: `linear-gradient(180deg, transparent, ${d.tint})`,
              boxShadow: `0 0 ${6 * d.thickness}px ${d.tint}`,
              filter: d.blur ? `blur(${d.blur}px)` : undefined,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};
