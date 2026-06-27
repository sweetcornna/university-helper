import React from 'react';
import { useCurrentFrame, useVideoConfig, Img, staticFile, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC } from '../fonts';
import { SceneWrap } from '../components/ui';
import { develop, lineReveal, reveal } from '../lib/anim';

/** Brand reveal — the hand-off. Scene owns the Chinese hero (subtitle shows EN only). */
export const Scene2Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();

  // light stream converging to center (the pile becoming an ordered queue)
  const stream = interpolate(frame, [0, 26], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const streamFade = interpolate(frame, [26, 46], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  const lock = reveal(frame, 30, 22);
  const tagReveal = lineReveal(frame, 40, 30);
  const dev = develop(frame, 40, 34);
  const glow = interpolate(frame, [40, 80], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  const HERO = ['你', '睡', '觉', '，', '它', '上', '课'];

  return (
    <SceneWrap pad={0} inF={10} outF={16}>
      {/* converging light stream */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: 0,
          width: '100%',
          height: 2,
          opacity: streamFade * 0.8,
          transform: `translateY(-50%) scaleX(${stream})`,
          background: `linear-gradient(90deg, transparent, ${COLORS.signal} 50%, transparent)`,
        }}
      />

      {/* soft dark knockout keeps the serif hero crisp over any sky behind it */}
      <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(40% 34% at 50% 52%, rgba(5,10,20,0.5) 0%, transparent 72%)', opacity: lock.opacity }} />

      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        {/* wordmark lockup */}
        <div style={{ opacity: lock.opacity, transform: `translateY(${lock.y}px)`, display: 'flex', alignItems: 'center', gap: 18, marginBottom: 40 }}>
          <Img src={staticFile('favicon.svg')} style={{ width: 46, height: 46, borderRadius: 11 }} />
          <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 30, letterSpacing: '0.01em', color: COLORS.paper }}>University&nbsp;Helper</span>
        </div>

        {/* hero tagline */}
        <div style={{ overflow: 'hidden', padding: '0 10px 18px' }}>
          <div
            style={{
              display: 'flex',
              gap: 6,
              transform: `translateY(${(1 - tagReveal) * 110}%)`,
              filter: `blur(${dev.blur}px)`,
            }}
          >
            {HERO.map((c, i) => (
              <span
                key={i}
                style={{
                  fontFamily: serifSC,
                  fontWeight: 900,
                  fontSize: 132,
                  lineHeight: 1.05,
                  color: COLORS.paper,
                  textShadow: `0 0 ${44 * glow}px rgba(91,157,255,${0.45 * glow})`,
                }}
              >
                {c}
              </span>
            ))}
          </div>
        </div>
      </div>
    </SceneWrap>
  );
};
