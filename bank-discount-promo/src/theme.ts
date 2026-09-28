import {loadFont} from '@remotion/google-fonts/Heebo';

// Heebo: modern Israeli sans-serif with full Hebrew support.
export const {fontFamily: FONT_FAMILY} = loadFont('normal', {
	weights: ['400', '500', '700', '800', '900'],
	subsets: ['hebrew', 'latin'],
});

export const COLORS = {
	green: '#009639',
	greenAlt: '#008738',
	greenDark: '#006827',
	ink: '#1A1A1A',
	white: '#FFFFFF',
	gray: '#F4F6F5',
	muted: '#5F6B66',
	line: '#E3E8E5',
} as const;

export const SHADOW = {
	soft: '0 24px 60px rgba(26, 26, 26, 0.10)',
	glow: '0 0 140px rgba(0, 150, 57, 0.35)',
} as const;
