import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';

/** Alternating red/blue police strobes washing across the frame. */
export const SirenLights: React.FC<{intensity?: number; rate?: number}> = ({intensity = 0.55, rate = 6}) => {
  const frame = useCurrentFrame();
  const phase = Math.floor(frame / rate) % 4; // R, off, B, off (double-flash feel)
  const red = phase === 0 ? 1 : phase === 1 ? 0.35 : 0;
  const blue = phase === 2 ? 1 : phase === 3 ? 0.35 : 0;
  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'screen'}}>
      <AbsoluteFill
        style={{
          opacity: red * intensity,
          background: `radial-gradient(ellipse 60% 80% at 0% 40%, ${COLORS.alarmRed}, transparent 70%)`,
        }}
      />
      <AbsoluteFill
        style={{
          opacity: blue * intensity,
          background: `radial-gradient(ellipse 60% 80% at 100% 40%, ${COLORS.swatBlue}, transparent 70%)`,
        }}
      />
    </AbsoluteFill>
  );
};
