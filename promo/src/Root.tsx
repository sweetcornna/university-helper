import React from 'react';
import { Composition } from 'remotion';
import './fonts'; // trigger font loading early
import { Promo } from './Promo';
import { PromoVertical } from './portrait/PromoVertical';
import { Cover } from './Cover';
import { VIDEO } from './tokens';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="UniversityHelperPromo"
        component={Promo}
        durationInFrames={VIDEO.durationInFrames}
        fps={VIDEO.fps}
        width={VIDEO.width}
        height={VIDEO.height}
      />
      <Composition
        id="UniversityHelperPromoVertical"
        component={PromoVertical}
        durationInFrames={VIDEO.durationInFrames}
        fps={VIDEO.fps}
        width={1080}
        height={1920}
      />
      <Composition id="BilibiliCover" component={Cover} durationInFrames={1} fps={30} width={1600} height={900} defaultProps={{ bg: 'cover-bg-flat.png' }} />
      <Composition id="BilibiliCover43" component={Cover} durationInFrames={1} fps={30} width={1600} height={1200} defaultProps={{ bg: 'cover-bg-flat-43.png' }} />
    </>
  );
};
