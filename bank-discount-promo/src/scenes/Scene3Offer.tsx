import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {CtaButton} from '../components/CtaButton';
import {Logo} from '../components/Logo';
import {RevealText} from '../components/RevealText';
import {PromoProps} from '../copy';
import {COLORS} from '../theme';

const DigitalCard: React.FC<{logoSrc: string | null}> = ({logoSrc}) => (
	<div
		style={{
			width: 760,
			height: 470,
			borderRadius: 44,
			padding: 52,
			boxSizing: 'border-box',
			position: 'relative',
			overflow: 'hidden',
			background: 'linear-gradient(135deg, #1F2A25 0%, #0E1411 100%)',
			boxShadow: '0 50px 90px rgba(0,0,0,0.35)',
			color: COLORS.white,
			display: 'flex',
			flexDirection: 'column',
			justifyContent: 'space-between',
		}}
	>
		<div
			style={{
				position: 'absolute',
				width: 560,
				height: 560,
				borderRadius: '50%',
				left: -220,
				bottom: -330,
				background: `radial-gradient(circle, ${COLORS.green} 0%, rgba(0,150,57,0) 70%)`,
				opacity: 0.8,
			}}
		/>
		<Logo size={64} logoSrc={logoSrc} inverted />
		<div
			style={{
				width: 96,
				height: 72,
				borderRadius: 14,
				background: 'linear-gradient(135deg, #E8D9A8 0%, #B79E5C 100%)',
			}}
		/>
		<div
			style={{
				direction: 'ltr',
				textAlign: 'left',
				fontSize: 40,
				letterSpacing: 6,
				fontWeight: 500,
				opacity: 0.9,
			}}
		>
			•••• •••• •••• 2026
		</div>
	</div>
);

// 00:10 - 00:16 — Offer + call to action on a green gradient.
export const Scene3Offer: React.FC<PromoProps> = ({offerLines, ctaLabel, logoSrc}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const cardIn = spring({frame: frame - 6, fps, config: {damping: 15, stiffness: 80}});
	const rotateY = interpolate(cardIn, [0, 1], [-55, -12]) + Math.sin(frame / 30) * 4;
	const rotateX = interpolate(cardIn, [0, 1], [25, 8]);
	const drift = interpolate(frame, [0, 180], [0, -40]);

	return (
		<AbsoluteFill
			style={{
				background: `linear-gradient(160deg, ${COLORS.green} 0%, ${COLORS.greenDark} 100%)`,
				color: COLORS.white,
			}}
		>
			{/* Soft light shapes */}
			<div
				style={{
					position: 'absolute',
					width: 1100,
					height: 1100,
					borderRadius: '50%',
					top: -420,
					right: -520,
					background: 'radial-gradient(circle, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0) 65%)',
					transform: `translateY(${-drift}px)`,
				}}
			/>
			<div
				style={{
					position: 'absolute',
					width: 900,
					height: 900,
					borderRadius: '50%',
					bottom: -380,
					left: -380,
					border: '2px solid rgba(255,255,255,0.14)',
					transform: `translateY(${drift}px)`,
				}}
			/>

			<AbsoluteFill style={{alignItems: 'center', paddingTop: 300, perspective: 1600}}>
				<div
					style={{
						opacity: cardIn,
						transform: `translateY(${(1 - cardIn) * -200}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`,
					}}
				>
					<DigitalCard logoSrc={logoSrc} />
				</div>
			</AbsoluteFill>

			<AbsoluteFill style={{alignItems: 'center', paddingTop: 960, textAlign: 'center'}}>
				{offerLines.map((line, i) => (
					<RevealText key={line} delay={18 + i * 9}>
						<div
							style={{
								fontSize: i === offerLines.length - 1 ? 116 : 88,
								fontWeight: i === offerLines.length - 1 ? 900 : 700,
								lineHeight: 1.22,
							}}
						>
							{line}
						</div>
					</RevealText>
				))}
				<div style={{marginTop: 130}}>
					<CtaButton label={ctaLabel} delay={52} />
				</div>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};
