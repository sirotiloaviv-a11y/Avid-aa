import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Logo} from '../components/Logo';
import {RevealText} from '../components/RevealText';
import {PromoProps} from '../copy';
import {COLORS} from '../theme';

const UNDERLINE_WIDTH = 560;

// 00:16 - 00:20 — Logo lockup, tagline and legal fine print.
export const Scene4Outro: React.FC<PromoProps> = ({tagline, finePrint, logoSrc}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const focus = spring({frame: frame - 4, fps, config: {damping: 20, stiffness: 70}});
	const scale = interpolate(focus, [0, 1], [1.35, 1]);
	const blur = interpolate(focus, [0, 1], [24, 0]);

	const line = interpolate(frame, [24, 50], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.bezier(0.16, 1, 0.3, 1),
	});

	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(circle at 50% 44%, rgba(0,150,57,0.08) 0%, rgba(0,150,57,0) 55%), ${COLORS.white}`,
				alignItems: 'center',
				justifyContent: 'center',
			}}
		>
			<div
				style={{
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					marginTop: -120,
				}}
			>
				<div style={{opacity: focus, transform: `scale(${scale})`, filter: `blur(${blur}px)`}}>
					<Logo size={150} logoSrc={logoSrc} />
				</div>
				<div
					style={{
						marginTop: 56,
						width: UNDERLINE_WIDTH * line,
						height: 14,
						borderRadius: 7,
						background: COLORS.green,
					}}
				/>
				<RevealText delay={42} style={{marginTop: 70}}>
					<div style={{fontSize: 82, fontWeight: 800}}>{tagline}</div>
				</RevealText>
			</div>

			<RevealText
				delay={56}
				distance={20}
				style={{position: 'absolute', bottom: 110, left: 0, right: 0, textAlign: 'center'}}
			>
				<div style={{fontSize: 32, fontWeight: 500, color: COLORS.muted}}>{finePrint}</div>
			</RevealText>
		</AbsoluteFill>
	);
};
