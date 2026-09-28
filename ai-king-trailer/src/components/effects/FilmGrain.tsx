import React, {useId} from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {svgId} from '../../lib/motion';

/** Animated 35mm-style grain. Re-seeds the noise every frame. */
export const FilmGrain: React.FC<{opacity?: number}> = ({opacity = 0.09}) => {
  const frame = useCurrentFrame();
  const id = svgId('grain', useId());
  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'overlay', opacity}}>
      <svg width="100%" height="100%">
        <filter id={id}>
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={frame % 97} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#${id})`} />
      </svg>
    </AbsoluteFill>
  );
};
