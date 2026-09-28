import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {ACTS, COLORS} from '../config/constants';
import {CUES, local, montageCuts} from '../config/timeline';
import {EASE, handheld, impulse, lerp, shake} from '../lib/motion';
import {CityScape} from '../components/backgrounds/CityScape';
import {CodeWall} from '../components/backgrounds/CodeWall';
import {Corridor} from '../components/backgrounds/Corridor';
import {GoldHalo} from '../components/backgrounds/GoldHalo';
import {Searchlight} from '../components/backgrounds/Searchlight';
import {SpeedTunnel} from '../components/backgrounds/SpeedTunnel';
import {Explosion} from '../components/effects/Explosion';
import {FlashBang} from '../components/effects/FlashBang';
import {Glitch} from '../components/effects/Glitch';
import {NeonRain} from '../components/effects/NeonRain';
import {SirenLights} from '../components/effects/SirenLights';
import {WhipZoom} from '../components/effects/WhipZoom';
import {KingPortrait} from '../components/media/KingPortrait';
import {MediaSlot} from '../components/media/MediaSlot';
import {Caption} from '../components/text/Caption';
import {WordSlam} from '../components/text/WordSlam';

const L = (abs: number) => local(abs, ACTS.chaos.from);

/**
 * ACT III — 00:25–00:50 — CHAOS
 *
 * Six establishing action beats (SWAT breach, server-room hack, street
 * explosion, helicopter hunt, the King walking away from a fireball, the
 * chase), then an accelerating rapid-cut montage with word slams, a hard
 * drop to silence — "UNTIL NOW." — and a strobing riser into a white-out.
 */

/*
 * AI VIDEO PROMPT — slot `swatBreach`, 3s:
 * "First-person bodycam footage of a SWAT team breaching a steel door in a dark
 * concrete corridor, door blows inward with sparks and smoke, red laser sights cutting
 * through haze, red and blue police strobes, handheld shaky camera, high-contrast
 * action-movie grade, motion blur."
 */
const SwatShot: React.FC = () => (
  <>
    <MediaSlot slot="swatBreach" fallback={<Corridor />} />
    <SirenLights intensity={0.5} />
  </>
);

/*
 * AI VIDEO PROMPT — slot `serverRoom`, 3s:
 * "Endless dark server room, rows of racks with thousands of blinking blue LEDs
 * suddenly flash red one row after another like a wave, sparks burst from a rack,
 * alarm lights spinning, holographic screens full of scrolling code turning red.
 * Slow dolly forward, cinematic, cyber-thriller."
 */
const ServerShot: React.FC<{alert?: string; tint?: string}> = ({alert = 'ACCESS GRANTED · Ø', tint}) => (
  <MediaSlot slot="serverRoom" fallback={<CodeWall alert={alert} tint={tint} />} />
);

/*
 * AI VIDEO PROMPT — slot `streetExplosion`, 3s:
 * "Massive fireball explosion erupting from a black armored police SUV on a rain-soaked
 * neon-lit city street at night, glass and debris flying toward camera in slow motion,
 * shockwave rippling puddles, orange fire against magenta and cyan neon signs,
 * blockbuster action film, anamorphic lens flare."
 */
const ExplosionShot: React.FC<{at?: number[]}> = ({at = [15, 30]}) => {
  const frame = useCurrentFrame();
  const s = impulse(frame, at, 14);
  return (
    <AbsoluteFill style={{transform: shake(frame, s, 'boom')}}>
      <MediaSlot slot="streetExplosion" fallback={<CityScape push={2} />} />
      {at.map((f, i) => (
        <Explosion key={f} at={f} x={i ? '68%' : '38%'} y={i ? '60%' : '66%'} size={i ? 420 : 560} seed={`street${i}`} />
      ))}
      <NeonRain count={120} opacity={0.5} seed="street" />
    </AbsoluteFill>
  );
};

/*
 * AI VIDEO PROMPT — slot `helicopterRooftop`, 2s:
 * "Aerial shot from a police helicopter at night, a harsh white spotlight sweeping
 * across a wet skyscraper rooftop in heavy rain, searching, thermal-camera HUD overlay,
 * tense, cinematic."
 */
