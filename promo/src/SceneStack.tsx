import React from 'react';
import { Sequence } from 'remotion';
import { BEATS } from './script';
import { Scene1Hook } from './scenes/Scene1Hook';
import { Scene2Reveal } from './scenes/Scene2Reveal';
import { Scene3Access } from './scenes/Scene3Access';
import { Scene4Signin } from './scenes/Scene4Signin';
import { Scene5Nightshift } from './scenes/Scene5Nightshift';
import { Scene6Isolation } from './scenes/Scene6Isolation';
import { Scene7Deploy } from './scenes/Scene7Deploy';
import { Scene8Daybreak } from './scenes/Scene8Daybreak';
import { Scene9Endcard } from './scenes/Scene9Endcard';

const COMPONENTS: Record<string, React.FC> = {
  hook: Scene1Hook,
  reveal: Scene2Reveal,
  access: Scene3Access,
  signin: Scene4Signin,
  nightshift: Scene5Nightshift,
  isolation: Scene6Isolation,
  deploy: Scene7Deploy,
  daybreak: Scene8Daybreak,
  endcard: Scene9Endcard,
};

export const SceneStack: React.FC = () => {
  return (
    <>
      {BEATS.map((b) => {
        const C = COMPONENTS[b.id];
        if (!C) return null;
        return (
          <Sequence key={b.id} from={b.from} durationInFrames={b.duration} name={b.id} layout="none">
            <C />
          </Sequence>
        );
      })}
    </>
  );
};
