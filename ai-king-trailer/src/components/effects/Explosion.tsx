import React, {useMemo} from 'react';
import {AbsoluteFill, random, useCurrentFrame} from 'remotion';
import {EASE, lerp} from '../../lib/motion';

type Props = {
  at: number; // local frame of detonation
  x?: string; // CSS position of the blast centre
  y?: string;
  size?: number; // px radius at full bloom
  seed?: string;
};

/**
 * Procedural explosion: white-hot core → orange fireball → rolling smoke,
 * plus a shockwave ring and ballistic sparks with gravity.
 * Stand-in for real pyro footage; also layers nicely on top of it.
 */
export const Explosion: React.FC<Props> = ({at, x = '50%', y = '55%', size = 520, seed = 'boom'}) => {
  const frame = useCurrentFrame();
  const t = frame - at;

  const sparks = useMemo(
    () =>
      Array.from({length: 70}).map((_, i) => ({
        angle: random(`${seed}-a-${i}`) * Math.PI * 2,
        speed: 14 + random(`${seed}-s-${i}`) * 38,
        size: 2 + random(`${seed}-z-${i}`) * 5,
        life: 20 + random(`${seed}-l-${i}`) * 40,
      })),
    [seed],
  );

  if (t < 0 || t > 110) return null;

  const bloom = lerp(t, [0, 10, 60], [0.1, 1, 1.35], EASE.out);
  const coreOpacity = lerp(t, [0, 3, 20, 45], [0, 1, 0.8, 0]);
  const smokeOpacity = lerp(t, [8, 30, 110], [0, 0.85, 0]);
  const ring = lerp(t, [0, 26], [0, size * 3.2], EASE.out);
  const ringOpacity = lerp(t, [0, 4, 26], [0, 0.9, 0]);

  const centre: React.CSSProperties = {position: 'absolute', left: x, top: y, transform: 'translate(-50%, -50%)'};

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      {/* rolling smoke */}
      <div
        style={{
          ...centre,
          width: size * 2.6 * bloom,
          height: size * 2.2 * bloom,
          top: `calc(${y} - ${t * 1.6}px)`,
          borderRadius: '50%',
          opacity: smokeOpacity,
          background: 'radial-gradient(circle, rgba(40,30,28,0.95) 20%, rgba(25,20,20,0.6) 55%, transparent 72%)',
          filter: 'blur(18px)',
        }}
      />
      {/* fireball */}
      <div
        style={{
          ...centre,
          width: size * 2 * bloom,
          height: size * 1.7 * bloom,
          borderRadius: '50%',
          opacity: coreOpacity,
          mixBlendMode: 'screen',
          background:
            'radial-gradient(circle, #fffbe6 0%, #ffd36b 18%, #ff8a1f 38%, #d63a0a 58%, rgba(120,20,0,0.4) 70%, transparent 76%)',
          filter: 'blur(6px)',
        }}
      />
      {/* shockwave */}
      <div
        style={{
          ...centre,
          width: ring,
          height: ring * 0.45,
          borderRadius: '50%',
          border: '6px solid rgba(255,230,190,0.9)',
          opacity: ringOpacity,
          filter: 'blur(3px)',
        }}
      />
      {/* sparks */}
      {sparks.map((s, i) => {
        if (t > s.life) return null;
        const dx = Math.cos(s.angle) * s.speed * t;
        const dy = Math.sin(s.angle) * s.speed * t + 0.9 * t * t; // gravity
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: `calc(${x} + ${dx}px)`,
              top: `calc(${y} + ${dy}px)`,
              width: s.size,
              height: s.size * 3,
              borderRadius: s.size,
              background: '#ffd98a',
              boxShadow: '0 0 12px #ff9a2e',
              opacity: 1 - t / s.life,
              transform: `rotate(${(s.angle * 180) / Math.PI + 90}deg)`,
            }}
          />
        );
      })}
      {/* global light spill */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${x} ${y}, rgba(255,140,40,${coreOpacity * 0.55}), transparent 65%)`,
          mixBlendMode: 'screen',
        }}
      />
    </AbsoluteFill>
  );
};
