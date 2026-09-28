import React from 'react';
import {AbsoluteFill} from 'remotion';
import {FilmGrain} from './FilmGrain';
import {Letterbox} from './Letterbox';
import {Vignette} from './Vignette';

/** The "grade": letterbox + vignette + grain + a subtle teal/orange split tone. */
export const CinematicFinish: React.FC<{letterbox?: number}> = ({letterbox = 1}) => (
  <AbsoluteFill style={{pointerEvents: 'none'}}>
    <AbsoluteFill
      style={{
        mixBlendMode: 'soft-light',
        opacity: 0.35,
        background: 'linear-gradient(180deg, rgba(0,70,110,0.9) 0%, rgba(0,0,0,0) 50%, rgba(255,140,40,0.6) 100%)',
      }}
    />
    <Vignette strength={0.7} />
    <FilmGrain opacity={0.1} />
    <Letterbox amount={letterbox} />
  </AbsoluteFill>
);
