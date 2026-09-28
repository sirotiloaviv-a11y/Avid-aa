import React from 'react';
import {AbsoluteFill, Img, Sequence, useCurrentFrame} from 'remotion';
import {ACTS, COLORS} from '../config/constants';
import {CUES, local} from '../config/timeline';
import {FONTS} from '../config/fonts';
import {IMAGES} from '../config/assets';
import {EASE, fadeInOut, impulse, lerp, shake} from '../lib/motion';
import {GoldHalo} from '../components/backgrounds/GoldHalo';
import {FlashBang} from '../components/effects/FlashBang';
import {Glitch} from '../components/effects/Glitch';
import {KingPortrait} from '../components/media/KingPortrait';
import {MediaSlot} from '../components/media/MediaSlot';
import {GoldTitle} from '../components/text/GoldTitle';
import {GlitchText} from '../components/text/GlitchText';

const L = (abs: number) => local(abs, ACTS.climax.from);

/**
 * ACT IV — 00:50–01:00 — CLIMAX, TITLE CARD & END SCREEN
 *
 * Out of the white-out: "THE AI KING / REVEALED" slams in with a shockwave.
 * The key art assembles live — halo, half-mask / half-man, Hebrew title —
 * then the finished poster, the billing block, and a final Ø stinger.
 */

/*
 * AI VIDEO PROMPT — slot `titleBackground`, 4s, loopable:
 * "Slow-motion golden dust and embers drifting through volumetric light in a dark
 * midnight-blue void, a thin ring of golden light slowly rotating in the centre,
 * horizontal anamorphic gold flares, luxurious, epic, perfect for a movie title card.
 * No text."
 */
export const ClimaxScene: React.FC = () => {
  const frame = useCurrentFrame();
  const keyArt = L(CUES.keyArtBuild);
  const endScreen = L(CUES.endScreen);
  const endCard = L(CUES.endCard);
  const stinger = L(CUES.finalStinger);

  return (
    <AbsoluteFill style={{background: '#000'}}>
      <Sequence durationInFrames={keyArt}>
        <TitleSlam />
      </Sequence>
      <Sequence from={keyArt} durationInFrames={endScreen - keyArt}>
        <KeyArtBuild hebrewAt={L(CUES.hebrewTitleSlam) - keyArt} />
      </Sequence>
      <Sequence from={endScreen} durationInFrames={endCard - endScreen}>
        <PosterHold />
      </Sequence>
      <Sequence from={endCard} durationInFrames={stinger - endCard}>
        <BillingBlock />
      </Sequence>
      <Sequence from={stinger}>
        <Stinger />
      </Sequence>

      {/* carry the white-out from ACT III across the cut */}
      <AbsoluteFill style={{background: '#fff', opacity: lerp(frame, [0, 14], [1, 0]), pointerEvents: 'none'}} />
      <FlashBang at={L(CUES.hebrewTitleSlam)} duration={14} peak={0.7} />
    </AbsoluteFill>
  );
};

const TitleSlam: React.FC = () => {
  const frame = useCurrentFrame();
  const slam = L(CUES.titleSlam);
  const hit = impulse(frame, [slam, slam + 14], 12);
  const ring = lerp(frame - slam, [0, 24], [0, 2600], EASE.out);
  return (
    <AbsoluteFill style={{transform: shake(frame, hit * 0.7, 'title')}}>
      <MediaSlot slot="titleBackground" fallback={<GoldHalo draw={lerp(frame, [0, 40], [0, 0.6])} />} style={{opacity: 0.55}} />
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          width: ring,
          height: ring * 0.3,
          transform: 'translate(-50%, -50%)',
          borderRadius: '50%',
          border: `4px solid ${COLORS.gold}`,
          opacity: lerp(frame - slam, [0, 24], [0.9, 0]),
          filter: 'blur(2px)',
        }}
      />
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', transform: `scale(${lerp(frame, [slam, 60], [1, 1.06])})`}}>
        <GoldTitle text="THE AI KING" at={slam} fontSize={190} letterSpacing="0.08em" />
        <div style={{height: 12}} />
        <GoldTitle text="REVEALED" at={slam + 14} fontSize={96} metal="silver" letterSpacing="0.6em" />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** The poster, assembled live: halo → half/half portrait → Hebrew title → name. */
