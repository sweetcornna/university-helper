import React from 'react';
import { AbsoluteFill, Audio, staticFile } from 'remotion';
import { Sky } from './components/Sky';
import { Atmosphere } from './components/Atmosphere';
import { Hud } from './components/Hud';
import { Subtitle } from './components/Subtitle';
import { SceneStack } from './SceneStack';

export const Promo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: '#050A14' }}>
      {/* continuous planes — never inside a Sequence (absolute frame) */}
      <Sky />
      <Atmosphere />
      {/* scene content */}
      <SceneStack />
      {/* persistent overlays */}
      <Hud />
      <Subtitle />
      {/* root-level audio — spans all frames; fades baked into the file */}
      <Audio src={staticFile('music.mp3')} volume={0.85} />
    </AbsoluteFill>
  );
};
