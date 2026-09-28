import React, {useId} from 'react';
import {AbsoluteFill, random, useCurrentFrame} from 'remotion';
import {svgId} from '../../lib/motion';

type Props = {
  /** 0 = clean, 1 = full meltdown. Drive it with impulse(). */
  intensity: number;
  seed?: string;
  children: React.ReactNode;
};

/**
 * Digital glitch: RGB channel split + horizontally displaced slices + a
 * brief colour-inverted band. Children are re-rendered once per slice,
 * so keep glitched subtrees reasonably light.
 */
export const Glitch: React.FC<Props> = ({intensity, seed = 'glitch', children}) => {
  const frame = useCurrentFrame();
  const id = svgId('rgb', useId());

  if (intensity <= 0.01) return <AbsoluteFill>{children}</AbsoluteFill>;

  const offset = 4 + intensity * 26;
  const sliceCount = Math.round(3 + intensity * 9);
  const r = (k: string) => random(`${seed}-${frame}-${k}`);

  return (
    <AbsoluteFill>
      <svg width={0} height={0} style={{position: 'absolute'}}>
        <filter id={id} x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
          <feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r" />
          <feOffset in="r" dx={offset} dy={0} result="r2" />
          <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g" />
          <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b" />
          <feOffset in="b" dx={-offset} dy={offset * 0.2} result="b2" />
          <feBlend in="r2" in2="g" mode="screen" result="rg" />
          <feBlend in="rg" in2="b2" mode="screen" />
        </filter>
      </svg>

      <AbsoluteFill style={{filter: `url(#${id})`, transform: `translateX(${(r('base') - 0.5) * intensity * 30}px)`}}>
        {children}
      </AbsoluteFill>

      {Array.from({length: sliceCount}).map((_, i) => {
        if (r(`show${i}`) > 0.35 + intensity * 0.6) return null;
        const top = r(`top${i}`) * 95;
        const height = 1 + r(`h${i}`) * (4 + intensity * 12);
        const dx = (r(`dx${i}`) - 0.5) * intensity * 260;
        const invert = r(`inv${i}`) > 0.85;
        return (
          <AbsoluteFill
            key={i}
            style={{
              clipPath: `inset(${top}% 0 ${Math.max(0, 100 - top - height)}% 0)`,
              transform: `translateX(${dx}px)`,
              filter: invert ? 'invert(1) hue-rotate(180deg)' : `url(#${id})`,
            }}
          >
            {children}
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};
