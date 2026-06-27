import React from 'react';
import { AbsoluteFill, Audio, staticFile } from 'remotion';
import { Sky } from '../components/Sky';
import { Atmosphere } from '../components/Atmosphere';
import { Hud } from '../components/Hud';
import { SceneStackV } from './SceneStackV';
import { SubtitleV } from './SubtitleV';

/** 9:16 portrait, Chinese-only build. Reuses the aspect-aware Sky/Atmosphere/Hud
 *  and the shared beat timeline + music; only the scene layouts + captions differ. */
export const PromoVertical: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: '#050A14' }}>
      <Sky />
      <Atmosphere />
      <SceneStackV />
      <Hud />
      <SubtitleV />
      <Audio src={staticFile('music.mp3')} volume={0.85} />
    </AbsoluteFill>
  );
};