const HeliShot: React.FC = () => <MediaSlot slot="helicopterRooftop" fallback={<Searchlight />} />;

/*
 * AI VIDEO PROMPT — slot `kingWalksAway`, 2s (image-to-video from the mask photo):
 * "Slow-motion shot of a man in a black cyber mask with gold circuit patterns and a
 * golden crown walking calmly toward camera as a huge explosion erupts behind him,
 * long black coat with gold circuit embroidery, embers and debris floating, he does
 * not flinch. Epic hero shot, backlit by fire, 120fps slow motion."
 */
const KingWalksShot: React.FC<{boomAt: number}> = ({boomAt}) => {
  const frame = useCurrentFrame();
  return (
    <MediaSlot
      slot="kingWalksAway"
      fallback={
        <AbsoluteFill style={{background: '#050305'}}>
          <Explosion at={boomAt} x="50%" y="48%" size={760} seed="walk" />
          <AbsoluteFill style={{transform: `scale(${lerp(frame, [0, 60], [1, 1.1])})`}}>
            <KingPortrait kind="kingMask" eyeY={600} faceSize={300} style={{filter: 'brightness(0.55) contrast(1.4)'}} />
          </AbsoluteFill>
          <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 45%, rgba(255,120,30,0.25), transparent 60%)', mixBlendMode: 'screen'}} />
        </AbsoluteFill>
      }
    />
  );
};

/*
 * AI VIDEO PROMPT — slot `carChase`, 2s:
 * "Low tracking shot of a matte black sports car racing through a neon-lit tunnel at
 * night pursued by police cars with flashing red and blue lights, extreme speed, light
 * streaks, sparks from a scraping bumper, motion blur, handheld chase-cam energy."
 */
const ChaseShot: React.FC = () => (
  <>
    <MediaSlot slot="carChase" fallback={<SpeedTunnel />} />
    <SirenLights intensity={0.4} rate={4} />
  </>
);

/** Rotating pool of shots for the rapid-cut montage. */
const MONTAGE_POOL: React.FC<{i: number}>[] = [
  () => <SwatShot />,
  () => <ExplosionShot at={[0]} />,
  () => <ChaseShot />,
  () => <ServerShot alert="SYSTEM OVERRIDE" tint={COLORS.alarmRed} />,
  () => (
    <AbsoluteFill style={{background: COLORS.navy}}>
      <KingPortrait kind="kingMask" />
    </AbsoluteFill>
  ),
  () => <HeliShot />,
  () => <ExplosionShot at={[2]} />,
  () => (
    <AbsoluteFill style={{background: COLORS.navy}}>
      <KingPortrait kind="kingFace" />
    </AbsoluteFill>
  ),
];

const SLAMS: Record<number, {word: string; he: string}> = {
  1: {word: 'NO FACE', he: 'ללא פנים'},
  4: {word: 'NO NAME', he: 'ללא שם'},
  7: {word: 'NO LIMITS', he: 'ללא גבולות'},
};

