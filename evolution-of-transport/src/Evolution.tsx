import React from 'react';
import {AbsoluteFill, Sequence, getStaticFiles} from 'remotion';
import {ShotClip} from './components/ShotClip';
import {Soundtrack} from './components/Soundtrack';
import {TIMELINE} from './shots';

export const Evolution: React.FC = () => {
	const files = new Set(getStaticFiles().map((f) => f.name));
	const has = (file: string) => files.has(file);

	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			{/* Later shots sit on top; with a seam they start a few frames early and blend in. */}
			{TIMELINE.map((shot) => (
				<Sequence key={shot.id} name={shot.id} from={shot.from} durationInFrames={shot.duration}>
					<ShotClip shot={shot} available={has(`clips/${shot.clip}`)} />
				</Sequence>
			))}
			<Soundtrack has={has} />
		</AbsoluteFill>
	);
};
