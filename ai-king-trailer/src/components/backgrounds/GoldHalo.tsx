import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';
import {EASE, lerp} from '../../lib/motion';

/**
 * The key-art set: midnight-blue velvet, a thin golden ring behind the
 * King's head and horizontal anamorphic light flares. `draw` 0→1 animates
 * the ring stroke on.
 */
export const GoldHalo: React.FC<{draw?: number; ringY?: number; ringR?: number}> = ({draw = 1, ringY = 470, ringR = 430}) => {
  const frame = useCurrentFrame();
  const circumference = 2 * Math.PI * ringR;
  const flare = 0.6 + Math.sin(frame / 9) * 0.15;
  const drift = lerp(frame, [0, 300], [0, 40], EASE.inOut);

  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse 70% 80% at 50% 45%, ${COLORS.royal} 0%, ${COLORS.midnight} 45%, ${COLORS.navy} 100%)`}}>
      {/* velvet curtain folds */}
      <AbsoluteFill
        style={{
          opacity: 0.35,
          backgroundImage: 'repeating-linear-gradient(90deg, rgba(0,0,0,0.6) 0px, rgba(40,60,140,0.25) 60px, rgba(0,0,0,0.6) 130px)',
          WebkitMaskImage: 'linear-gradient(90deg, #000 0%, transparent 30%, transparent 70%, #000 100%)',
          maskImage: 'linear-gradient(90deg, #000 0%, transparent 30%, transparent 70%, #000 100%)',
        }}
      />
      <svg width="100%" height="100%" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice" style={{position: 'absolute'}}>
        <defs>
          <linearGradient id="halo-gold" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={COLORS.goldLight} />
            <stop offset="0.5" stopColor={COLORS.gold} />
            <stop offset="1" stopColor={COLORS.goldDeep} />
          </linearGradient>
        </defs>
        <circle
          cx={960}
          cy={ringY}
          r={ringR}
          fill="none"
          stroke="url(#halo-gold)"
          strokeWidth={5}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - draw)}
          transform={`rotate(-90 960 ${ringY})`}
          style={{filter: 'drop-shadow(0 0 14px rgba(232,195,106,0.9))'}}
        />
        <circle cx={960} cy={ringY} r={ringR + 26} fill="none" stroke={COLORS.gold} strokeOpacity={0.25 * draw} strokeWidth={1.5} />
        {/* side light bars */}
        {[240, 290, 700].map((y, i) => (
          <g key={y} opacity={draw * flare}>
            <rect x={-drift} y={y} width={560} height={2} fill={COLORS.gold} opacity={0.7 - i * 0.15} />
            <rect x={1360 + drift} y={y} width={560} height={2} fill={COLORS.gold} opacity={0.7 - i * 0.15} />
          </g>
        ))}
      </svg>
      {/* anamorphic flare streaks */}
      {[0.22, 0.65].map((y, i) => (
        <div
          key={y}
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: `${y * 100}%`,
            height: 3,
            opacity: draw * flare * (i ? 0.5 : 0.8),
            background: 'linear-gradient(90deg, transparent 0%, rgba(255,215,140,0.9) 20%, transparent 45%, transparent 55%, rgba(255,215,140,0.9) 80%, transparent 100%)',
            filter: 'blur(1.5px)',
            boxShadow: '0 0 30px rgba(255,200,110,0.8)',
          }}
        />
      ))}
    </AbsoluteFill>
  );
};
