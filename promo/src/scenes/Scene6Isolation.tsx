import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC, monoFont } from '../fonts';
import { SceneWrap, MonoEyebrow } from '../components/ui';
import { reveal } from '../lib/anim';

// 5×5 window grid. 'late' = amber, extinguishes one-by-one; 'you' = blue, stays breathing.
const YOU = 12; // center
const LATE = [3, 16, 21]; // a few neighbours still lit — they extinguish, yours stays

const Dorm: React.FC = () => {
  const frame = useCurrentFrame();
  const youGlow = 0.32 + 0.28 * (0.5 - 0.5 * Math.cos(frame * 0.09));
  return (
    <div style={{ width: 360, padding: 30, paddingTop: 40, background: '#02060D', borderRadius: 6, position: 'relative', boxShadow: 'inset 0 1px 0 rgba(143,163,192,0.14)' }}>
      {/* water tank */}
      <div style={{ position: 'absolute', top: -22, right: 46, width: 36, height: 22, background: '#02060D' }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
        {Array.from({ length: 25 }).map((_, i) => {
          const isYou = i === YOU;
          const lateIdx = LATE.indexOf(i);
          const isLate = lateIdx >= 0;
          // amber windows turn off one-by-one early, leaving only your blue window
          const offAt = 22 + lateIdx * 16;
          const lit = isLate && frame < offAt;
          let bg = '#0A1322';
          let glow = 'none';
          if (isYou) {
            bg = '#5B9DFF';
            glow = `0 0 ${14 + youGlow * 22}px rgba(91,157,255,${youGlow})`;
          } else if (lit) {
            bg = '#E8A04C';
            glow = '0 0 16px rgba(255,180,84,0.4)';
          }
          return <div key={i} style={{ aspectRatio: '1 / 1.05', borderRadius: 1, background: bg, boxShadow: glow, transition: 'none' }} />;
        })}
      </div>
    </div>
  );
};

const POINTS = [
  { zh: '每位用户 · 独立数据库', k: 'tenant_<you>' },
  { zh: 'Fernet 凭证加密存储', k: 'AES-128 + HMAC' },
  { zh: '非 root 容器运行', k: 'rootless' },
  { zh: '登录限流 · 防护', k: '5 req/min' },
  { zh: '全部开源', k: 'MIT' },
];

export const Scene6Isolation: React.FC = () => {
  const frame = useCurrentFrame();
  const head = reveal(frame, 6, 18);
  const dormR = reveal(frame, 14, 24);
  const capR = reveal(frame, 60, 18);
  const pushIn = interpolate(frame, [0, 306], [1.0, 1.03], { extrapolateRight: 'clamp' });

  return (
    <SceneWrap pad={0} inF={12} outF={16}>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 130, transform: `scale(${pushIn})` }}>
        {/* LEFT: dorm */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ opacity: dormR.opacity, transform: `translateY(${dormR.y}px)` }}>
            <Dorm />
          </div>
          <div style={{ opacity: capR.opacity, marginTop: 24, fontFamily: monoFont, fontSize: 16, letterSpacing: '0.12em', color: COLORS.signal }}>
            你的数据库 · tenant_you
          </div>
        </div>

        {/* RIGHT: differentiators */}
        <div style={{ width: 620 }}>
          <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, marginBottom: 18 }}>
            <MonoEyebrow>数据隔离 · isolation</MonoEyebrow>
            <div style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 50, color: COLORS.paper, marginTop: 14 }}>自托管，数据是你的</div>
          </div>
          {POINTS.map((p, i) => {
            const r = reveal(frame, 40 + i * 14, 18, 22);
            return (
              <div key={i} style={{ opacity: r.opacity, transform: `translateY(${r.y}px)`, display: 'flex', alignItems: 'baseline', gap: 18, padding: '13px 0', borderTop: `1px solid ${COLORS.line}` }}>
                <span style={{ color: COLORS.lamp, fontSize: 22, lineHeight: 1 }}>▸</span>
                <span style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 26, color: COLORS.paper }}>{p.zh}</span>
                <span style={{ fontFamily: monoFont, fontSize: 16, color: COLORS.signal, letterSpacing: '0.04em', marginLeft: 'auto', opacity: 0.85 }}>{p.k}</span>
              </div>
            );
          })}
        </div>
      </div>
    </SceneWrap>
  );
};
