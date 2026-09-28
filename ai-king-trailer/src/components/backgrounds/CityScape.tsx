import React, {useMemo} from 'react';
import {AbsoluteFill, random, useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';

type Building = {x: number; w: number; h: number; windows: {x: number; y: number; c: string; flicker: number}[]};

const SIGNS = [
  {text: 'ØNLINE', color: COLORS.neonMagenta, x: 12, y: 38},
  {text: 'מלך', color: COLORS.neonCyan, x: 71, y: 30},
  {text: 'NO SIGNAL', color: COLORS.alarmRed, x: 44, y: 46},
  {text: 'AI', color: COLORS.gold, x: 88, y: 42},
];

const layer = (seed: string, count: number, minH: number, maxH: number): Building[] => {
  let x = -2;
  return Array.from({length: count}).map((_, i) => {
    const w = 3 + random(`${seed}-w-${i}`) * 7;
    const h = minH + random(`${seed}-h-${i}`) * (maxH - minH);
    const windows = Array.from({length: Math.floor(h / 3)}).flatMap((__, row) =>
      Array.from({length: Math.max(1, Math.floor(w / 1.6))}).map((___, col) => {
        const r = random(`${seed}-win-${i}-${row}-${col}`);
        return {
          x: col * 1.6 + 0.4,
          y: row * 3 + 1,
          c: r > 0.93 ? COLORS.neonMagenta : r > 0.86 ? COLORS.neonCyan : r > 0.6 ? '#ffd79a' : 'transparent',
          flicker: random(`${seed}-f-${i}-${row}-${col}`),
        };
      }),
    );
    const b = {x, w, h, windows};
    x += w + random(`${seed}-g-${i}`) * 1.5;
    return b;
  });
};

/**
 * Procedural neon megacity at night — stand-in for the intro establishing shot.
 * Units are % of the frame so it scales to any aspect ratio.
 */
export const CityScape: React.FC<{push?: number}> = ({push = 0}) => {
  const frame = useCurrentFrame();
  const far = useMemo(() => layer('far', 22, 25, 55), []);
  const near = useMemo(() => layer('near', 16, 35, 75), []);

  const renderLayer = (buildings: Building[], tone: string, parallax: number) => (
    <AbsoluteFill style={{transform: `translateX(${-push * parallax}%) scale(${1 + push * parallax * 0.01})`}}>
      {buildings.map((b, i) => (
        <div
          key={i}
          style={{position: 'absolute', left: `${b.x}%`, bottom: 0, width: `${b.w}%`, height: `${b.h}%`, background: tone, overflow: 'hidden'}}
        >
          {b.windows.map((w, j) =>
            w.c === 'transparent' || (w.flicker > 0.97 && Math.floor(frame / 5) % 2 === 0) ? null : (
              <div
                key={j}
                style={{
                  position: 'absolute',
                  left: `${(w.x / b.w) * 100}%`,
                  top: `${(w.y / b.h) * 100}%`,
                  width: `${(0.8 / b.w) * 100}%`,
                  height: `${(1.2 / b.h) * 100}%`,
                  background: w.c,
                  opacity: 0.55,
                  boxShadow: `0 0 6px ${w.c}`,
                }}
              />
            ),
          )}
        </div>
      ))}
    </AbsoluteFill>
  );

  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, #02030a 0%, ${COLORS.midnight} 55%, #2a0b3a 100%)`}}>
      {/* sky glow + fog */}
      <AbsoluteFill style={{background: 'radial-gradient(ellipse 80% 40% at 50% 85%, rgba(255,43,214,0.35), transparent 70%)'}} />
      {renderLayer(far, '#070a1a', 2)}
      {SIGNS.map((s, i) => {
        const on = random(`sign-${i}-${Math.floor(frame / 3)}`) > 0.08;
        return (
          <div
            key={i}
            dir="auto"
            style={{
              position: 'absolute',
              left: `${s.x}%`,
              top: `${s.y}%`,
              fontFamily: FONTS.tech,
              fontWeight: 900,
              fontSize: 42,
              color: s.color,
              opacity: on ? 0.9 : 0.15,
              textShadow: `0 0 10px ${s.color}, 0 0 40px ${s.color}`,
              transform: `translateX(${-push * 3}%)`,
            }}
          >
            {s.text}
          </div>
        );
      })}
      {renderLayer(near, '#03040c', 4)}
      <AbsoluteFill style={{background: 'linear-gradient(0deg, rgba(10,12,30,0.9) 0%, transparent 35%)'}} />
    </AbsoluteFill>
  );
};
