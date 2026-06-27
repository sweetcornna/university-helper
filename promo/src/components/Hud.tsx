import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { nightState } from '../lib/night';
import { COLORS } from '../tokens';
import { sansSC, monoFont } from '../fonts';
import { expoOut } from '../lib/anim';

/**
 * Whisper-quiet product chrome: brand bug (top-left), the continuous "one night"
 * clock + phase (top-right), and a 1px night-progress line at the very bottom.
 * Fades away for the dawn payoff so the final shots read as pure film.
 */
export const Hud: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / durationInFrames;
  const n = nightState(p);

  const inOpacity = interpolate(frame, [10, 40], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const outOpacity = interpolate(frame, [1430, 1520], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const opacity = Math.min(inOpacity, outOpacity);
  const ink = n.lit ? COLORS.dayInk : COLORS.muted;

  return (
    <AbsoluteFill style={{ pointerEvents: 'none', opacity }}>
      {/* brand bug */}
      <div style={{ position: 'absolute', top: 46, left: 56, display: 'flex', alignItems: 'center', gap: 14 }}>
        <Img src={staticFile('favicon.svg')} style={{ width: 30, height: 30, borderRadius: 7 }} />
        <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 19, letterSpacing: '0.01em', color: n.lit ? COLORS.dayInk : COLORS.paper }}>
          University&nbsp;Helper
        </span>
      </div>

      {/* continuous clock + phase */}
      <div style={{ position: 'absolute', top: 44, right: 56, textAlign: 'right' }}>
        <div style={{ fontFamily: monoFont, fontWeight: 500, fontSize: 30, letterSpacing: '0.04em', color: ink, fontVariantNumeric: 'tabular-nums' }}>
          {n.clock}
        </div>
        <div style={{ fontFamily: monoFont, fontWeight: 400, fontSize: 13, letterSpacing: '0.34em', color: n.lit ? COLORS.dayMuted : COLORS.lamp, marginTop: 3 }}>
          {n.phase}
        </div>
      </div>

      {/* night-progress line */}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 2, background: 'rgba(143,163,192,0.14)' }}>
        <div
          style={{
            height: '100%',
            width: '100%',
            transform: `scaleX(${p})`,
            transformOrigin: 'left',
            background: 'linear-gradient(90deg, #5B9DFF, #FFB454)',
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
