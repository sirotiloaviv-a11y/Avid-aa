import {loadFont as loadCinzel} from '@remotion/google-fonts/Cinzel';
import {loadFont as loadOrbitron} from '@remotion/google-fonts/Orbitron';
import {loadFont as loadHeebo} from '@remotion/google-fonts/Heebo';
import {loadFont as loadOswald} from '@remotion/google-fonts/Oswald';

// Remotion waits for these to load before rendering any frame.
const cinzel = loadCinzel('normal', {weights: ['700', '900'], subsets: ['latin']});
const orbitron = loadOrbitron('normal', {weights: ['500', '900'], subsets: ['latin']});
const heebo = loadHeebo('normal', {weights: ['400', '800', '900'], subsets: ['hebrew', 'latin']});
const oswald = loadOswald('normal', {weights: ['300', '600'], subsets: ['latin']});

export const FONTS = {
  /** Epic serif for trailer cards. */
  title: cinzel.fontFamily,
  /** Tech / HUD / terminal text. */
  tech: orbitron.fontFamily,
  /** Hebrew captions and title. */
  hebrew: heebo.fontFamily,
  /** Condensed credits billing block. */
  condensed: oswald.fontFamily,
};
