import React from 'react';
import {AbsoluteFill, random, useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';

const HEX = '0123456789ABCDEF';

/** Server-room / hacker wall of scrolling hex with an alert banner. */
export const CodeWall: React.FC<{alert?: string; tint?: string}> = ({alert = 'ACCESS GRANTED', tint = COLORS.neonCyan}) => {
  const frame = useCurrentFrame();
  const cols = 34;
  const rows = 26;
  const blink = Math.floor(frame / 6) % 2 === 0;
  return (
    <AbsoluteFill style={{background: '#01040a', overflow: 'hidden'}}>
      <AbsoluteFill style={{transform: 'perspective(900px) rotateY(-18deg) scale(1.25)', transformOrigin: '30% 50%'}}>
        {Array.from({length: cols}).map((_, c) => (
          <div
            key={c}
            style={{
              position: 'absolute',
              left: `${(c / cols) * 100}%`,
              top: `${(((frame * (2 + random(`sp-${c}`) * 5)) % 60) - 60)}%`,
              fontFamily: FONTS.tech,
              fontSize: 20,
              lineHeight: '30px',
              color: tint,
              opacity: 0.25 + random(`op-${c}`) * 0.6,
              textShadow: `0 0 8px ${tint}`,
            }}
          >
            {Array.from({length: rows * 2}).map((__, r) => (
              <div key={r}>
                {HEX[Math.floor(random(`h-${c}-${r}-${Math.floor(frame / 3)}`) * 16)]}
                {HEX[Math.floor(random(`h2-${c}-${r}`) * 16)]}
              </div>
            ))}
          </div>
        ))}
      </AbsoluteFill>
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
        <div
          style={{
            padding: '18px 48px',
            border: `3px solid ${COLORS.alarmRed}`,
            background: 'rgba(40,0,0,0.75)',
            color: COLORS.alarmRed,
            fontFamily: FONTS.tech,
            fontWeight: 900,
            fontSize: 64,
            letterSpacing: '0.2em',
            opacity: blink ? 1 : 0.4,
            boxShadow: `0 0 60px ${COLORS.alarmRed}`,
          }}
        >
          {alert}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
