import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {TRANSITION_FRAMES, TransitionType} from '../timing';

type Props = {
	enter: TransitionType | null;
	// The transition type of the *next* scene, which decides how this one leaves.
	exit: TransitionType | null;
	exitAt: number;
	children: React.ReactNode;
};

const progress = (frame: number, start: number) =>
	interpolate(frame, [start, start + TRANSITION_FRAMES], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.bezier(0.65, 0, 0.35, 1),
	});

export const SceneTransition: React.FC<Props> = ({enter, exit, exitAt, children}) => {
	const frame = useCurrentFrame();
	const {width} = useVideoConfig();

	const pIn = enter ? progress(frame, 0) : 1;
	const pOut = exit ? progress(frame, exitAt) : 0;

	let opacity = 1;
	let translateX = 0;
	let scale = 1;

	// RTL reading direction: new content pushes in from the left.
	if (enter === 'fade') opacity *= pIn;
	if (enter === 'slide') translateX -= (1 - pIn) * width;
	if (enter === 'zoom') {
		opacity *= pIn;
		scale *= interpolate(pIn, [0, 1], [1.12, 1]);
	}

	if (exit === 'slide') translateX += pOut * width * 0.35;
	if (exit === 'zoom') scale *= interpolate(pOut, [0, 1], [1, 0.96]);

	return (
		<AbsoluteFill
			style={{
				opacity,
				transform: `translateX(${translateX}px) scale(${scale})`,
				overflow: 'hidden',
			}}
		>
			{children}
		</AbsoluteFill>
	);
};
