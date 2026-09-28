import React, {useMemo} from 'react';
import {AbsoluteFill, random, useCurrentFrame} from 'remotion';

/** Night-highway chase: streaking lights converging on a vanishing point. */
export const SpeedTunnel: React.FC<{hue?: number}> = ({hue = 20}) => {
  const frame = useCurrentFrame();
  const streaks = useMemo(
    () =>
      Array.from({length: 90}).map((_, i) => ({
        angle: random(`st-a-${i}`) * 360,
        speed: 0.02 + random(`st-s-${i}`) * 0.05,
        phase: random(`st-p-${i}`),
        warm: random(`st-w-${i}`) > 0.5,
      })),
    [],
  );
  return (
    <AbsoluteFill style={{background: 'radial-gradient(circle at 50% 50%, #0d0d18 0%, #000 70%)', overflow: 'hidden'}}>
      {streaks.map((s, i) => {
        const p = (s.phase + frame * s.speed) % 1; // 0 = vanishing point, 1 = off-screen
        const dist = p * p * 1400;
        const len = 40 + p * 520;
        const color = s.warm ? `hsl(${hue}, 100%, 60%)` : 'hsl(200, 100%, 85%)';
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: '50%',
              top: '50%',
              width: len,
              height: 2 + p * 5,
              transformOrigin: '0 50%',
              transform: `rotate(${s.angle}deg) translateX(${dist}px)`,
              background: `linear-gradient(90deg, transparent, ${color})`,
              boxShadow: `0 0 14px ${color}`,
              opacity: Math.min(1, p * 3),
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};
