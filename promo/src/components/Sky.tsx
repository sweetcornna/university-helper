import React, { useMemo } from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { nightState, makeStars, ramp } from '../lib/night';

/**
 * Continuous night→dawn background. MUST be a direct child of the root AbsoluteFill
 * (never inside a <Sequence>) so useCurrentFrame() stays the absolute composition frame.
 */
export const Sky: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps, width, height } = useVideoConfig();
  const p = frame / durationInFrames;
  const n = nightState(p, width, height);
  const starCount = width < height ? 150 : 130;
  const stars = useMemo(() => makeStars(starCount, fps, width, height), [starCount, fps, width, height]);

  // very slow vertical drift gives the static gradient subtle life (parallax plane)
  const drift = interpolate(frame, [0, durationInFrames], [0, -42]);

  // moon is an opening-night element; it "clouds over" before the night shift so
  // it never collides with the platform/sign-in/engine content that fills the frame.
  const moonMask = interpolate(frame, [196, 252], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const moonOpacity = n.moon.opacity * moonMask;

  return (
    <AbsoluteFill style={{ backgroundColor: '#050A14', overflow: 'hidden' }}>
      {/* sky-night base */}
      <AbsoluteFill
        style={{
          opacity: n.skyNight,
          transform: `translateY(${drift * 0.3}px)`,
          background:
            'radial-gradient(120% 80% at 80% -10%, #0B1B36 0%, transparent 55%),' +
            'radial-gradient(90% 60% at 10% 110%, #081226 0%, transparent 60%),' +
            '#050A14',
        }}
      />
      {/* Milky Way band */}
      <AbsoluteFill
        style={{
          opacity: n.skyNight * 0.9,
          background:
            'linear-gradient(112deg, transparent 38%, rgba(150,180,230,0.030) 46%, rgba(214,226,248,0.075) 50%, rgba(150,180,230,0.030) 54%, transparent 62%)',
        }}
      />
      {/* pre-dawn */}
      <AbsoluteFill
        style={{
          opacity: n.skyPreDawn,
          background: 'linear-gradient(180deg, #0A1730 0%, #11244A 55%, #1B3261 100%)',
        }}
      />
      {/* dawn */}
      <AbsoluteFill
        style={{
          opacity: n.skyDawn,
          background:
            'linear-gradient(180deg, #27396B 0%, #4A4576 30%, #7A5170 55%, #C76B5B 78%, #F2A65A 92%, #FFD58E 100%)',
        }}
      />

      {/* stars */}
      <AbsoluteFill style={{ opacity: n.stars }}>
        {stars.map((s, i) => {
          const ph = ((frame - s.delayF) / s.durF) * Math.PI * 2;
          const tw = 0.14 + (s.peak - 0.14) * (0.5 - 0.5 * Math.cos(ph));
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: s.left,
                top: s.top,
                width: s.size,
                height: s.size,
                borderRadius: '50%',
                background: '#CFE0F5',
                opacity: tw,
              }}
            />
          );
        })}
      </AbsoluteFill>

      {/* meteors */}
      <Meteor start={70} seed={3} />
      <Meteor start={330} seed={11} />
      <Meteor start={612} seed={23} />

      {/* moon */}
      {moonOpacity > 0.01 && (
        <div
          style={{
            position: 'absolute',
            left: n.moon.x,
            top: n.moon.y,
            width: 120,
            height: 120,
            transform: `translate(-50%,-50%) scale(${n.moon.scale})`,
            borderRadius: '50%',
            opacity: moonOpacity,
            background:
              'radial-gradient(circle at 63% 58%, rgba(112,122,142,0.38) 0 7%, transparent 8%),' +
              'radial-gradient(circle at 41% 70%, rgba(112,122,142,0.30) 0 5%, transparent 6%),' +
              'radial-gradient(circle at 53% 33%, rgba(112,122,142,0.32) 0 4%, transparent 5%),' +
              'radial-gradient(circle at 30% 48%, rgba(112,122,142,0.22) 0 3.4%, transparent 4.4%),' +
              'radial-gradient(circle at 36% 35%, #FBF8EE 0%, #E7E2D4 55%, #C3C0B5 100%)',
            boxShadow:
              '0 0 46px 14px rgba(235,230,215,0.22), 0 0 170px 64px rgba(190,200,226,0.10)',
          }}
        />
      )}

      {/* sun */}
      {n.sun.opacity > 0.01 && (
        <div
          style={{
            position: 'absolute',
            left: n.sun.x,
            top: n.sun.y,
            width: 152,
            height: 152,
            transform: `translate(-50%,-50%) scale(${n.sun.scale})`,
            borderRadius: '50%',
            opacity: n.sun.opacity,
            background:
              'radial-gradient(circle at 50% 42%, #FFF9E8 0%, #FFE3A1 45%, #FFB35C 78%, #F88E54 100%)',
            boxShadow:
              '0 0 70px 26px rgba(255,205,120,0.50), 0 0 240px 110px rgba(255,160,110,0.28)',
          }}
        />
      )}
    </AbsoluteFill>
  );
};

const Meteor: React.FC<{ start: number; seed: number }> = ({ start, seed }) => {
  const frame = useCurrentFrame();
  const dur = 33; // ~1.1s
  const local = frame - start;
  if (local < 0 || local > dur) return null;
  const t = local / dur;
  const top = (Math.abs(Math.sin(seed * 12.9898)) * 26 + 6) / 100;
  const left = (Math.abs(Math.sin(seed * 78.233)) * 50 + 35) / 100;
  const x = interpolate(t, [0, 1], [0, -160]);
  const y = interpolate(t, [0, 1], [0, 100]);
  const opacity = t < 0.7 ? interpolate(t, [0, 0.15], [0, 0.9], { extrapolateRight: 'clamp' }) : (1 - t) / 0.3 * 0.9;
  return (
    <div
      style={{
        position: 'absolute',
        top: `${top * 100}%`,
        left: `${left * 100}%`,
        width: 150,
        height: 1,
        opacity,
        transform: `translate(${x}px, ${y}px) rotate(-32deg)`,
        background: 'linear-gradient(90deg, rgba(207,224,245,0) 0%, rgba(207,224,245,0.9) 100%)',
      }}
    />
  );
};
