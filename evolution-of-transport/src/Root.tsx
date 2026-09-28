import React from 'react';
import {Composition} from 'remotion';
import {Evolution} from './Evolution';
import {FPS, HEIGHT, TOTAL_FRAMES, WIDTH} from './shots';

export const RemotionRoot: React.FC = () => (
	<Composition
		id="Evolution"
		component={Evolution}
		durationInFrames={TOTAL_FRAMES}
		fps={FPS}
		width={WIDTH}
		height={HEIGHT}
	/>
);
