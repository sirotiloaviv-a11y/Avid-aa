import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {COLORS} from '../../config/constants';
import {FONTS} from '../../config/fonts';
import {lerp} from '../../lib/motion';

/**
 * SWAT breach stand-in: a one-point-perspective corridor, a door that
 * blows open, laser sights sweeping and a tactical HUD.
 */
export const Corridor: React.FC = () => {
  const frame = useCurrentFrame();
  const door = lerp(frame, [18, 24], [0, 1]);
  const push = lerp(frame, [0, 75], [1, 1.25]);
  return (
    <AbsoluteFill style={{background: '#030406', overflow: 'hidden'}}>
      <AbsoluteFill style={{transform: `scale(${push})`}}>
        {/* walls: nested frames receding to a vanishing point */}
        {Array.from({length: 9}).map((_, i) => {
          const inset = 4 + i * 5.2;
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: `${inset}%`,
                right: `${inset}%`,
                top: `${inset * 0.9}%`,
                bottom: `${inset * 0.9}%`,
                border: `2px solid rgba(90,110,140,${0.35 - i * 0.03})`,
              }}
            />
          );
        })}
        {/* door at the end, blowing open */}
        <div
          style={{
            position: 'absolute',
            left: '44%',
            width: '12%',
            top: '36%',
            height: '34%',
            background: `rgba(255,240,210,${door})`,
            boxShadow: `0 0 ${200 * door}px rgba(255,220,170,${door})`,
          }}
        />
        {/* laser sights */}
        {[0, 1, 2].map((i) => {
          const a = Math.sin(frame / (9 + i * 3) + i * 2) * 14 - 8 + i * 8;
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: `${10 + i * 35}%`,
                bottom: '5%',
                width: 3,
                height: '75%',
                transformOrigin: 'bottom center',
                transform: `rotate(${a}deg)`,
                background: `linear-gradient(0deg, transparent, ${COLORS.alarmRed})`,
                boxShadow: `0 0 12px ${COLORS.alarmRed}`,
                opacity: 0.8,
              }}
            />
          );
        })}
      </AbsoluteFill>
      <Hud label="BREACH · BREACH · BREACH" />
    </AbsoluteFill>
  );
};

/** Tactical camera HUD: corner brackets, REC dot, timecode and a label. */
export const Hud: React.FC<{label: string}> = ({label}) => {
  const frame = useCurrentFrame();
  const tc = `00:${String(Math.floor(frame / 30) + 12).padStart(2, '0')}:${String(frame % 30).padStart(2, '0')}`;
  const corner = (pos: React.CSSProperties) => (
    <div style={{position: 'absolute', width: 70, height: 70, borderColor: 'rgba(255,255,255,0.8)', borderStyle: 'solid', borderWidth: 0, ...pos}} />
  );
  return (
    <AbsoluteFill style={{fontFamily: FONTS.tech, color: 'rgba(255,255,255,0.85)', fontSize: 22, letterSpacing: '0.15em'}}>
      {corner({left: 80, top: 170, borderLeftWidth: 3, borderTopWidth: 3})}
      {corner({right: 80, top: 170, borderRightWidth: 3, borderTopWidth: 3})}
      {corner({left: 80, bottom: 170, borderLeftWidth: 3, borderBottomWidth: 3})}
      {corner({right: 80, bottom: 170, borderRightWidth: 3, borderBottomWidth: 3})}
      <div style={{position: 'absolute', left: 170, top: 185, display: 'flex', alignItems: 'center', gap: 12}}>
        <div style={{width: 16, height: 16, borderRadius: 8, background: Math.floor(frame / 15) % 2 ? COLORS.alarmRed : 'transparent'}} />
        REC · CAM-07
      </div>
      <div style={{position: 'absolute', right: 170, top: 185}}>{tc}</div>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 190, textAlign: 'center', color: COLORS.alarmRed}}>{label}</div>
      {/* reticle */}
      <div style={{position: 'absolute', left: '50%', top: '50%', width: 120, height: 120, marginLeft: -60, marginTop: -60, border: '2px solid rgba(255,40,40,0.8)', borderRadius: '50%'}} />
      <div style={{position: 'absolute', left: '50%', top: '50%', width: 4, height: 4, marginLeft: -2, marginTop: -2, background: COLORS.alarmRed}} />
    </AbsoluteFill>
  );
};
