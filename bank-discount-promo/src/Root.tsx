import React from 'react';
import {Composition} from 'remotion';
import {DEFAULT_PROPS} from './copy';
import {DiscountPromo} from './DiscountPromo';
import {FPS, HEIGHT, TOTAL_FRAMES, WIDTH} from './timing';

export const RemotionRoot: React.FC = () => {
	return (
		<Composition
			id="DiscountPromo"
			component={DiscountPromo}
			durationInFrames={TOTAL_FRAMES}
			fps={FPS}
			width={WIDTH}
			height={HEIGHT}
			defaultProps={DEFAULT_PROPS}
		/>
	);
};
