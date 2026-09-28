// Parametric timeline. Change a scene's seconds and every start frame,
// the total duration and the composition length follow.
export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

// Length of the overlap between two consecutive scenes.
export const TRANSITION_FRAMES = 15;

export type TransitionType = 'fade' | 'slide' | 'zoom';

type SceneSpec = {
	id: 'hook' | 'app' | 'offer' | 'outro';
	seconds: number;
	// How this scene enters over the previous one.
	enter: TransitionType;
};

const SPECS: SceneSpec[] = [
	{id: 'hook', seconds: 4, enter: 'fade'}, // 00:00 - 00:04
	{id: 'app', seconds: 6, enter: 'slide'}, // 00:04 - 00:10
	{id: 'offer', seconds: 6, enter: 'zoom'}, // 00:10 - 00:16
	{id: 'outro', seconds: 4, enter: 'fade'}, // 00:16 - 00:20
];

export type Scene = SceneSpec & {from: number; duration: number};

export const SCENES: Scene[] = SPECS.reduce<Scene[]>((acc, spec) => {
	const prev = acc[acc.length - 1];
	const from = prev ? prev.from + prev.duration : 0;
	return [...acc, {...spec, from, duration: Math.round(spec.seconds * FPS)}];
}, []);

export const TOTAL_FRAMES = SCENES.reduce((sum, s) => sum + s.duration, 0); // 600

export const sec = (seconds: number) => Math.round(seconds * FPS);
