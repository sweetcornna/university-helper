import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC, monoFont } from '../fonts';
import { SceneWrap, Glyph, MonoEyebrow } from '../components/ui';
import { reveal, expoOut } from '../lib/anim';

const FEATURES = {
  left: ['位置 / 二维码签到', '泛雅刷课', '章节测验自动答'],
  right: ['QR / 密码登录', '多课时视频', '见面课 · 自动答题'],
};

const Pulse: React.FC<{ dir: 1 | -1; start: number }> = ({ dir, start }) => {
  const frame = useCurrentFrame();
  const period = 34;
  const t = ((frame - start) % period) / period;
  if (frame < start) return null;
  const x = dir * t * 430;
  const op = Math.sin(t * Math.PI);
  return (
    <div
      style={{
        position: 'absolute',
        left: '50%',
        top: '50%',
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: COLORS.signal,
        boxShadow: `0 0 14px ${COLORS.signal}`,
        transform: `translate(calc(-50% + ${x}px), -50%)`,
        opacity: op * 0.9,
      }}
    />
  );
};

const Platform: React.FC<{ glyph: string; name: string; en: string; feats: string[]; start: number; align: 'left' | 'right' }> = ({
  glyph,
  name,
  en,
  feats,
  start,
  align,
}) => {
  const frame = useCurrentFrame();
  const r = reveal(frame, start, 22);
  const gOp = interpolate(frame, [start, start + 12], [0, 0.045], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'relative', width: 560, textAlign: align === 'left' ? 'left' : 'right' }}>
      <Glyph char={glyph} opacity={gOp} size={300} style={{ position: 'absolute', top: -188, [align]: -48, pointerEvents: 'none' } as React.CSSProperties} />
      <div style={{ opacity: r.opacity, transform: `translateY(${r.y}px)`, position: 'relative' }}>
        <MonoEyebrow color={COLORS.muted} style={{ fontSize: 14 }}>{en}</MonoEyebrow>
        <div style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 58, color: COLORS.paper, margin: '10px 0 22px' }}>{name}</div>
        {feats.map((f, i) => {
          const fr = reveal(frame, start + 14 + i * 7, 16, 14);
          return (
            <div
              key={i}
              style={{
                opacity: fr.opacity,
                transform: `translateY(${fr.y}px)`,
                fontFamily: sansSC,
                fontSize: 23,
                color: COLORS.muted,
                padding: '7px 0',
                display: 'flex',
                gap: 14,
                flexDirection: align === 'right' ? 'row-reverse' : 'row',
              }}
            >
              <span style={{ color: COLORS.signal }}>—</span>
              <span>{f}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const Scene3Access: React.FC = () => {
  const frame = useCurrentFrame();
  const railH = interpolate(frame, [8, 40], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const chip = reveal(frame, 18, 18);

  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 120 }}>
        <Platform glyph="星" name="超星学习通" en="Chaoxing" feats={FEATURES.left} start={10} align="left" />
        <Platform glyph="树" name="智慧树" en="Zhihuishu" feats={FEATURES.right} start={20} align="right" />
      </div>

      {/* center spine + login chip + pulses */}
      <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', height: 320, width: 1 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 1, background: 'rgba(143,163,192,0.3)', transform: `scaleY(${railH})`, transformOrigin: 'center' }} />
      </div>
      <Pulse dir={-1} start={42} />
      <Pulse dir={1} start={42} />
      <Pulse dir={-1} start={59} />
      <Pulse dir={1} start={59} />
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          transform: `translate(-50%,-50%) scale(${chip.opacity})`,
          opacity: chip.opacity,
          padding: '12px 22px',
          border: `1px solid rgba(255,180,84,0.4)`,
          borderRadius: 6,
          background: 'rgba(13,26,51,0.7)',
          fontFamily: monoFont,
          fontSize: 18,
          letterSpacing: '0.18em',
          color: COLORS.lamp,
          whiteSpace: 'nowrap',
        }}
      >
        一次登录
      </div>
    </SceneWrap>
  );
};
