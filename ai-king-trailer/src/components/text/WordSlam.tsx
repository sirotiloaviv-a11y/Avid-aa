import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';
import {EASE, lerp, shake} from '../../lib/motion';

/** A single huge word punched onto the screen for one montage beat. */
export const WordSlam: React.FC<{word: string; he?: string; color?: string}> = ({word, he, color = COLORS.silver}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const scale = lerp(frame, [0, 4, durationInFrames], [1.6, 1, 0.94], EASE.out);
  const opacity = lerp(frame, [0, 2, durationInFrames - 2, durationInFrames], [0, 1, 1, 0]);
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', opacity, transform: `${shake(frame, lerp(frame, [0, 6], [1, 0]), word)} scale(${scale})`}}>
      <div style={{fontFamily: FONTS.title, fontWeight: 900, fontSize: 220, letterSpacing: '0.12em', color, textShadow: '0 0 40px rgba(0,0,0,0.9), 0 0 80px rgba(232,195,106,0.35)'}}>
        {word}
      </div>
      {he && (
        <div dir="rtl" style={{fontFamily: FONTS.hebrew, fontWeight: 800, fontSize: 64, color: COLORS.gold, marginTop: 8}}>
          {he}
        </div>
      )}
    </AbsoluteFill>
  );
};
