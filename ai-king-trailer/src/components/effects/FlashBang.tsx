import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {lerp} from '../../lib/motion';

/**
 * Flash-bang transition: near-instant white-out that decays with a warm
 * over-exposed tail. `at` is a local frame.
 */
export const FlashBang: React.FC<{at: number; duration?: number; color?: string; peak?: number}> = ({
  at,
  duration = 18,
  color = '255,250,240',
  peak = 1,
}) => {
  const frame = useCurrentFrame();
  const t = frame - at;
  if (t < -2 || t > duration) return null;
  const opacity = lerp(t, [-2, 0, 3, duration], [0, peak, peak * 0.85, 0]);
  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
        background: `radial-gradient(circle at 50% 50%, rgba(${color},1) 0%, rgba(${color},0.92) 55%, rgba(255,200,140,0.8) 100%)`,
        opacity,
        mixBlendMode: 'screen',
      }}
    />
  );
};

/** Quick fade to/from black. */
export const DipToBlack: React.FC<{at: number; half?: number}> = ({at, half = 6}) => {
  const frame = useCurrentFrame();
  const opacity = lerp(frame, [at - half, at, at + half], [0, 1, 0]);
  if (opacity <= 0) return null;
  return <AbsoluteFill style={{background: '#000', opacity, pointerEvents: 'none'}} />;
};
