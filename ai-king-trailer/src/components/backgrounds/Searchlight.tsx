import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {Hud} from './Corridor';
import {NeonRain} from '../effects/NeonRain';

/** Helicopter spotlight sweeping a rain-soaked rooftop. */
export const Searchlight: React.FC = () => {
  const frame = useCurrentFrame();
  const sweep = Math.sin(frame / 14) * 22;
  return (
    <AbsoluteFill style={{background: 'linear-gradient(180deg, #04060d 0%, #0a0f1e 60%, #121826 100%)', overflow: 'hidden'}}>
      {/* rooftop edge + antennae */}
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: '28%', background: '#05070c', borderTop: '2px solid #1b2236'}} />
      {[18, 63, 81].map((x) => (
        <div key={x} style={{position: 'absolute', left: `${x}%`, bottom: '28%', width: 6, height: 180, background: '#0c1020'}} />
      ))}
      {/* light cone */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '-10%',
          width: 900,
          height: '130%',
          marginLeft: -450,
          transformOrigin: '50% 0%',
          transform: `rotate(${sweep}deg)`,
          background: 'linear-gradient(180deg, rgba(220,235,255,0.75) 0%, rgba(220,235,255,0.12) 70%, transparent 100%)',
          clipPath: 'polygon(46% 0, 54% 0, 100% 100%, 0 100%)',
          mixBlendMode: 'screen',
          filter: 'blur(6px)',
        }}
      />
      <NeonRain count={140} speed={1.3} angle={18} opacity={0.6} seed="heli" />
      <Hud label="TARGET ACQUIRED" />
    </AbsoluteFill>
  );
};
