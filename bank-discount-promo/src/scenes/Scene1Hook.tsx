import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Logo} from '../components/Logo';
import {RevealText} from '../components/RevealText';
import {PromoProps} from '../copy';
import {COLORS} from '../theme';

const wavePath = (width: number, height: number, amp: number, phase: number, freq: number) => {
	const points: string[] = [];
	for (let x = 0; x <= width; x += 20) {
		const y = amp * Math.sin((x / width) * Math.PI * 2 * freq + phase);
		points.push(`${x},${y.toFixed(1)}`);
	}
	return `M0,${height} L${points.join(' L')} L${width},${height} Z`;
};

// 00:00 - 00:04 — Opening hook on white with a rising green wave.
export const Scene1Hook: React.FC<PromoProps> = ({hookTitle, hookSubtitle, hookHighlight, logoSrc}) => {
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();

	const rise = interpolate(frame, [0, 45], [1, 0], {
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});
	const waveTop = height * 0.7 + rise * height * 0.35;
	const phase = frame / 14;

	const shapeIn = spring({frame: frame - 6, fps, config: {damping: 14}});
	const spin = frame * 0.35;

	return (
		<AbsoluteFill style={{backgroundColor: COLORS.white}}>
			{/* Geometric accents */}
			<div
				style={{
					position: 'absolute',
					top: 170,
					left: -140,
					width: 520,
					height: 520,
					borderRadius: '50%',
					border: `36px solid ${COLORS.green}`,
					opacity: 0.1 * shapeIn,
					transform: `scale(${shapeIn})`,
				}}
			/>
			<div
				style={{
					position: 'absolute',
					top: 190,
					right: 110,
					width: 130,
					height: 130,
					borderRadius: 36,
					background: COLORS.green,
					opacity: 0.9 * shapeIn,
					transform: `scale(${shapeIn}) rotate(${20 + spin}deg)`,
				}}
			/>
			<div
				style={{
					position: 'absolute',
					top: 330,
					right: 290,
					width: 60,
					height: 60,
					borderRadius: '50%',
					background: COLORS.greenDark,
					opacity: shapeIn,
					transform: `scale(${shapeIn})`,
				}}
			/>

			{/* Layered green waves */}
			<svg
				width={width}
				height={height}
				style={{position: 'absolute', top: waveTop, left: 0}}
				viewBox={`0 -80 ${width} ${height}`}
			>
				<path d={wavePath(width, height, 50, phase + 1.4, 1.2)} fill={COLORS.green} opacity={0.25} />
				<path d={wavePath(width, height, 38, phase * 1.3, 0.9)} fill={COLORS.green} transform="translate(0,50)" />
				<path
					d={wavePath(width, height, 28, -phase, 1.5)}
					fill={COLORS.greenDark}
					transform="translate(0,150)"
				/>
			</svg>

			{/* Copy */}
			<AbsoluteFill style={{padding: '0 96px', justifyContent: 'flex-start', paddingTop: 480}}>
				<RevealText delay={4} distance={30}>
					<Logo size={84} logoSrc={logoSrc} />
				</RevealText>
				<RevealText delay={14} style={{marginTop: 90}}>
					<div style={{fontSize: 140, fontWeight: 900, lineHeight: 1.05, letterSpacing: -2}}>
						{hookTitle}
					</div>
				</RevealText>
				<RevealText delay={30} style={{marginTop: 50}}>
					<div style={{fontSize: 84, fontWeight: 500, lineHeight: 1.2}}>{hookSubtitle}</div>
				</RevealText>
				<RevealText delay={40}>
					<div style={{fontSize: 84, fontWeight: 900, lineHeight: 1.2, color: COLORS.green}}>
						{hookHighlight}
					</div>
				</RevealText>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};
