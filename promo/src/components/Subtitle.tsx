import React from 'react';
import { AbsoluteFill, useCurrentFrame, interpolate } from 'remotion';
import { BEATS } from '../script';
import { COLORS } from '../tokens';
import { sansSC, monoFont } from '../fonts';
import { expoOut, lineReveal } from '../lib/anim';

/**
 * Bilingual lower-third subtitle track. One source of truth (script BEATS).
 * sub: 'full' = zh+en, 'enOnly' = en only (scene owns the hero zh), 'none' = hidden.
 */
export const Subtitle: React.FC = () => {
  const frame = useCurrentFrame();

  // pick the latest beat whose window contains this frame (clean forward handoff)
  let active = -1;
  for (let i = 0; i < BEATS.length; i++) {
    const b = BEATS[i];
    if (frame >= b.from && frame < b.from + b.duration) active = i;
  }
  if (active < 0) return null;
  const b = BEATS[active];
  if (b.sub === 'none') return null;

  const local = frame - b.from;
  const reveal = lineReveal(local, 6, 22);
  const out = interpolate(local, [b.duration - 14, b.duration], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = Math.min(reveal === 0 ? 0 : 1, out) * interpolate(local, [6, 18], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const enRise = interpolate(local, [12, 30], [10, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });

  const showZh = b.sub !== 'enOnly';

  return (
    <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', pointerEvents: 'none' }}>
      <div style={{ marginBottom: 96, textAlign: 'center', opacity }}>
        {showZh && (
          <div style={{ overflow: 'hidden', paddingBottom: 6 }}>
            <div
              style={{
                fontFamily: sansSC,
                fontWeight: 500,
                fontSize: 44,
                letterSpacing: '0.02em',
                color: COLORS.paper,
                transform: `translateY(${(1 - reveal) * 100}%)`,
                textShadow: '0 2px 30px rgba(5,10,20,0.7)',
              }}
            >
              {b.zh}
            </div>
          </div>
        )}
        <div
          style={{
            fontFamily: monoFont,
            fontWeight: 400,
            fontSize: showZh ? 19 : 26,
            letterSpacing: '0.16em',
            color: showZh ? COLORS.muted : COLORS.paper,
            textTransform: 'uppercase',
            transform: `translateY(${enRise}px)`,
            marginTop: showZh ? 4 : 0,
            textShadow: '0 2px 20px rgba(5,10,20,0.7)',
          }}
        >
          {b.en}
        </div>
      </div>
    </AbsoluteFill>
  );
};
