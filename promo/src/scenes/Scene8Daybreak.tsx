import React from 'react';
import { useCurrentFrame, useVideoConfig, AbsoluteFill, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC, monoFont } from '../fonts';
import { develop, lineReveal, pop, expoOut } from '../lib/anim';

// breakdown of the 6 courses' overnight work — closes the hook's "6 门课" loop
const STATS = [
  { zh: '签到', n: 6 },
  { zh: '视频', n: 12 },
  { zh: '章节测验', n: 9 },
  { zh: '见面课', n: 3 },
];

/** Daybreak payoff. Sky is already sunrise (continuous). Scene owns the hero 天亮了. */
export const Scene8Daybreak: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const heroReveal = lineReveal(frame, 14, 30);
  const dev = develop(frame, 14, 38);
  const ctxR = interpolate(frame, [44, 66], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const statsR = interpolate(frame, [58, 78], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  // slow push-in keeps the long climactic hold alive (depth, per the playbook)
  const pushIn = interpolate(frame, [0, 306], [1.0, 1.035], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      {/* soft dark halo guarantees the white hero reads on the bright dawn sky */}
      <AbsoluteFill style={{ background: 'radial-gradient(46% 42% at 50% 36%, rgba(5,10,20,0.6) 0%, rgba(5,10,20,0.22) 46%, transparent 72%)' }} />

      <div style={{ position: 'relative', textAlign: 'center', transform: `translateY(-72px) scale(${pushIn})` }}>
        <div style={{ overflow: 'hidden', padding: '0 12px 18px' }}>
          <div
            style={{
              fontFamily: serifSC,
              fontWeight: 900,
              fontSize: 168,
              lineHeight: 1.05,
              color: COLORS.paper,
              transform: `translateY(${(1 - heroReveal) * 110}%)`,
              filter: `blur(${dev.blur}px)`,
              textShadow: '0 0 56px rgba(255,238,200,0.45), 0 2px 26px rgba(5,10,20,0.8)',
            }}
          >
            天亮了。
          </div>
        </div>

        {/* close the narrative loop: the 6 courses queued tonight — all done */}
        <div style={{ opacity: ctxR, transform: `translateY(${(1 - ctxR) * 10}px)`, fontFamily: sansSC, fontWeight: 500, fontSize: 34, color: COLORS.paper, marginBottom: 30 }}>
          6 门课，<span style={{ color: COLORS.done }}>全部完成</span>。
        </div>

        {/* completed-tonight breakdown — numbers count up */}
        <div style={{ display: 'flex', gap: 44, justifyContent: 'center', opacity: statsR }}>
          {STATS.map((s, i) => {
            const at = 60 + i * 9;
            const p = pop(frame, at, fps);
            const val = Math.round(interpolate(frame, [at, at + 16], [0, s.n], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }));
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 12, transform: `scale(${interpolate(p, [0, 1], [0.92, 1])})` }}>
                <span style={{ color: COLORS.done, fontSize: 24 }}>✓</span>
                <span style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 27, color: COLORS.muted }}>{s.zh}</span>
                <span style={{ fontFamily: monoFont, fontWeight: 500, fontSize: 30, color: COLORS.paper, fontVariantNumeric: 'tabular-nums' }}>{val}</span>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
