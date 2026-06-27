import React from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, monoFont } from '../fonts';
import { envelope } from '../lib/anim';

/** Wraps a scene with the shared in/out envelope (fade + tiny rise). */
export const SceneWrap: React.FC<{
  children: React.ReactNode;
  inF?: number;
  outF?: number;
  rise?: number;
  pad?: number | string;
  style?: React.CSSProperties;
}> = ({ children, inF = 16, outF = 14, rise = 14, pad = 132, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const env = envelope(frame, durationInFrames, inF, outF);
  const y = (1 - env) * rise;
  return (
    <AbsoluteFill style={{ opacity: env, transform: `translateY(${y}px)`, padding: pad, ...style }}>
      {children}
    </AbsoluteFill>
  );
};

/** Horizontal fill bar (scaleX from left). */
export const ProgressBar: React.FC<{
  progress: number; // 0..1
  width?: number | string;
  color?: string;
  track?: string;
  height?: number;
}> = ({ progress, width = 360, color = COLORS.signal, track = 'rgba(143,163,192,0.18)', height = 5 }) => (
  <div style={{ width, height, borderRadius: 3, background: track, overflow: 'hidden' }}>
    <div
      style={{
        width: '100%',
        height: '100%',
        borderRadius: 3,
        background: color,
        transform: `scaleX(${Math.max(0, Math.min(1, progress))})`,
        transformOrigin: 'left',
      }}
    />
  </div>
);

/** Giant faint watermark glyph (星 / 树). */
export const Glyph: React.FC<{ char: string; opacity?: number; size?: number; style?: React.CSSProperties }> = ({
  char,
  opacity = 0.05,
  size = 460,
  style,
}) => (
  <div
    style={{
      fontFamily: serifSC,
      fontWeight: 900,
      fontSize: size,
      lineHeight: 1,
      color: COLORS.paper,
      opacity,
      userSelect: 'none',
      ...style,
    }}
  >
    {char}
  </div>
);

/** Amber mono eyebrow / section label. */
export const MonoEyebrow: React.FC<{ children: React.ReactNode; color?: string; style?: React.CSSProperties }> = ({
  children,
  color = COLORS.lamp,
  style,
}) => (
  <span
    style={{
      fontFamily: monoFont,
      fontWeight: 500,
      fontSize: 17,
      letterSpacing: '0.28em',
      textTransform: 'uppercase',
      color,
      ...style,
    }}
  >
    {children}
  </span>
);
