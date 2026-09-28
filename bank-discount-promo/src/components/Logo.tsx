import React from 'react';
import {Img, staticFile} from 'remotion';
import {COLORS} from '../theme';

type Props = {
	// Height of the lockup in px; everything scales from it.
	size: number;
	logoSrc?: string | null;
	color?: string;
	inverted?: boolean;
};

/**
 * Logo container. Drop the official Bank Discount logo into /public and pass
 * its file name as `logoSrc`; until then a neutral placeholder lockup
 * (abstract mark + "דיסקונט" wordmark) is drawn in its place.
 */
export const Logo: React.FC<Props> = ({size, logoSrc, color = COLORS.green, inverted = false}) => {
	if (logoSrc) {
		return <Img src={staticFile(logoSrc)} style={{height: size, width: 'auto'}} />;
	}

	const markFill = inverted ? COLORS.white : color;
	const markInner = inverted ? color : COLORS.white;
	const textColor = inverted ? COLORS.white : COLORS.ink;

	return (
		<div
			style={{
				display: 'flex',
				flexDirection: 'row',
				alignItems: 'center',
				gap: size * 0.28,
				direction: 'rtl',
			}}
		>
			<svg width={size} height={size} viewBox="0 0 100 100">
				<rect x="0" y="0" width="100" height="100" rx="26" fill={markFill} />
				<path
					d="M30 26 H52 C69 26 78 37 78 50 C78 63 69 74 52 74 H30 Z"
					fill="none"
					stroke={markInner}
					strokeWidth="11"
					strokeLinejoin="round"
				/>
				<circle cx="52" cy="50" r="7" fill={markInner} />
			</svg>
			<span
				style={{
					fontSize: size * 0.82,
					fontWeight: 900,
					color: textColor,
					letterSpacing: -size * 0.01,
					lineHeight: 1,
				}}
			>
				דיסקונט
			</span>
		</div>
	);
};
