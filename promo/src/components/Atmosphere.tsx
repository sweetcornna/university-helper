import React from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { ramp } from '../lib/night';

/**
 * Cinematic depth plane: vignette, top/bottom scrims, and the warm dawn bloom
 * (the single reserved light-leak that marks the tonal lift). Sits above the Sky,
 * below the scene content. Driven by absolute frame — keep outside any Sequence.
 */
export const Atmosphere: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / durationInFrames;

  const hudScrim = 0.82 * (1 - ramp(p, 0.66, 0.92));
  const dawnBloom = ramp(p, 0.74, 0.96);
  // a brief warm light-leak sweep right at the dawn turn (~48–52s)
  const leak = interpolate(frame, [1410, 1470, 1560], [0, 0.5, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      {/* vignette */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(120% 90% at 50% 42%, transparent 52%, rgba(2,4,10,0.55) 100%)',
          opacity: 1 - dawnBloom * 0.6,
        }}
      />
      {/* top scrim for clock/phase legibility */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(180deg, rgba(5,10,20,${hudScrim}) 0%, rgba(5,10,20,0) 22%)`,
        }}
      />
      {/* bottom scrim for subtitle legibility */}
      <AbsoluteFill
        style={{
          background: 'linear-gradient(0deg, rgba(5,10,20,0.55) 0%, rgba(5,10,20,0) 26%)',
          opacity: 1 - dawnBloom * 0.5,
        }}
      />
      {/* warm dawn bloom rising from the horizon */}
      <AbsoluteFill
        style={{
          opacity: dawnBloom,
          background:
            'radial-gradient(140% 70% at 50% 118%, rgba(255,213,142,0.55) 0%, rgba(255,180,110,0.18) 40%, transparent 70%)',
          mixBlendMode: 'screen',
        }}
      />
      {/* reserved light-leak sweep at the dawn turn */}
      <AbsoluteFill
        style={{
          opacity: leak,
          background:
            'linear-gradient(105deg, transparent 30%, rgba(255,224,170,0.6) 50%, transparent 70%)',
          mixBlendMode: 'screen',
        }}
      />
    </AbsoluteFill>
  );
};
