import React from 'react';
import {useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';
import {EASE, lerp} from '../../lib/motion';

type Props = {
  text: string;
  /** Local frame the title slams in. */
  at?: number;
  fontSize?: number;
  fontFamily?: string;
  dir?: 'ltr' | 'rtl';
  metal?: 'gold' | 'silver';
  letterSpacing?: string;
  style?: React.CSSProperties;
};

const GRADIENTS = {
  gold: `linear-gradient(180deg, ${COLORS.goldLight} 0%, #F4D78A 22%, ${COLORS.gold} 45%, #B8862B 60%, #F1D68E 78%, ${COLORS.goldDeep} 100%)`,
  silver: 'linear-gradient(180deg, #ffffff 0%, #E6E9EF 30%, #9aa3b2 55%, #f4f6fa 75%, #7d8595 100%)',
};

/**
 * Brushed-metal title with a travelling specular sheen, a bevel-style
 * shadow stack and a slam-in (scale-down + de-blur) at `at`.
 */
export const GoldTitle: React.FC<Props> = ({
  text,
  at = 0,
  fontSize = 150,
  fontFamily = FONTS.title,
  dir = 'ltr',
  metal = 'gold',
  letterSpacing = '0.04em',
  style,
}) => {
  const frame = useCurrentFrame();
  const t = frame - at;
  if (t < 0) return null;

  const scale = lerp(t, [0, 7], [1.45, 1], EASE.out);
  const blur = lerp(t, [0, 7], [16, 0]);
  const opacity = lerp(t, [0, 3], [0, 1]);
  const sheen = lerp(t, [4, 60], [-60, 160]);

  const shared: React.CSSProperties = {
    fontFamily,
    fontSize,
    fontWeight: 900,
    letterSpacing,
    lineHeight: 1.05,
    whiteSpace: 'nowrap',
  };

  return (
    <div dir={dir} style={{position: 'relative', display: 'inline-block', transform: `scale(${scale})`, opacity, filter: `blur(${blur}px)`, ...style}}>
      {/* extrusion / bevel shadow */}
      <span
        aria-hidden
        style={{
          ...shared,
          position: 'absolute',
          inset: 0,
          color: '#2a1a05',
          textShadow: '0 2px 0 #5a3a0c, 0 4px 0 #3d2707, 0 6px 0 #2a1a05, 0 14px 30px rgba(0,0,0,0.85)',
        }}
      >
        {text}
      </span>
      {/* metal face */}
      <span
        style={{
          ...shared,
          position: 'relative',
          backgroundImage: GRADIENTS[metal],
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
          color: 'transparent',
        }}
      >
        {text}
      </span>
      {/* moving specular sheen */}
      <span
        aria-hidden
        style={{
          ...shared,
          position: 'absolute',
          inset: 0,
          backgroundImage: `linear-gradient(105deg, transparent ${sheen - 12}%, rgba(255,255,255,0.95) ${sheen}%, transparent ${sheen + 12}%)`,
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
          color: 'transparent',
          mixBlendMode: 'screen',
        }}
      >
        {text}
      </span>
    </div>
  );
};
