import React from 'react';
import {random, useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';

const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&@Ø<>/\\|=+*';

type Props = {
  text: string;
  fontSize?: number;
  color?: string;
  /** 0..1 — how much of the text has "decoded" from random glyphs (left → right). */
  decode?: number;
  /** 0..1 — RGB ghosting / jitter amount. */
  glitch?: number;
  glow?: string;
  fontFamily?: string;
  letterSpacing?: string;
  style?: React.CSSProperties;
};

/** Neon terminal text that decodes from noise, with cyan/magenta ghosting. */
export const GlitchText: React.FC<Props> = ({
  text,
  fontSize = 64,
  color = '#ffffff',
  decode = 1,
  glitch = 0,
  glow = COLORS.neonCyan,
  fontFamily = FONTS.tech,
  letterSpacing = '0.18em',
  style,
}) => {
  const frame = useCurrentFrame();
  const revealed = Math.floor(text.length * decode);
  const shown = text
    .split('')
    .map((ch, i) => {
      if (ch === ' ' || i < revealed) return ch;
      return GLYPHS[Math.floor(random(`g-${text}-${i}-${Math.floor(frame / 2)}`) * GLYPHS.length)];
    })
    .join('');

  const jx = (random(`jx-${frame}`) - 0.5) * glitch * 24;
  const jy = (random(`jy-${frame}`) - 0.5) * glitch * 8;
  const base: React.CSSProperties = {
    fontFamily,
    fontSize,
    fontWeight: 900,
    letterSpacing,
    whiteSpace: 'pre',
    lineHeight: 1,
  };

  return (
    <div style={{position: 'relative', display: 'inline-block', ...style}}>
      {glitch > 0.02 && (
        <>
          <span style={{...base, position: 'absolute', inset: 0, color: COLORS.neonCyan, opacity: 0.8, transform: `translate(${jx + glitch * 10}px, ${jy}px)`, mixBlendMode: 'screen'}}>
            {shown}
          </span>
          <span style={{...base, position: 'absolute', inset: 0, color: COLORS.neonMagenta, opacity: 0.8, transform: `translate(${-jx - glitch * 10}px, ${-jy}px)`, mixBlendMode: 'screen'}}>
            {shown}
          </span>
        </>
      )}
      <span
        style={{
          ...base,
          position: 'relative',
          color,
          textShadow: `0 0 8px ${glow}, 0 0 24px ${glow}, 0 0 60px ${glow}`,
        }}
      >
        {shown}
      </span>
    </div>
  );
};
