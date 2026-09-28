import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS} from '../theme';
import {ArrowLeftIcon} from './Icons';

const SHINE_EVERY = 45; // frames between shine sweeps

// White pill CTA with a spring entrance, a gentle pulse and a periodic shine.
export const CtaButton: React.FC<{label: string; delay: number}> = ({label, delay}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const t = frame - delay;

	const enter = spring({frame: t, fps, config: {damping: 12, stiffness: 140}});
	const pulse = t > 15 ? 1 + 0.035 * Math.sin(((t - 15) / fps) * Math.PI * 2 * 1.1) : 1;
	const shineT = t < 20 ? -1 : ((t - 20) % SHINE_EVERY) / 22;
	const shineX = interpolate(shineT, [0, 1], [-140, 140], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	// Expanding halo ring that echoes the pulse.
	const ring = t > 15 ? ((t - 15) % 40) / 40 : 0;

	return (
		<div style={{position: 'relative', transform: `scale(${enter * pulse})`}}>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					borderRadius: 999,
					border: `4px solid ${COLORS.white}`,
					opacity: t > 15 ? 0.6 * (1 - ring) : 0,
					transform: `scale(${1 + ring * 0.18}, ${1 + ring * 0.45})`,
				}}
			/>
			<div
				style={{
					position: 'relative',
					overflow: 'hidden',
					display: 'flex',
					alignItems: 'center',
					gap: 24,
					padding: '40px 76px',
					borderRadius: 999,
					background: COLORS.white,
					color: COLORS.greenDark,
					fontSize: 60,
					fontWeight: 800,
					boxShadow: '0 24px 60px rgba(0,0,0,0.25)',
				}}
			>
				{label}
				<ArrowLeftIcon size={60} color={COLORS.green} strokeWidth={2.8} />
				<div
					style={{
						position: 'absolute',
						top: 0,
						bottom: 0,
						left: `${50 + shineX}%`,
						width: 120,
						marginLeft: -60,
						transform: 'skewX(-20deg)',
						background:
							'linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(0,150,57,0.18) 50%, rgba(255,255,255,0) 100%)',
					}}
				/>
			</div>
		</div>
	);
};
