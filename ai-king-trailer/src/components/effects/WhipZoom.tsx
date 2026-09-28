import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {EASE, lerp} from '../../lib/motion';

type Props = {
  /** Frames of whip-zoom INTO the shot at its head (0 disables). */
  inFrames?: number;
  /** Frames of whip-zoom OUT of the shot at its tail (0 disables). */
  outFrames?: number;
  /** Peak scale during the whip. */
  peak?: number;
  children: React.ReactNode;
};

/**
 * Whip zoom: the shot punches into a motion-blurred zoom at its tail,
 * and the next shot decelerates out of one at its head. Wrap each shot of
 * a cut with it (uses the enclosing Sequence's duration).
 */
export const WhipZoom: React.FC<Props> = ({inFrames = 0, outFrames = 0, peak = 1.8, children}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  let scale = 1;
  let blur = 0;
  let brightness = 1;
  if (inFrames > 0 && frame < inFrames) {
    const p = lerp(frame, [0, inFrames], [1, 0], EASE.out);
    scale = 1 + (peak - 1) * p;
    blur = 24 * p;
    brightness = 1 + p * 0.6;
  }
  const tailStart = durationInFrames - outFrames;
  if (outFrames > 0 && frame >= tailStart) {
    const p = lerp(frame, [tailStart, durationInFrames], [0, 1], EASE.in);
    scale = 1 + (peak - 1) * p;
    blur = 24 * p;
    brightness = 1 + p * 0.6;
  }
  return (
    <AbsoluteFill
      style={{
        transform: `scale(${scale})`,
        filter: blur > 0.1 ? `blur(${blur}px) brightness(${brightness})` : undefined,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