export const ChaosScene: React.FC = () => {
  const frame = useCurrentFrame();
  const [swat, server, street, heli, walk, chase] = CUES.chaosShots.map(L);
  const cuts = montageCuts();

  return (
    <AbsoluteFill style={{background: '#000'}}>
      {/* ── Establishing action beats ─────────────────────── */}
      <Sequence from={swat} durationInFrames={server - swat}>
        <AbsoluteFill style={{transform: handheld(frame, 2.2)}}>
          <SwatShot />
        </AbsoluteFill>
      </Sequence>
      <Sequence from={server} durationInFrames={street - server}>
        <WhipZoom outFrames={6}>
          <ServerShot />
        </WhipZoom>
      </Sequence>
      <Sequence from={street} durationInFrames={heli - street}>
        <WhipZoom inFrames={6}>
          <ExplosionShot at={CUES.chaosExplosions.slice(0, 2).map((f) => L(f) - street)} />
        </WhipZoom>
      </Sequence>
      <Sequence from={heli} durationInFrames={walk - heli}>
        <HeliShot />
      </Sequence>
      <Sequence from={walk} durationInFrames={chase - walk}>
        <KingWalksShot boomAt={L(CUES.chaosExplosions[2]) - walk} />
      </Sequence>
      <Sequence from={chase} durationInFrames={L(CUES.chaosMontageStart) - chase}>
        <WhipZoom outFrames={6}>
          <ChaseShot />
        </WhipZoom>
      </Sequence>

      {/* ── Accelerating montage ──────────────────────────── */}
      {cuts.map((cut) => {
        const Shot = MONTAGE_POOL[cut.index % MONTAGE_POOL.length];
        const slam = SLAMS[cut.index];
        return (
          <Sequence key={cut.index} from={L(cut.from)} durationInFrames={cut.durationInFrames}>
            <MontageCut index={cut.index}>
              <Shot i={cut.index} />
            </MontageCut>
            {slam && <WordSlam word={slam.word} he={slam.he} />}
            <FlashBang at={0} duration={4} peak={0.45} />
          </Sequence>
        );
      })}

      {/* ── Silence: UNTIL NOW. ───────────────────────────── */}
      <Sequence from={L(CUES.chaosSilenceStart) + 10} durationInFrames={48}>
        <Caption text="Until now." he="עד עכשיו." size={96} tone="gold" />
      </Sequence>

      {/* ── Strobing riser into white-out ─────────────────── */}
      <Sequence from={L(CUES.chaosRiserStart)} durationInFrames={L(CUES.chaosWhiteOut) - L(CUES.chaosRiserStart) + 5}>
        <RiserStrobe />
      </Sequence>

      {/* captions over the establishing beats */}
      <Sequence from={swat + 12} durationInFrames={58}>
        <Caption text="They hunted him" he="הם צדו אותו" size={60} position="lower" />
      </Sequence>
      <Sequence from={server + 10} durationInFrames={60}>
        <Caption text="They feared him" he="הם פחדו ממנו" size={60} position="lower" />
      </Sequence>
      <Sequence from={street + 30} durationInFrames={44}>
        <Caption text="They tried to stop him" he="הם ניסו לעצור אותו" size={60} position="lower" />
      </Sequence>
      <Sequence from={walk + 6} durationInFrames={54}>
        <Caption text="He was never the target" he="הוא אף פעם לא היה המטרה" size={58} tone="gold" position="lower" />
      </Sequence>
      <Sequence from={chase + 6} durationInFrames={50}>
        <Caption text="He is the system" he="הוא המערכת" size={60} position="lower" />
      </Sequence>

      <FlashBang at={L(CUES.chaosFlashBang)} duration={24} />
      <FlashBang at={L(CUES.chaosWhiteOut)} duration={40} peak={1} />
    </AbsoluteFill>
  );
};

/** Each montage cut gets its own punch-in, shake and a random glitch. */
const MontageCut: React.FC<{index: number; children: React.ReactNode}> = ({index, children}) => {
  const frame = useCurrentFrame();
  const zoom = lerp(frame, [0, 10], [1.25, 1.05], EASE.out);
  const glitch = index % 3 === 2 ? impulse(frame, [0], 5) : 0;
  return (
    <AbsoluteFill style={{transform: `${shake(frame, lerp(frame, [0, 5], [0.9, 0.2]), `m${index}`)} scale(${zoom})`}}>
      <Glitch intensity={glitch} seed={`m${index}`}>
        {children}
      </Glitch>
    </AbsoluteFill>
  );
};

/*
 * AI VIDEO PROMPT — optional replacement for the riser strobe, 2s:
 * "Rapid strobe-lit alternating close-ups: a black-and-gold cyber mask, then the bare
 * face of a young bearded man with curly hair, flickering faster and faster in gold
 * light against midnight blue, pushing in on the eyes, ending in a blinding white flash."
 */
const RiserStrobe: React.FC = () => {
  const frame = useCurrentFrame();
  const period = frame < 20 ? 8 : frame < 36 ? 4 : 2;
  const showFace = Math.floor(frame / period) % 2 === 1;
  const zoom = lerp(frame, [0, 60], [1, 1.9], EASE.in);
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <GoldHalo draw={1} />
      <AbsoluteFill style={{transform: `scale(${zoom})`, transformOrigin: '50% 45%'}}>
        <KingPortrait kind={showFace ? 'kingFace' : 'kingMask'} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
