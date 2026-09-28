import React from 'react';
import {Audio, Sequence, interpolate, staticFile, useVideoConfig} from 'remotion';
import {FPS, MUSIC, SFX} from '../shots';

export const Soundtrack: React.FC<{has: (file: string) => boolean}> = ({has}) => {
	const {durationInFrames} = useVideoConfig();

	return (
		<>
			{has(MUSIC.file) ? (
				<Audio
					src={staticFile(MUSIC.file)}
					volume={(f) =>
						MUSIC.volume *
						interpolate(
							f,
							[0, MUSIC.fadeInSec * FPS, durationInFrames - MUSIC.fadeOutSec * FPS, durationInFrames],
							[0, 1, 1, 0],
							{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
						)
					}
				/>
			) : null}
			{SFX.filter((cue) => has(cue.file)).map((cue) => (
				<Sequence key={cue.file} from={Math.round(cue.atSec * FPS)} layout="none">
					<Audio src={staticFile(cue.file)} volume={cue.volume} />
				</Sequence>
			))}
		</>
	);
};
