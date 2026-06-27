import React from 'react';
import { AbsoluteFill, Img, staticFile } from 'remotion';
import { COLORS } from './tokens';
import { serifSC, sansSC, monoFont } from './fonts';

/** Bilibili cover. gpt-image-2 flat-design key art + crisp on-brand typography.
 *  Shared by the 16:9 and 4:3 compositions (bg passed via defaultProps) so the
 *  title treatment is identical across both ratios. */
export const Cover: React.FC<{ bg?: string }> = ({ bg = 'cover-bg-flat.png' }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: '#050A14' }}>
      <Img src={staticFile(bg)} style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'center' }} />

      {/* very light scrims — the flat art's left/upper area is already clean navy */}
      <AbsoluteFill style={{ background: 'linear-gradient(90deg, rgba(5,10,20,0.55) 0%, rgba(5,10,20,0.18) 40%, rgba(5,10,20,0) 64%)' }} />
      <AbsoluteFill style={{ background: 'linear-gradient(180deg, rgba(5,10,20,0.45) 0%, rgba(5,10,20,0) 16%)' }} />

      {/* wordmark lockup */}
      <div style={{ position: 'absolute', top: 56, left: 80, display: 'flex', alignItems: 'center', gap: 16 }}>
        <Img src={staticFile('favicon.svg')} style={{ width: 44, height: 44, borderRadius: 10 }} />
        <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 32, color: COLORS.paper, letterSpacing: '0.01em' }}>University&nbsp;Helper</span>
      </div>

      {/* hero title — the curiosity hook */}
      <div style={{ position: 'absolute', left: 80, top: 244 }}>
        <div style={{ fontFamily: monoFont, fontWeight: 500, fontSize: 25, letterSpacing: '0.3em', color: COLORS.signal, textTransform: 'uppercase', marginBottom: 26, textShadow: '0 2px 16px rgba(5,10,20,0.8)' }}>
          超星 · 智慧树 一站搞定
        </div>
        <div style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 134, lineHeight: 1.06, color: COLORS.paper, textShadow: '0 0 50px rgba(91,157,255,0.45), 0 6px 36px rgba(5,10,20,0.85)' }}>
          聚合刷课平台？
          <br />
          还<span style={{ color: COLORS.lamp }}>免费开源</span>？
        </div>
        <div style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 37, color: COLORS.paper, marginTop: 34, letterSpacing: '0.01em', textShadow: '0 2px 16px rgba(5,10,20,0.9)' }}>
          自托管 · 夜里自动签到 · 刷课 · 答题 · <span style={{ color: COLORS.done }}>MIT</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
