import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';

type Props = {
	children: React.ReactNode;
	delay?: number;
	duration?: number;
	distance?: number;
	style?: React.CSSProperties;
};

// Fade-in + slide-up, the base text animation used across all scenes.
export const RevealText: React.FC<Props> = ({
	children,
	delay = 0,
	duration = 18,
	distance = 60,
	style,
}) => {
	const frame = useCurrentFrame();
	const p = interpolate(frame, [delay, delay + duration], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.bezier(0.16, 1, 0.3, 1),
	});

	return (
		<div
			style={{
				opacity: p,
				transform: `translateY(${(1 - p) * distance}px)`,
				filter: `blur(${(1 - p) * 8}px)`,
				...style,
			}}
		>
			{children}
		</div>
	);
};
