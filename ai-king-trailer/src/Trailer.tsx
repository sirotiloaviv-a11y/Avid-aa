import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {ACTS} from './config/constants';
import {CUES} from './config/timeline';
import {lerp} from './lib/motion';
import {SoundDesign} from './audio/SoundDesign';
import {CinematicFinish} from './components/effects/CinematicFinish';
import {IntroScene} from './scenes/IntroScene';
import {RevealScene} from './scenes/RevealScene';
import {ChaosScene} from './scenes/ChaosScene';
import {ClimaxScene} from './scenes/ClimaxScene';

export type TrailerProps = {
  /** Render without sound (e.g. for silent previews). */
  muted?: boolean;
};

/**
 * THE AI KING REVEALED — master timeline (1800 frames @ 30fps).
 *
 *   00:00 ─ ACT I   cyber-underworld   (IntroScene)
 *   00:10 ─ ACT II  the reveal         (RevealScene)
 *   00:25 ─ ACT III chaos              (ChaosScene)
 *   00:50 ─ ACT IV  climax & end card  (ClimaxScene)
 */
export const Trailer: React.FC<TrailerProps> = ({muted = false}) => {
  const frame = useCurrentFrame();
  // Scope bars for the whole trailer, lifted for the full-frame poster.
  const letterbox = lerp(frame, [CUES.endScreen - 8, CUES.endScreen, CUES.endCard, CUES.endCard + 1], [1, 0, 0, 1]);

  return (
    <AbsoluteFill style={{background: '#000'}}>
      <Sequence name="ACT I — Intro" from={ACTS.intro.from} durationInFrames={ACTS.intro.durationInFrames}>
        <IntroScene />
      </Sequence>
      <Sequence name="ACT II — Reveal" from={ACTS.reveal.from} durationInFrames={ACTS.reveal.durationInFrames}>
        <RevealScene />
      </Sequence>
      <Sequence name="ACT III — Chaos" from={ACTS.chaos.from} durationInFrames={ACTS.chaos.durationInFrames}>
        <ChaosScene />
      </Sequence>
      <Sequence name="ACT IV — Climax" from={ACTS.climax.from} durationInFrames={ACTS.climax.durationInFrames}>
        <ClimaxScene />
      </Sequence>

      <CinematicFinish letterbox={letterbox} />
      {!muted && <SoundDesign />}
    </AbsoluteFill>
  );
};