const KeyArtBuild: React.FC<{hebrewAt: number}> = ({hebrewAt}) => {
  const frame = useCurrentFrame();
  const push = lerp(frame, [0, 130], [1.08, 1], EASE.out);
  const lineW = lerp(frame, [hebrewAt + 20, hebrewAt + 40], [0, 420], EASE.out);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{transform: `scale(${push})`}}>
        <GoldHalo draw={lerp(frame, [0, 30], [0, 1], EASE.out)} ringY={430} ringR={400} />
        <KingPortrait kind="kingFace" eyeY={430} faceSize={300} />
        <AbsoluteFill style={{clipPath: 'inset(0 960px 0 0)'}}>
          <KingPortrait kind="kingMask" eyeY={430} faceSize={300} />
        </AbsoluteFill>
        <AbsoluteFill style={{background: 'linear-gradient(0deg, rgba(5,10,28,0.95) 0%, rgba(5,10,28,0.6) 28%, transparent 50%)'}} />
      </AbsoluteFill>
      <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 150}}>
        <GoldTitle text="מלך ה-AI נחשף" at={hebrewAt} dir="rtl" fontFamily={FONTS.hebrew} fontSize={170} letterSpacing="0" />
        <div style={{display: 'flex', alignItems: 'center', gap: 36, marginTop: 6}}>
          <div style={{width: lineW, height: 3, background: `linear-gradient(90deg, transparent, ${COLORS.gold})`}} />
          <GoldTitle text="אביב סנאנס" at={hebrewAt + 18} dir="rtl" metal="silver" fontFamily={FONTS.hebrew} fontSize={76} letterSpacing="0" />
          <div style={{width: lineW, height: 3, background: `linear-gradient(270deg, transparent, ${COLORS.gold})`}} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** The finished key art full-bleed with "COMING SOON". Letterbox is lifted here. */
const PosterHold: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: COLORS.navy}}>
      <AbsoluteFill style={{transform: `scale(${lerp(frame, [0, 70], [1.0, 1.06])})`}}>
        <Img src={IMAGES.keyArt} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </AbsoluteFill>
      <AbsoluteFill style={{alignItems: 'center', paddingTop: 44}}>
        <div
          style={{
            display: 'flex',
            gap: 28,
            alignItems: 'center',
            fontFamily: FONTS.title,
            fontWeight: 700,
            fontSize: 34,
            letterSpacing: '0.5em',
            color: COLORS.gold,
            opacity: lerp(frame, [10, 24], [0, 1]),
            textShadow: '0 0 20px rgba(0,0,0,0.9)',
          }}
        >
          <span>COMING SOON</span>
          <span style={{opacity: 0.6}}>·</span>
          <span dir="rtl" style={{fontFamily: FONTS.hebrew, letterSpacing: '0.1em'}}>
            בקרוב
          </span>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Condensed trailer billing block + hashtag. */
const BillingBlock: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = fadeInOut(frame, 26, 6, 4);
  return (
    <AbsoluteFill style={{background: '#000', justifyContent: 'center', alignItems: 'center', opacity}}>
      <div style={{fontFamily: FONTS.condensed, fontWeight: 300, fontSize: 26, color: '#c9ccd4', letterSpacing: '0.12em', textAlign: 'center', lineHeight: 1.6, maxWidth: 1300, transform: 'scaleY(1.35)'}}>
        ZERØ-DAY PICTURES PRESENTS · A NEURAL CROWN PRODUCTION · <b style={{fontWeight: 600}}>AVIV SANANES</b> · "THE AI KING REVEALED"
        <br />
        WRITTEN BY THE MACHINE · DIRECTED BY THE MAN · MUSIC BY THE NOISE · VISUAL EFFECTS BY PURE CODE
      </div>
      <div style={{marginTop: 50, fontFamily: FONTS.tech, fontWeight: 500, fontSize: 30, letterSpacing: '0.35em', color: COLORS.gold}}>#THEAIKINGREVEALED</div>
    </AbsoluteFill>
  );
};

/** Final beat: the Ø sigil glitches on, one last bass hit. */
const Stinger: React.FC = () => {
  const frame = useCurrentFrame();
  const glitch = impulse(frame, [0, 6, 10], 4);
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <Glitch intensity={glitch} seed="stinger">
        <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
          <GlitchText text="Ø" fontSize={260} fontFamily={FONTS.title} color={COLORS.gold} glow={COLORS.gold} letterSpacing="0" glitch={glitch} />
        </AbsoluteFill>
      </Glitch>
    </AbsoluteFill>
  );
};
