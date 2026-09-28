import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';

/** CRT scanlines with a slow rolling refresh bar. */
export const Scanlines: React.FC<{opacity?: number}> = ({opacity = 0.18}) => {
  const frame = useCurrentFrame();
  const barY = ((frame * 9) % 140) - 20;
  return (
    <AbsoluteFill style={{pointerEvents: 'none', opacity}}>
      <AbsoluteFill
        style={{
          backgroundImage: 'repeating-linear-gradient(0deg, rgba(0,0,0,0.9) 0px, rgba(0,0,0,0.9) 1px, transparent 2px, transparent 4px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: `${barY}%`,
          height: '12%',
          background: 'linear-gradient(180deg, transparent, rgba(255,255,255,0.25), transparent)',
        }}
      />
    </AbsoluteFill>
  );
};
