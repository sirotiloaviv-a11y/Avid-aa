import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {GrowthIcon, TransferIcon, WalletIcon} from '../components/Icons';
import {PhoneMockup} from '../components/PhoneMockup';
import {RevealText} from '../components/RevealText';
import {PromoProps} from '../copy';
import {COLORS, SHADOW} from '../theme';

const BADGES = [
	{Icon: GrowthIcon, top: 820, side: 'left', offset: 40, delay: 40},
	{Icon: WalletIcon, top: 1110, side: 'right', offset: 40, delay: 50},
	{Icon: TransferIcon, top: 1420, side: 'left', offset: 70, delay: 60},
] as const;

// 00:04 - 00:10 — App mockup with feature icons springing in.
export const Scene2App: React.FC<PromoProps> = ({appTitle, appFeatures}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const phoneIn = spring({frame: frame - 8, fps, config: {damping: 16, stiffness: 90}});
	const phoneY = interpolate(phoneIn, [0, 1], [700, 0]);
	const float = Math.sin(frame / 22) * 10;

	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(circle at 50% 62%, rgba(0,150,57,0.22) 0%, rgba(0,150,57,0) 45%), ${COLORS.gray}`,
			}}
		>
			<AbsoluteFill style={{alignItems: 'center', paddingTop: 170, textAlign: 'center'}}>
				{appTitle.map((line, i) => (
					<RevealText key={line} delay={10 + i * 8}>
						<div
							style={{
								fontSize: 104,
								fontWeight: 900,
								lineHeight: 1.12,
								color: i === appTitle.length - 1 ? COLORS.green : COLORS.ink,
							}}
						>
							{line}
						</div>
					</RevealText>
				))}
			</AbsoluteFill>

			<AbsoluteFill style={{alignItems: 'center', paddingTop: 520}}>
				<div style={{transform: `translateY(${phoneY + float}px) scale(0.92)`, transformOrigin: 'top center'}}>
					<PhoneMockup start={24} />
				</div>
			</AbsoluteFill>

			{BADGES.map(({Icon, top, side, offset, delay}, i) => {
				const pop = spring({frame: frame - delay, fps, config: {damping: 8, stiffness: 150, mass: 0.8}});
				const bob = Math.sin((frame + i * 20) / 18) * 12;
				return (
					<div
						key={appFeatures[i]}
						style={{
							position: 'absolute',
							top: top + bob,
							left: side === 'left' ? offset : undefined,
							right: side === 'right' ? offset : undefined,
							display: 'flex',
							flexDirection: 'column',
							alignItems: 'center',
							gap: 14,
							transform: `scale(${pop})`,
						}}
					>
						<div
							style={{
								width: 176,
								height: 176,
								borderRadius: '50%',
								background: COLORS.white,
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								boxShadow: `${SHADOW.soft}, 0 0 0 10px rgba(0,150,57,0.12)`,
							}}
						>
							<Icon size={88} color={COLORS.green} strokeWidth={2.3} />
						</div>
						<div
							style={{
								fontSize: 36,
								fontWeight: 800,
								background: COLORS.ink,
								color: COLORS.white,
								padding: '8px 22px',
								borderRadius: 999,
							}}
						>
							{appFeatures[i]}
						</div>
					</div>
				);
			})}
		</AbsoluteFill>
	);
};
