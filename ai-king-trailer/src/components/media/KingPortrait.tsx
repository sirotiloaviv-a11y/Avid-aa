import React from 'react';
import {AbsoluteFill, Img} from 'remotion';
import {IMAGES, PORTRAIT_FRAMING} from '../../config/assets';

export type PortraitKind = 'kingMask' | 'kingFace';

type Props = {
  kind: PortraitKind;
  /** Where the eye line sits in the frame (px). */
  eyeY?: number;
  /** Horizontal centre of the face (px). */
  centerX?: number;
  /** On-screen eye→chin distance (px) — both portraits share it so they line up. */
  faceSize?: number;
  /** Fade the photo's own background into the scene. */
  feather?: boolean;
  style?: React.CSSProperties;
};

/**
 * Places a portrait so its eye line and face scale land on the same screen
 * coordinates regardless of the source photo — this is what lets the mask
 * lift off and reveal a face that sits exactly underneath it.
 */
export const KingPortrait: React.FC<Props> = ({kind, eyeY = 560, centerX = 960, faceSize = 330, feather = true, style}) => {
  const f = PORTRAIT_FRAMING[kind];
  const height = faceSize / f.eyeToChin;
  const width = (height * f.naturalWidth) / f.naturalHeight;
  const left = centerX - f.x * width;
  const top = eyeY - f.y * height;

  // Ellipse around head + shoulders, in % of the image box.
  const cx = f.x * 100;
  const cy = (f.y + f.eyeToChin * 0.35) * 100;
  const featherMask = `radial-gradient(ellipse ${kind === 'kingFace' ? '48% 40%' : '44% 54%'} at ${cx}% ${cy}%, #000 62%, transparent 100%)`;

  return (
    <AbsoluteFill style={style}>
      <div
        style={{
          position: 'absolute',
          left,
          top,
          width,
          height,
          WebkitMaskImage: feather ? featherMask : undefined,
          maskImage: feather ? featherMask : undefined,
        }}
      >
        <Img
          src={IMAGES[kind]}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            filter: kind === 'kingFace' ? 'contrast(1.12) saturate(1.05) brightness(0.95)' : 'contrast(1.1) brightness(1.02)',
          }}
        />
        {kind === 'kingFace' && (
          // Pushes the bright room behind the photo into the midnight-blue set.
          <div
            style={{
              position: 'absolute',
              inset: 0,
              mixBlendMode: 'multiply',
              background: `radial-gradient(ellipse 34% 26% at ${cx}% ${cy - 4}%, rgba(255,255,255,1) 55%, rgba(12,22,60,0.95) 100%)`,
            }}
          />
        )}
        {/* golden rim light */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            mixBlendMode: 'soft-light',
            background: 'linear-gradient(90deg, rgba(255,200,110,0.55) 0%, transparent 35%, transparent 65%, rgba(90,130,255,0.45) 100%)',
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
