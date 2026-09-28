import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import {SceneTransition} from './components/SceneTransition';
import {PromoProps} from './copy';
import {Scene1Hook} from './scenes/Scene1Hook';
import {Scene2App} from './scenes/Scene2App';
import {Scene3Offer} from './scenes/Scene3Offer';
import {Scene4Outro} from './scenes/Scene4Outro';
import {COLORS, FONT_FAMILY} from './theme';
import {SCENES, TRANSITION_FRAMES} from './timing';

const SCENE_COMPONENTS: Record<string, React.FC<PromoProps>> = {
	hook: Scene1Hook,
	app: Scene2App,
	offer: Scene3Offer,
	outro: Scene4Outro,
};

export const DiscountPromo: React.FC<PromoProps> = (props) => {
	return (
		<AbsoluteFill
			lang="he"
			style={{
				backgroundColor: COLORS.white,
				direction: 'rtl',
				fontFamily: FONT_FAMILY,
				color: COLORS.ink,
			}}
		>
			{SCENES.map((scene, i) => {
				const next = SCENES[i + 1];
				const Component = SCENE_COMPONENTS[scene.id];
				// Each scene keeps rendering under the next one while it transitions in.
				const tail = next ? TRANSITION_FRAMES : 0;
				return (
					<Sequence
						key={scene.id}
						name={scene.id}
						from={scene.from}
						durationInFrames={scene.duration + tail}
					>
						<SceneTransition
							enter={i === 0 ? null : scene.enter}
							exit={next ? next.enter : null}
							exitAt={scene.duration}
						>
							<Component {...props} />
						</SceneTransition>
					</Sequence>
				);
			})}
		</AbsoluteFill>
	);
};
