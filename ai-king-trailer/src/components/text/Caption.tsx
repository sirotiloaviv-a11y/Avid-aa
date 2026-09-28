import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';
import {EASE, fadeInOut, lerp} from '../../lib/motion';

type Props = {
  text: string;
  /** Hebrew subtitle line under the English card. */
  he?: string;
  size?: number;
  tone?: 'white' | 'gold';
  position?: 'center' | 'lower';
};

/**
 * Classic trailer card: tracking-out serif caps that blur in and drift,
 * with a Hebrew subtitle. Its timing comes from the enclosing <Sequence>.
 */
export const Caption: React.FC<Props> = ({text, he, size = 76, tone = 'white', position = 'center'}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  const opacity = fadeInOut(frame, durationInFrames, 14, 10);
  const blur = lerp(frame, [0, 16], [14, 0], EASE.out);
  const tracking = lerp(frame, [0, durationInFrames], [0.22, 0.34]);
  const scale = lerp(frame, [0, durationInFrames], [1.04, 1]);

  const fill =
    tone === 'gold'
      ? {
          backgroundImage: `linear-gradient(180deg, ${COLORS.goldLight} 0%, ${COLORS.gold} 45%, ${COLORS.goldDeep} 100%)`,
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
          color: 'transparent',
          filter: `drop-shadow(0 0 18px rgba(232,195,106,0.45)) blur(${blur}px)`,
        }
      : {color: COLORS.silver, textShadow: '0 0 30px rgba(160,190,255,0.35)', filter: `blur(${blur}px)`};

  return (
    <AbsoluteFill
      style={{
        justifyContent: position === 'center' ? 'center' : 'flex-end',
        alignItems: 'center',
        paddingBottom: position === 'lower' ? 190 : 0,
        opacity,
        transform: `scale(${scale})`,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.title,
          fontWeight: 900,
          fontSize: size,
          letterSpacing: `${tracking}em`,
          textAlign: 'center',
          textTransform: 'uppercase',
          padding: '0 80px',
          ...fill,
        }}
      >
        {text}
      </div>
      {he && (
        <div
          dir="rtl"
          style={{
            marginTop: 22,
            fontFamily: FONTS.hebrew,
            fontWeight: 400,
            fontSize: size * 0.42,
            letterSpacing: '0.08em',
            color: 'rgba(230,233,239,0.8)',
            filter: `blur(${blur}px)`,
          }}
        >
          {he}
        </div>
      )}
    </AbsoluteFill>
  );
};
