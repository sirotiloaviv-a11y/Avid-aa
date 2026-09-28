import React from 'react';
import {Audio, Sequence} from 'remotion';
import {AUDIO} from '../config/assets';
import {ACTS, TOTAL_FRAMES} from '../config/constants';
import {CUES, montageCuts} from '../config/timeline';
import {lerp} from '../lib/motion';

/** One-shot sound effect placed at an absolute frame. */
const Sfx: React.FC<{src: string; at: number; volume?: number; duration?: number; playbackRate?: number}> = ({
  src,
  at,
  volume = 1,
  duration = 150,
  playbackRate = 1,
}) => (
  <Sequence from={Math.max(0, at)} durationInFrames={duration} layout="none">
    <Audio src={src} volume={volume} playbackRate={playbackRate} />
  </Sequence>
);

/**
 * The full mix. Every hit reads from the shared cue sheet so it lands on
 * the same frame as its visual. Swap files in `config/assets.ts`.
 */
export const SoundDesign: React.FC = () => {
  const silenceStart = CUES.chaosSilenceStart;
  const riser = CUES.chaosRiserStart;

  return (
    <>
      {/* ── Score bed: ducks for the reveal hush and drops out for "UNTIL NOW." ── */}
      <Audio
        src={AUDIO.score}
        volume={(f) =>
          lerp(
            f,
            [0, 45, CUES.revealSplitStart - 20, CUES.revealSplitStart, CUES.revealMaskLift, silenceStart - 4, silenceStart, riser, riser + 20, TOTAL_FRAMES - 30, TOTAL_FRAMES],
            [0, 0.8, 0.8, 0.35, 0.9, 0.95, 0.05, 0.05, 0.9, 0.9, 0],
          )
        }
      />

      {/* ── ACT I ── */}
      <Sequence durationInFrames={ACTS.intro.durationInFrames + 20} layout="none">
        <Audio src={AUDIO.rain} loop volume={(f) => lerp(f, [0, 60, 280, 320], [0, 0.55, 0.55, 0])} />
      </Sequence>
      {CUES.introGlitches.map((f) => (
        <Sfx key={`ig${f}`} src={AUDIO.glitch} at={f} volume={0.6} duration={12} />
      ))}
      <Sfx src={AUDIO.riser} at={CUES.introWhipOut - 90} volume={0.5} duration={100} />
      <Sfx src={AUDIO.whoosh} at={CUES.introWhipOut - 6} volume={0.9} duration={30} />
      <Sfx src={AUDIO.braam} at={ACTS.reveal.from} volume={0.8} duration={90} />

      {/* ── ACT II ── */}
      <Sequence from={CUES.revealHeartbeatStart} durationInFrames={CUES.revealMaskLift - CUES.revealHeartbeatStart} layout="none">
        <Audio src={AUDIO.heartbeat} loop volume={(f) => lerp(f, [0, 30], [0, 0.9])} />
      </Sequence>
      {CUES.revealGlitches.map((f) => (
        <Sfx key={`rg${f}`} src={AUDIO.glitch} at={f} volume={0.55} duration={10} />
      ))}
      <Sfx src={AUDIO.riser} at={CUES.revealMaskLift - 120} volume={0.8} duration={125} />
      <Sfx src={AUDIO.impact} at={CUES.revealMaskLift} volume={1} duration={60} />
      <Sfx src={AUDIO.braam} at={CUES.revealMaskLift} volume={1} duration={120} />
      <Sfx src={AUDIO.whoosh} at={CUES.revealWhipOut} volume={0.9} duration={30} />

      {/* ── ACT III ── */}
      <Sequence from={ACTS.chaos.from} durationInFrames={150} layout="none">
        <Audio src={AUDIO.siren} loop volume={(f) => lerp(f, [0, 10, 120, 150], [0, 0.35, 0.35, 0])} />
      </Sequence>
      {CUES.chaosShots.map((f) => (
        <Sfx key={`cs${f}`} src={AUDIO.impact} at={f} volume={0.85} duration={45} />
      ))}
      <Sfx src={AUDIO.tinnitus} at={CUES.chaosFlashBang} volume={0.35} duration={70} />
      {CUES.chaosExplosions.map((f) => (
        <Sfx key={`ce${f}`} src={AUDIO.explosion} at={f} volume={1} duration={90} />
      ))}
      {montageCuts().map((c) => (
        <Sfx key={`mc${c.index}`} src={c.index % 2 ? AUDIO.whoosh : AUDIO.impact} at={c.from} volume={0.75} duration={Math.max(8, c.durationInFrames + 10)} />
      ))}
      <Sfx src={AUDIO.heartbeat} at={silenceStart + 6} volume={0.9} duration={50} />
      <Sfx src={AUDIO.riser} at={riser} volume={1} duration={60} playbackRate={2} />
      <Sfx src={AUDIO.impact} at={CUES.chaosWhiteOut} volume={1} duration={40} />

      {/* ── ACT IV ── */}
      <Sfx src={AUDIO.braam} at={CUES.titleSlam} volume={1} duration={120} />
      <Sfx src={AUDIO.impact} at={CUES.titleSlam} volume={1} duration={50} />
      <Sfx src={AUDIO.impact} at={CUES.titleSlam + 14} volume={0.7} duration={40} />
      <Sfx src={AUDIO.whoosh} at={CUES.keyArtBuild - 4} volume={0.6} duration={30} />
      <Sfx src={AUDIO.braam} at={CUES.hebrewTitleSlam} volume={0.9} duration={110} />
      <Sfx src={AUDIO.glitch} at={CUES.finalStinger} volume={0.7} duration={12} />
      <Sfx src={AUDIO.impact} at={CUES.finalStinger} volume={1} duration={18} />
    </>
  );
};
