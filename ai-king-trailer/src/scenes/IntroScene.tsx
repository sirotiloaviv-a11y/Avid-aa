import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {ACTS, COLORS} from '../config/constants';
import {CUES, local} from '../config/timeline';
import {FONTS} from '../config/fonts';
import {EASE, handheld, impulse, lerp} from '../lib/motion';
import {CityScape} from '../components/backgrounds/CityScape';
import {Glitch} from '../components/effects/Glitch';
import {NeonRain} from '../components/effects/NeonRain';
import {Scanlines} from '../components/effects/Scanlines';
import {WhipZoom} from '../components/effects/WhipZoom';
import {KingPortrait} from '../components/media/KingPortrait';
import {MediaSlot} from '../components/media/MediaSlot';
import {Caption} from '../components/text/Caption';
import {GlitchText} from '../components/text/GlitchText';

const L = (abs: number) => local(abs, ACTS.intro.from);

/**
 * ACT I — 00:00–00:10 — THE CYBER-UNDERWORLD
 *
 * Cold open on a dead signal, then a rain-soaked neon megacity that keeps
 * tearing apart with glitches. Subliminal frames of the masked King flicker
 * through the static before a whip-zoom throws us into the reveal.
 */

/*
 * AI VIDEO PROMPT — slot `introCity` (Runway Gen-4 / Sora / Luma Ray2), 8s, 16:9:
 * "Cinematic slow descending crane shot through a rain-drenched cyberpunk megacity at
 * night. Towering black skyscrapers covered in flickering magenta and cyan neon signs,
 * some in Hebrew. Heavy rain streaks lit by neon, wet streets reflecting light, drifting
 * fog, holographic billboards glitching. Anamorphic lens, shallow depth of field, teal
 * and magenta palette, deep crushed blacks, 35mm film grain, Blade Runner 2049 mood,
 * slow and ominous camera movement. No people in frame."
 *
 * AI VIDEO PROMPT — slot `introSilhouette`, 3s:
 * "Extreme close-up of a figure wearing a black geometric cyber mask with gold circuit
 * inlays and a golden crown with sapphire gems, emerging from total darkness. Only a
 * thin gold rim light reveals the edges. Digital static and data-moshing glitches tear
 * across the frame. Ominous, high contrast, cinematic."
 */
export const IntroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const glitch = impulse(frame, CUES.introGlitches.map(L), 7);
  const push = lerp(frame, [55, 300], [0, 1], EASE.inOut);

  return (
    <AbsoluteFill style={{background: COLORS.black}}>
      {/* ── Cold open: dead signal ───────────────────────── */}
      <Sequence durationInFrames={62}>
        <ColdOpen />
      </Sequence>

      {/* ── The city ──────────────────────────────────────── */}
      <Sequence from={55} durationInFrames={245}>
        <WhipZoom outFrames={8}>
          <Glitch intensity={glitch} seed="intro">
            <AbsoluteFill style={{transform: `${handheld(frame, 0.6)} scale(${1.02 + push * 0.14})`}}>
              <MediaSlot slot="introCity" fallback={<CityScape push={push * 6} />} />
            </AbsoluteFill>
          </Glitch>
          <NeonRain opacity={0.75} />
          <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,0.6) 0%, transparent 30%, transparent 70%, rgba(0,0,0,0.7) 100%)'}} />

          {/* subliminal King frames */}
          {CUES.introKingFlashes.map((abs, i) => (
            <Sequence key={abs} from={L(abs) - 55} durationInFrames={i === 2 ? 8 : 4}>
              <MediaSlot
                slot="introSilhouette"
                fallback={
                  <AbsoluteFill style={{background: '#000'}}>
                    <KingPortrait kind="kingMask" style={{filter: 'brightness(0.55) contrast(1.8) saturate(0.6)'}} />
                  </AbsoluteFill>
                }
              />
            </Sequence>
          ))}
        </WhipZoom>
      </Sequence>

      <Sequence from={95} durationInFrames={75}>
        <Caption text="In a world run by code" he="בעולם שנשלט על ידי קוד" />
      </Sequence>
      <Sequence from={180} durationInFrames={66}>
        <Caption text="One mind rose above the machine" he="תודעה אחת התעלתה מעל המכונה" size={68} />
      </Sequence>

      <Scanlines opacity={0.12 + glitch * 0.3} />
    </AbsoluteFill>
  );
};

const ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const typed = 'INCOMING TRANSMISSION';
  const chars = Math.floor(lerp(frame, [4, 22], [0, typed.length]));
  const cursor = Math.floor(frame / 6) % 2 === 0 ? '▌' : ' ';
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', background: '#000', gap: 40}}>
      <div style={{fontFamily: FONTS.tech, fontSize: 30, letterSpacing: '0.4em', color: 'rgba(0,240,255,0.8)'}}>
        {'> ' + typed.slice(0, chars) + cursor}
      </div>
      {frame >= 26 && (
        <GlitchText
          text="IDENTITY: ENCRYPTED"
          fontSize={72}
          decode={lerp(frame, [26, 50], [0, 1])}
          glitch={lerp(frame, [26, 34, 50, 60], [1, 0.3, 0.2, 1])}
          color={COLORS.silver}
          glow={COLORS.neonMagenta}
        />
      )}
    </AbsoluteFill>
  );
};
