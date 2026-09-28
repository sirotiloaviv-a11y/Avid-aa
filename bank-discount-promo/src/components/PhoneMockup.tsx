import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS, SHADOW} from '../theme';
import {GrowthIcon, SavingsIcon, TransferIcon, WalletIcon} from './Icons';

const PHONE_W = 600;
const PHONE_H = 1220;

const CHART_PATH = 'M0 150 C60 140 90 110 140 118 C190 126 210 70 270 78 C330 86 350 40 420 30';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

const formatShekel = (n: number) => `₪${Math.round(n).toLocaleString('en-US')}`;

const Card: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({
	children,
	style,
}) => (
	<div
		style={{
			background: COLORS.white,
			borderRadius: 32,
			padding: 28,
			boxShadow: '0 8px 24px rgba(26,26,26,0.06)',
			...style,
		}}
	>
		{children}
	</div>
);

// A stylised banking-app screen inside a phone frame. `start` is the frame
// (scene-local) at which the screen content begins animating.
export const PhoneMockup: React.FC<{start: number}> = ({start}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const t = frame - start;

	const balance = interpolate(t, [0, 50], [0, 24580], {
		...clamp,
		easing: Easing.out(Easing.cubic),
	});
	const chart = interpolate(t, [10, 60], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});

	const actions = [
		{Icon: TransferIcon, label: 'העברה'},
		{Icon: WalletIcon, label: 'תשלום'},
		{Icon: SavingsIcon, label: 'חיסכון'},
	];

	const rows = [
		{title: 'משכורת', amount: '+₪14,200', positive: true},
		{title: 'העברה ב-Bit', amount: '-₪250', positive: false},
		{title: 'פיקדון חודשי', amount: '+₪1,000', positive: true},
	];

	return (
		<div
			style={{
				width: PHONE_W,
				height: PHONE_H,
				borderRadius: 96,
				background: '#111413',
				padding: 18,
				boxShadow: `${SHADOW.glow}, 0 40px 80px rgba(0,0,0,0.25)`,
				position: 'relative',
			}}
		>
			<div
				style={{
					width: '100%',
					height: '100%',
					borderRadius: 80,
					background: COLORS.gray,
					overflow: 'hidden',
					position: 'relative',
					padding: '90px 34px 34px',
					boxSizing: 'border-box',
					display: 'flex',
					flexDirection: 'column',
					gap: 24,
				}}
			>
				{/* Dynamic island */}
				<div
					style={{
						position: 'absolute',
						top: 26,
						left: '50%',
						width: 170,
						height: 46,
						marginLeft: -85,
						borderRadius: 23,
						background: '#111413',
					}}
				/>

				<div style={{fontSize: 34, fontWeight: 800}}>שלום, ברוכים הבאים</div>

				{/* Balance card */}
				<div
					style={{
						borderRadius: 36,
						padding: 32,
						color: COLORS.white,
						background: `linear-gradient(135deg, ${COLORS.green} 0%, ${COLORS.greenDark} 100%)`,
						boxShadow: '0 16px 32px rgba(0,104,39,0.35)',
					}}
				>
					<div style={{fontSize: 26, fontWeight: 500, opacity: 0.85}}>יתרה בעו״ש</div>
					<div
						style={{
							fontSize: 72,
							fontWeight: 900,
							marginTop: 6,
							direction: 'ltr',
							textAlign: 'right',
						}}
					>
						{formatShekel(balance)}
					</div>
					<div style={{fontSize: 24, fontWeight: 500, marginTop: 8, opacity: 0.9}}>
						<span style={{direction: 'ltr', display: 'inline-block'}}>+8.4%</span> החודש
					</div>
				</div>

				{/* Quick actions */}
				<div style={{display: 'flex', justifyContent: 'space-between'}}>
					{actions.map(({Icon, label}, i) => {
						const pop = spring({frame: t - 20 - i * 5, fps, config: {damping: 11, stiffness: 160}});
						return (
							<div
								key={label}
								style={{
									display: 'flex',
									flexDirection: 'column',
									alignItems: 'center',
									gap: 10,
									transform: `scale(${pop})`,
								}}
							>
								<div
									style={{
										width: 118,
										height: 118,
										borderRadius: 36,
										background: COLORS.white,
										display: 'flex',
										alignItems: 'center',
										justifyContent: 'center',
										boxShadow: '0 6px 18px rgba(26,26,26,0.06)',
									}}
								>
									<Icon size={54} color={COLORS.green} strokeWidth={2.2} />
								</div>
								<div style={{fontSize: 24, fontWeight: 700}}>{label}</div>
							</div>
						);
					})}
				</div>

				{/* Growth chart */}
				<Card>
					<div style={{display: 'flex', alignItems: 'center', gap: 12, fontSize: 28, fontWeight: 800}}>
						<GrowthIcon size={34} color={COLORS.green} strokeWidth={2.6} />
						תיק החיסכון שלך
					</div>
					<svg width="100%" height="170" viewBox="0 0 420 170" style={{marginTop: 14}}>
						<defs>
							<linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
								<stop offset="0%" stopColor={COLORS.green} stopOpacity="0.28" />
								<stop offset="100%" stopColor={COLORS.green} stopOpacity="0" />
							</linearGradient>
						</defs>
						<path d={`${CHART_PATH} L420 170 L0 170 Z`} fill="url(#chartFill)" opacity={chart} />
						<path
							d={CHART_PATH}
							fill="none"
							stroke={COLORS.green}
							strokeWidth="6"
							strokeLinecap="round"
							pathLength={1}
							strokeDasharray="1"
							strokeDashoffset={1 - chart}
						/>
						<circle cx="420" cy="30" r={10 * chart} fill={COLORS.green} />
					</svg>
				</Card>

				{/* Recent activity */}
				<Card style={{display: 'flex', flexDirection: 'column', gap: 20, padding: '24px 28px'}}>
					{rows.map((row, i) => {
						const p = interpolate(t, [30 + i * 6, 45 + i * 6], [0, 1], clamp);
						return (
							<div
								key={row.title}
								style={{
									display: 'flex',
									justifyContent: 'space-between',
									fontSize: 26,
									opacity: p,
									transform: `translateX(${(1 - p) * -30}px)`,
								}}
							>
								<span style={{fontWeight: 700}}>{row.title}</span>
								<span
									style={{
										direction: 'ltr',
										fontWeight: 800,
										color: row.positive ? COLORS.green : COLORS.ink,
									}}
								>
									{row.amount}
								</span>
							</div>
						);
					})}
				</Card>
			</div>
		</div>
	);
};
