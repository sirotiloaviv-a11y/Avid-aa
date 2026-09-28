import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {ACTS, COLORS} from '../config/constants';
import {CUES, local} from '../config/timeline';
import {FONTS} from '../config/fonts';
import {EASE, handheld, impulse, lerp, shake} from '../lib/motion';
import {GoldHalo} from '../components/backgrounds/GoldHalo';
import {FlashBang} from '../components/effects/FlashBang';
import {Glitch} from '../components/effects/Glitch';
import {WhipZoom} from '../components/effects/WhipZoom';
import {KingPortrait} from '../components/media/KingPortrait';
import {MediaSlot} from '../components/media/MediaSlot';
import {Caption} from '../components/text/Caption';
import {GoldTitle} from '../components/text/GoldTitle';

const L = (abs: number) => local(abs, ACTS.reveal.from);

/** Screen x where the mask/face split ends up — the centre of the face. */
const SPLIT_X = 960;

/**
 * ACT II — 00:10–00:25 — THE REVEAL
 *
 * The AI King surfaces from the dark under a golden halo. His mask glitches
 * as a heartbeat builds, then a glowing seam splits it down the middle —
 * the half-mask / half-man key-art frame — before the mask lifts away in
 * a flash-bang to reveal the young man underneath.
 */

/*
 * AI VIDEO PROMPT — slot `revealThrone` (background plate), 15s, 16:9, locked-off:
 * "Dark royal throne room in deep midnight blue velvet, a large thin golden ring of
 * light hovering behind where a head would be, horizontal gold anamorphic light
 * flares, drifting dust particles in volumetric light, luxurious and ominous, symmetrical
 * composition, cinematic, 8K. Empty frame, no people."
 *
 * AI VIDEO PROMPT — full-performance alternative (image-to-video from the mask photo):
 * "A figure in a black geometric cyber mask with gold circuit patterns and a golden
 * crown marked 'AI' slowly raises both hands and lifts the mask and crown off his head,
 * revealing a handsome young man in his twenties with curly brown hair, a short beard
 * and intense brown eyes. He stares straight into the lens. Midnight blue background
 * with a golden halo ring, gold rim lighting, shallow depth of field, slow motion
 * 120fps, epic movie-trailer reveal."
 */
export const RevealScene: React.FC = () => {
  const frame = useCurrentFrame();

  const splitStart = L(CUES.revealSplitStart);
  const splitHold = L(CUES.revealSplitHold);
  const lift = L(CUES.revealMaskLift);

  const emerge = lerp(frame, [0, 110], [0.12, 1], EASE.out);
  const haloDraw = lerp(frame, [20, 130], [0, 1], EASE.inOut);
  const glitch = impulse(frame, CUES.revealGlitches.map(L), 6);
  const heartbeat = frame > L(CUES.revealHeartbeatStart) && frame < splitStart ? Math.max(0, Math.sin(frame / 3.2)) ** 8 * 0.012 : 0;
  const push = lerp(frame, [0, 450], [1, 1.12]) + heartbeat;

  // Mask clip edge sweeps right → centre, then the mask lifts off.
  const edgeX = lerp(frame, [splitStart, splitHold], [1340, SPLIT_X], EASE.inOut);
  const liftT = frame - lift;
  const maskY = lerp(liftT, [0, 34], [0, -1100], EASE.in);
  const maskRot = lerp(liftT, [0, 34], [0, -9], EASE.in);
  const seamOpacity = lerp(frame, [splitStart, splitStart + 8, lift - 4, lift], [0, 1, 1, 0]);
  const impact = impulse(frame, [lift], 16);

  const faceOpacity = lerp(frame, [splitStart - 2, splitStart + 4], [0, 1]);
  const sweep = lerp(frame, [lift + 30, lift + 110], [-40, 140]);

  return (
    <AbsoluteFill style={{background: COLORS.navy}}>
      <WhipZoom inFrames={8} outFrames={10}>
        <AbsoluteFill style={{transform: `${shake(frame, impact * 0.8, 'reveal')} ${handheld(frame, 0.4)} scale(${push})`}}>
          <MediaSlot slot="revealThrone" fallback={<GoldHalo draw={haloDraw} />} style={{opacity: lerp(frame, [0, 60], [0.2, 1])}} />

          <Glitch intensity={glitch} seed="reveal">
            {/* the man — always underneath */}
            <KingPortrait kind="kingFace" style={{opacity: faceOpacity}} />
            {/* light sweep across the face after the reveal */}
            <AbsoluteFill
              style={{
                mixBlendMode: 'overlay',
                background: `linear-gradient(115deg, transparent ${sweep - 15}%, rgba(255,230,180,0.7) ${sweep}%, transparent ${sweep + 15}%)`,
              }}
            />
            {/* the mask — clipped to the left of the seam, then lifted away */}
            <AbsoluteFill
              style={{
                clipPath: `inset(0 ${1920 - edgeX}px 0 0)`,
                transform: `translateY(${maskY}px) rotate(${maskRot}deg)`,
                transformOrigin: '50% 20%',
                filter: `brightness(${emerge})`,
              }}
            >
              <KingPortrait kind="kingMask" />
            </AbsoluteFill>
          </Glitch>

          {/* glowing seam between machine and man */}
          <div
            style={{
              position: 'absolute',
              left: edgeX - 2,
              top: 60,
              bottom: 60,
              width: 4,
              opacity: seamOpacity,
              background: `linear-gradient(180deg, transparent, ${COLORS.goldLight} 20%, ${COLORS.gold} 80%, transparent)`,
              boxShadow: `0 0 18px ${COLORS.gold}, 0 0 60px ${COLORS.gold}`,
            }}
          />
        </AbsoluteFill>
      </WhipZoom>

      <FlashBang at={lift} duration={22} />

      <Sequence from={24} durationInFrames={86}>
        <Caption text="No one has ever seen his face" he="אף אחד מעולם לא ראה את פניו" size={66} />
      </Sequence>
      <Sequence from={116} durationInFrames={60}>
        <Caption text="They call him the AI King" he="קוראים לו מלך ה-AI" tone="gold" size={70} position="lower" />
      </Sequence>
      <Sequence from={lift + 42} durationInFrames={72}>
        <Caption text="The man behind the machine" he="האיש שמאחורי המכונה" size={58} position="lower" />
      </Sequence>
      <Sequence from={L(CUES.revealNameIn)} durationInFrames={70}>
        <NameCard />
      </Sequence>
    </AbsoluteFill>
  );
};

const NameCard: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = lerp(frame, [50, 62], [1, 0]);
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 170, opacity}}>
      <GoldTitle text="אביב סנאנס" dir="rtl" metal="silver" fontFamily={FONTS.hebrew} fontSize={110} letterSpacing="0.02em" />
      <div style={{marginTop: 10, fontFamily: FONTS.title, fontWeight: 700, fontSize: 30, letterSpacing: `${lerp(frame, [0, 70], [0.5, 0.8])}em`, color: COLORS.gold, opacity: lerp(frame, [8, 20], [0, 1])}}>
        AVIV SANANES
      </div>
    </AbsoluteFill>
  );
};
