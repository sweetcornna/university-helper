import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { sansSC, monoFont } from '../fonts';
import { SceneWrap } from '../components/ui';
import { reveal, pop, expoOut } from '../lib/anim';
import { useVideoConfig } from 'remotion';

const Card: React.FC<{ start: number; label: string; en: string; children: React.ReactNode }> = ({ start, label, en, children }) => {
  const frame = useCurrentFrame();
  const r = reveal(frame, start, 20, 24);
  return (
    <div style={{ width: 430, opacity: r.opacity, transform: `translateY(${r.y}px)` }}>
      <div style={{ height: 300, position: 'relative', borderTop: `1px solid ${COLORS.line}`, paddingTop: 26, overflow: 'hidden' }}>{children}</div>
      <div style={{ marginTop: 22, display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 26, color: COLORS.paper }}>{label}</span>
        <span style={{ fontFamily: monoFont, fontSize: 13, letterSpacing: '0.22em', color: COLORS.muted, textTransform: 'uppercase' }}>{en}</span>
      </div>
    </div>
  );
};

const MapCard: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const drop = pop(frame, start + 16, fps);
  const ripple = interpolate(frame, [start + 24, start + 70], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'absolute', inset: 26, background: 'rgba(13,26,51,0.4)', borderRadius: 4, overflow: 'hidden' }}>
      {/* faint grid */}
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={'h' + i} style={{ position: 'absolute', left: 0, right: 0, top: `${(i + 1) * 14}%`, height: 1, background: 'rgba(143,163,192,0.10)' }} />
      ))}
      {Array.from({ length: 7 }).map((_, i) => (
        <div key={'v' + i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${(i + 1) * 12}%`, width: 1, background: 'rgba(143,163,192,0.10)' }} />
      ))}
      {/* a road */}
      <div style={{ position: 'absolute', left: '-10%', top: '60%', width: '120%', height: 6, background: 'rgba(91,157,255,0.18)', transform: 'rotate(-12deg)' }} />
      {/* ripple */}
      <div style={{ position: 'absolute', left: '50%', top: '46%', width: 18, height: 18, marginLeft: -9, marginTop: -9, borderRadius: '50%', border: `2px solid ${COLORS.signal}`, transform: `scale(${1 + ripple * 6})`, opacity: (1 - ripple) * 0.8 }} />
      {/* pin */}
      <div style={{ position: 'absolute', left: '50%', top: '46%', transform: `translate(-50%,${interpolate(drop, [0, 1], [-90, -34])}px) scale(${drop})` }}>
        <div style={{ width: 22, height: 22, borderRadius: '50% 50% 50% 0', background: COLORS.signal, transform: 'rotate(-45deg)', boxShadow: `0 0 16px ${COLORS.signal}` }} />
      </div>
    </div>
  );
};

const QrCard: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const N = 13;
  const scan = interpolate((frame - start - 14) % 60, [0, 60], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const show = frame > start + 10;
  return (
    <div style={{ position: 'absolute', inset: 26, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'relative', width: 200, height: 200, opacity: show ? 1 : 0 }}>
        <div style={{ position: 'absolute', inset: 0, display: 'grid', gridTemplateColumns: `repeat(${N}, 1fr)`, gridTemplateRows: `repeat(${N}, 1fr)`, gap: 2 }}>
          {Array.from({ length: N * N }).map((_, i) => {
            const r = Math.floor(i / N);
            const c = i % N;
            const finder = (r < 3 && c < 3) || (r < 3 && c >= N - 3) || (r >= N - 3 && c < 3);
            const h = Math.sin(r * 12.9898 + c * 78.233) * 43758.5453;
            const on = finder || h - Math.floor(h) > 0.55;
            return <div key={i} style={{ background: on ? COLORS.paper : 'transparent', borderRadius: 1, opacity: on ? 0.92 : 0 }} />;
          })}
        </div>
        {/* scan line */}
        <div style={{ position: 'absolute', left: -6, right: -6, top: `${scan * 100}%`, height: 3, background: COLORS.signal, boxShadow: `0 0 12px ${COLORS.signal}` }} />
      </div>
    </div>
  );
};

const SignAllCard: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rows = ['高等数学', '大学英语', '中国近代史', '线性代数'];
  return (
    <div style={{ position: 'absolute', inset: 26, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 14 }}>
      {rows.map((row, i) => {
        const checkAt = start + 22 + i * 12;
        const p = pop(frame, checkAt, fps);
        const done = frame > checkAt + 2;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 24, height: 24, borderRadius: 5, border: `1.5px solid ${done ? COLORS.done : 'rgba(143,163,192,0.4)'}`, background: done ? 'rgba(61,220,151,0.14)' : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ color: COLORS.done, fontSize: 16, transform: `scale(${p})`, lineHeight: 1 }}>✓</span>
            </div>
            <span style={{ fontFamily: sansSC, fontSize: 22, color: done ? COLORS.paper : COLORS.muted }}>{row}</span>
            <span style={{ marginLeft: 'auto', fontFamily: monoFont, fontSize: 13, color: done ? COLORS.done : COLORS.faint, letterSpacing: '0.1em' }}>{done ? '已签到' : '…'}</span>
          </div>
        );
      })}
    </div>
  );
};

export const Scene4Signin: React.FC = () => {
  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 70 }}>
        <Card start={10} label="位置签到" en="Location">
          <MapCard start={10} />
        </Card>
        <Card start={30} label="二维码" en="QR Code">
          <QrCard start={30} />
        </Card>
        <Card start={50} label="一键签全部" en="Sign-all">
          <SignAllCard start={50} />
        </Card>
      </div>
    </SceneWrap>
  );
};
