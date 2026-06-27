import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC, monoFont } from '../fonts';
import { develop, reveal } from '../lib/anim';
import { ENDCARD } from '../script';

export const Scene9Endcard: React.FC = () => {
  const frame = useCurrentFrame();
  const dev = develop(frame, 4, 24);
  const meta = reveal(frame, 16, 20);

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <AbsoluteFill style={{ background: 'radial-gradient(50% 46% at 50% 48%, rgba(5,10,20,0.5) 0%, transparent 72%)' }} />
      {/* bottom scrim so the meta + credit stay legible over the bright dawn band */}
      <AbsoluteFill style={{ background: 'linear-gradient(0deg, rgba(5,10,20,0.74) 0%, rgba(5,10,20,0.4) 9%, rgba(5,10,20,0) 26%)' }} />

      <div style={{ position: 'relative', textAlign: 'center', opacity: dev.opacity, transform: `scale(${dev.scale})` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 20, marginBottom: 26 }}>
          <Img src={staticFile('favicon.svg')} style={{ width: 64, height: 64, borderRadius: 15 }} />
          <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 48, color: COLORS.paper }}>University&nbsp;Helper</span>
        </div>
        <div style={{ fontFamily: serifSC, fontWeight: 700, fontSize: 40, color: COLORS.paper, letterSpacing: '0.06em', textShadow: '0 0 50px rgba(255,213,142,0.35)' }}>
          {ENDCARD.tagline}
        </div>

        <div style={{ opacity: meta.opacity, transform: `translateY(${meta.y}px)`, marginTop: 40 }}>
          <div style={{ fontFamily: monoFont, fontSize: 15, letterSpacing: '0.28em', color: COLORS.lamp, textTransform: 'uppercase', marginBottom: 18 }}>
            开源 · 自托管
          </div>
          <div style={{ display: 'flex', gap: 24, justifyContent: 'center', fontFamily: monoFont, fontSize: 19, color: COLORS.paper, letterSpacing: '0.04em' }}>
            <span>{ENDCARD.url}</span>
            <span style={{ opacity: 0.5 }}>·</span>
            <span>{ENDCARD.repo}</span>
            <span style={{ opacity: 0.5 }}>·</span>
            <span style={{ color: COLORS.signal }}>{ENDCARD.license}</span>
          </div>
        </div>
      </div>

      {/* music attribution (CC-BY 4.0 requires credit) */}
      <div style={{ position: 'absolute', bottom: 30, width: '100%', textAlign: 'center', opacity: meta.opacity, fontFamily: monoFont, fontSize: 15, letterSpacing: '0.05em', color: '#FFFFFF' }}>
        Music: “Hymn to the Dawn” by Scott Buckley — CC BY 4.0 · scottbuckley.com.au
      </div>
    </AbsoluteFill>
  );
};
