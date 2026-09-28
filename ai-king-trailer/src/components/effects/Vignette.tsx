import React from 'react';
import {AbsoluteFill} from 'remotion';

export const Vignette: React.FC<{strength?: number; color?: string}> = ({strength = 0.75, color = '0,0,0'}) => (
  <AbsoluteFill
    style={{
      pointerEvents: 'none',
      background: `radial-gradient(ellipse 75% 70% at 50% 50%, rgba(${color},0) 45%, rgba(${color},${strength}) 100%)`,
    }}
  />
);
