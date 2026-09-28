// All on-screen copy lives here and is exposed as editable composition props
// in Remotion Studio.
export type PromoProps = {
	hookTitle: string;
	hookSubtitle: string;
	hookHighlight: string;
	appTitle: string[];
	appFeatures: [string, string, string];
	offerLines: string[];
	ctaLabel: string;
	tagline: string;
	finePrint: string;
	// Path inside /public to the official logo file (e.g. "discount-logo.svg").
	// When null, the built-in placeholder lockup is rendered.
	logoSrc: string | null;
};

export const DEFAULT_PROPS: PromoProps = {
	hookTitle: 'חושבים על העתיד?',
	hookSubtitle: 'הגיע הזמן להתקדם',
	hookHighlight: 'בדיסקונט',
	appTitle: ['ניהול פיננסי חכם,', 'בלחיצת כפתור'],
	appFeatures: ['צמיחה', 'ארנק דיגיטלי', 'העברות מהירות'],
	offerLines: ['פותחים חשבון בדיגיטל', 'ומקבלים תנאים', 'שמגיעים רק לך'],
	ctaLabel: 'להצטרפות בקלות',
	tagline: 'דיסקונט. רואים אותך',
	finePrint: 'בכפוף לתנאי הבנק | כפוף לאישור',
	logoSrc: null,
};
