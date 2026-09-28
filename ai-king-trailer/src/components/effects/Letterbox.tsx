import React from 'react';
import {AbsoluteFill, useVideoConfig} from 'remotion';

/**
 * Anamorphic 2.39:1 bars. `amount` 0 → no bars, 1 → full scope crop.
 * Bar size is derived from the composition, so 9:16 renders get no bars.
 */
export const Letterbox: React.FC<{amount?: number; aspect?: number}> = ({amount = 1, aspect = 2.39}) => {
  const {width, height} = useVideoConfig();
  const bar = Math.max(0, (height - width / aspect) / 2) * amount;
  if (bar <= 0) return null;
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: bar, background: '#000'}} />
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: bar, background: '#000'}} />
    </AbsoluteFill>
  );
};
