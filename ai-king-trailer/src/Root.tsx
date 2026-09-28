import React from 'react';
import {Composition, Folder} from 'remotion';
import {ACTS, FPS, HEIGHT, TOTAL_FRAMES, WIDTH} from './config/constants';
import './config/fonts';
import {Trailer} from './Trailer';
import {IntroScene} from './scenes/IntroScene';
import {RevealScene} from './scenes/RevealScene';
import {ChaosScene} from './scenes/ChaosScene';
import {ClimaxScene} from './scenes/ClimaxScene';
import {CinematicFinish} from './components/effects/CinematicFinish';

/** Wrap an act so it previews with the same grade as the master. */
const graded = (Scene: React.FC) => {
  const Graded: React.FC = () => (
    <>
      <Scene />
      <CinematicFinish />
    </>
  );
  return Graded;
};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="AIKingTrailer"
      component={Trailer}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{muted: false}}
    />
    {/* Individual acts for fast iteration (silent — sound lives on the master timeline). */}
    <Folder name="Acts">
      <Composition id="Act1-Intro" component={graded(IntroScene)} durationInFrames={ACTS.intro.durationInFrames} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="Act2-Reveal" component={graded(RevealScene)} durationInFrames={ACTS.reveal.durationInFrames} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="Act3-Chaos" component={graded(ChaosScene)} durationInFrames={ACTS.chaos.durationInFrames} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="Act4-Climax" component={graded(ClimaxScene)} durationInFrames={ACTS.climax.durationInFrames} fps={FPS} width={WIDTH} height={HEIGHT} />
    </Folder>
  </>
);
