import React from 'react';
import { AbsoluteFill, useCurrentFrame, interpolate } from 'remotion';
import { BEATS } from '../script';
import { COLORS } from '../tokens';
import { sansSC } from '../fonts';
import { expoOut, lineReveal } from '../lib/anim';

/** Portrait, Chinese-only caption track. Beats whose scene owns the hero
 *  (sub: 'enOnly') or have no caption (sub: 'none') render nothing. */
export const SubtitleV: React.FC = () => {
  const frame = useCurrentFrame();

  let active = -1;
  for (let i = 0; i < BEATS.length; i++) {
    const b = BEATS[i];
    if (frame >= b.from && frame < b.from + b.duration) active = i;
  }
  if (active < 0) return null;
  const b = BEATS[active];
  if (b.sub === 'none' || b.sub === 'enOnly') return null;

  const local = frame - b.from;
  const reveal = lineReveal(local, 6, 22);
  const out = interpolate(local, [b.duration - 14, b.duration], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const fade = interpolate(local, [6, 18], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const opacity = Math.min(1, out) * fade;

  return (
    <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', pointerEvents: 'none' }}>
      <div style={{ marginBottom: 360, padding: '0 70px', textAlign: 'center', opacity }}>
        <div style={{ overflow: 'hidden', paddingBottom: 6 }}>
          <div
            style={{
              fontFamily: sansSC,
              fontWeight: 500,
              fontSize: 52,
              letterSpacing: '0.02em',
              lineHeight: 1.3,
              color: COLORS.paper,
              transform: `translateY(${(1 - reveal) * 100}%)`,
              textShadow: '0 2px 30px rgba(5,10,20,0.8)',
            }}
          >
            {b.zh}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
