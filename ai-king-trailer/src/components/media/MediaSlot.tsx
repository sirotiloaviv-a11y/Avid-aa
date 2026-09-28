import React from 'react';
import {AbsoluteFill, OffthreadVideo} from 'remotion';
import {SHOW_PLACEHOLDER_TAGS} from '../../config/constants';
import {FONTS} from '../../config/fonts';
import {VIDEOS, type VideoSlot} from '../../config/assets';

type Props = {
  slot: VideoSlot;
  /** Procedural stand-in rendered while the slot has no footage. */
  fallback: React.ReactNode;
  /** Frames to skip into the clip (e.g. to pick the best part of a generation). */
  trimBefore?: number;
  playbackRate?: number;
  style?: React.CSSProperties;
};

/**
 * A footage slot. Renders the AI-generated clip from `config/assets.ts`
 * when present, otherwise the procedural fallback + a small slot tag.
 */
export const MediaSlot: React.FC<Props> = ({slot, fallback, trimBefore = 0, playbackRate = 1, style}) => {
  const src = VIDEOS[slot];
  if (src) {
    return (
      <AbsoluteFill style={style}>
        <OffthreadVideo
          src={src}
          muted
          startFrom={trimBefore}
          playbackRate={playbackRate}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={style}>
      {fallback}
      {SHOW_PLACEHOLDER_TAGS && (
        <div
          style={{
            position: 'absolute',
            right: 36,
            top: 150,
            padding: '6px 12px',
            border: '1px solid rgba(232,195,106,0.7)',
            color: 'rgba(232,195,106,0.9)',
            fontFamily: FONTS.tech,
            fontSize: 16,
            letterSpacing: '0.2em',
            background: 'rgba(0,0,0,0.45)',
          }}
        >
          PLACEHOLDER · {slot}
        </div>
      )}
    </AbsoluteFill>
  );
};
