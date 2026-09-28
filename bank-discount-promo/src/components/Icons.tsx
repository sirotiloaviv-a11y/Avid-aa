import React from 'react';

type IconProps = {size: number; color: string; strokeWidth?: number};

const Svg: React.FC<IconProps & {children: React.ReactNode}> = ({
	size,
	color,
	strokeWidth = 2,
	children,
}) => (
	<svg
		width={size}
		height={size}
		viewBox="0 0 24 24"
		fill="none"
		stroke={color}
		strokeWidth={strokeWidth}
		strokeLinecap="round"
		strokeLinejoin="round"
	>
		{children}
	</svg>
);

export const GrowthIcon: React.FC<IconProps> = (p) => (
	<Svg {...p}>
		<polyline points="3 17 9 11 13 15 21 7" />
		<polyline points="15 7 21 7 21 13" />
	</Svg>
);

export const WalletIcon: React.FC<IconProps> = (p) => (
	<Svg {...p}>
		<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v2" />
		<rect x="3" y="7" width="18" height="14" rx="2" />
		<path d="M21 12h-4a2 2 0 0 0 0 4h4" />
	</Svg>
);

export const TransferIcon: React.FC<IconProps> = (p) => (
	<Svg {...p}>
		<path d="M4 8h15l-4-4" />
		<path d="M20 16H5l4 4" />
	</Svg>
);

export const SavingsIcon: React.FC<IconProps> = (p) => (
	<Svg {...p}>
		<circle cx="12" cy="12" r="9" />
		<path d="M12 7v10M9 10h4.5a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3H15" />
	</Svg>
);

export const ArrowLeftIcon: React.FC<IconProps> = (p) => (
	<Svg {...p}>
		<path d="M19 12H5" />
		<path d="M11 6l-6 6 6 6" />
	</Svg>
);
