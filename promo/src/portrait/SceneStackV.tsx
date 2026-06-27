import React from 'react';
import { Sequence } from 'remotion';
import { BEATS } from '../script';
import { HookV, RevealV, AccessV, SigninV, NightshiftV, IsolationV, DeployV, DaybreakV, EndcardV } from './scenesV';

const COMPONENTS: Record<string, React.FC> = {
  hook: HookV,
  reveal: RevealV,
  access: AccessV,
  signin: SigninV,
  nightshift: NightshiftV,
  isolation: IsolationV,
  deploy: DeployV,
  daybreak: DaybreakV,
  endcard: EndcardV,
};

export const SceneStackV: React.FC = () => (
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
