import React from 'react';
import {AbsoluteFill, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Shot} from '../shots';

// One generated shot, conformed to its slot. Clips are generated at 9:16;
// objectFit cover only guards against an off-by-a-few-pixels export.
export const ShotClip: React.FC<{shot: Shot; available: boolean}> = ({shot, available}) => {
	const frame = useCurrentFrame();
	const opacity =
		shot.seamIn > 0 ? interpolate(frame, [0, shot.seamIn], [0, 1], {extrapolateRight: 'clamp'}) : 1;

	if (!available) {
		// Studio-only slate. `npm run render` refuses to start while any clip
		// is missing, so this never reaches an exported file.
		return (
			<AbsoluteFill
				style={{
					background: '#111',
					color: '#666',
					fontFamily: 'monospace',
					fontSize: 36,
					alignItems: 'center',
					justifyContent: 'center',
				}}
			>
				missing: public/clips/{shot.clip}
			</AbsoluteFill>
		);
	}

	return (
		<AbsoluteFill style={{opacity}}>
			<OffthreadVideo
				src={staticFile(`clips/${shot.clip}`)}
				startFrom={shot.trimStartFrames}
				playbackRate={shot.playbackRate}
				muted
				style={{width: '100%', height: '100%', objectFit: 'cover'}}
			/>
		</AbsoluteFill>
	);
};
