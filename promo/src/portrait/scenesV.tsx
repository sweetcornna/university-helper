import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC, monoFont } from '../fonts';
import { SceneWrap, ProgressBar, Glyph, MonoEyebrow } from '../components/ui';
import { reveal, pop, develop, lineReveal, expoOut } from '../lib/anim';
import { TECH_STACK, DEPLOY_CMD, ENDCARD } from '../script';

const PAD = '0 84px';

/* ── 1 · HOOK ─────────────────────────────────────────────── */
const HOOK = [
  ['高等数学', '章节测验 ×3'],
  ['大学英语', '视频 48 min'],
  ['心理学', '见面课'],
  ['中国近代史', '今日签到'],
  ['创业基础', '视频 ×6'],
  ['线性代数', '章节测验'],
];
const HSTART = [10, 24, 36, 46, 54, 60];

export const HookV: React.FC = () => {
  const frame = useCurrentFrame();
  const count = HSTART.filter((s) => frame > s + 8).length;
  const head = reveal(frame, 4, 18);
  return (
    <SceneWrap pad={0}>
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: PAD }}>
        <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 64 }}>
          <MonoEyebrow color={COLORS.muted} style={{ fontSize: 22 }}>今夜待办</MonoEyebrow>
          <span style={{ fontFamily: monoFont, fontWeight: 500, fontSize: 70, color: COLORS.lamp, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>{String(count).padStart(2, '0')}</span>
          <span style={{ fontFamily: sansSC, fontSize: 32, color: COLORS.muted }}>门课</span>
        </div>
        <div style={{ width: '100%', maxWidth: 880 }}>
          {HOOK.map((t, i) => {
            const r = reveal(frame, HSTART[i], 18, 26);
            return (
              <div key={i} style={{ opacity: r.opacity, transform: `translateY(${r.y}px)`, display: 'flex', alignItems: 'center', gap: 22, padding: '24px 0', borderTop: `1px solid ${COLORS.line}` }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: COLORS.muted, opacity: 0.6 }} />
                <span style={{ fontFamily: serifSC, fontWeight: 700, fontSize: 46, color: COLORS.paper }}>{t[0]}</span>
                <span style={{ marginLeft: 'auto', fontFamily: sansSC, fontSize: 28, color: COLORS.muted }}>{t[1]}</span>
                <span style={{ fontFamily: monoFont, fontSize: 20, color: COLORS.muted, letterSpacing: '0.16em', opacity: 0.65 }}>待办</span>
              </div>
            );
          })}
          <div style={{ borderTop: `1px solid ${COLORS.line}` }} />
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 2 · REVEAL ───────────────────────────────────────────── */
export const RevealV: React.FC = () => {
  const frame = useCurrentFrame();
  const lock = reveal(frame, 22, 22);
  const tag = lineReveal(frame, 32, 30);
  const dev = develop(frame, 32, 34);
  const glow = interpolate(frame, [32, 74], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <SceneWrap pad={0} inF={10} outF={16}>
      <AbsoluteFill style={{ background: 'radial-gradient(48% 28% at 50% 50%, rgba(5,10,20,0.5) 0%, transparent 72%)', opacity: lock.opacity }} />
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
        <div style={{ opacity: lock.opacity, transform: `translateY(${lock.y}px)`, display: 'flex', alignItems: 'center', gap: 20, marginBottom: 56 }}>
          <Img src={staticFile('favicon.svg')} style={{ width: 58, height: 58, borderRadius: 13 }} />
          <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 40, color: COLORS.paper }}>University&nbsp;Helper</span>
        </div>
        <div style={{ overflow: 'hidden', padding: '0 10px 22px' }}>
          <div style={{ textAlign: 'center', transform: `translateY(${(1 - tag) * 108}%)`, filter: `blur(${dev.blur}px)` }}>
            {['你睡觉，', '它上课。'].map((line, i) => (
              <div key={i} style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 176, lineHeight: 1.1, color: COLORS.paper, textShadow: `0 0 ${50 * glow}px rgba(91,157,255,${0.5 * glow})` }}>{line}</div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 3 · ACCESS ───────────────────────────────────────────── */
const PlatformV: React.FC<{ glyph: string; name: string; en: string; feats: string[]; start: number }> = ({ glyph, name, en, feats, start }) => {
  const frame = useCurrentFrame();
  const r = reveal(frame, start, 22);
  const gOp = interpolate(frame, [start, start + 12], [0, 0.05], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'relative', textAlign: 'center', opacity: r.opacity, transform: `translateY(${r.y}px)` }}>
      <Glyph char={glyph} opacity={gOp} size={300} style={{ position: 'absolute', top: -150, left: '50%', transform: 'translateX(-50%)', pointerEvents: 'none' }} />
      <div style={{ position: 'relative' }}>
        <MonoEyebrow color={COLORS.muted} style={{ fontSize: 18 }}>{en}</MonoEyebrow>
        <div style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 74, color: COLORS.paper, margin: '12px 0 22px' }}>{name}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 30px', justifyContent: 'center' }}>
          {feats.map((f, i) => (
            <span key={i} style={{ fontFamily: sansSC, fontSize: 28, color: COLORS.muted }}><span style={{ color: COLORS.signal, marginRight: 10 }}>—</span>{f}</span>
          ))}
        </div>
      </div>
    </div>
  );
};

export const AccessV: React.FC = () => {
  const frame = useCurrentFrame();
  const chip = reveal(frame, 22, 18);
  const rail = interpolate(frame, [10, 40], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: PAD }}>
        <PlatformV glyph="星" name="超星学习通" en="Chaoxing" feats={['位置 / 二维码签到', '泛雅刷课', '章节测验自动答']} start={10} />
        <div style={{ position: 'relative', height: 170, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ position: 'absolute', top: 0, bottom: 0, width: 1, background: 'rgba(143,163,192,0.3)', transform: `scaleY(${rail})`, transformOrigin: 'center' }} />
          <div style={{ opacity: chip.opacity, transform: `scale(${chip.opacity})`, padding: '12px 26px', border: '1px solid rgba(255,180,84,0.4)', borderRadius: 6, background: 'rgba(13,26,51,0.72)', fontFamily: monoFont, fontSize: 24, letterSpacing: '0.18em', color: COLORS.lamp, whiteSpace: 'nowrap' }}>一次登录</div>
        </div>
        <PlatformV glyph="树" name="智慧树" en="Zhihuishu" feats={['QR / 密码登录', '多课时视频', '见面课 · 自动答题']} start={20} />
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 4 · SIGN-IN (3 stacked rows) ─────────────────────────── */
const SignRow: React.FC<{ start: number; label: string; en: string; children: React.ReactNode }> = ({ start, label, en, children }) => {
  const frame = useCurrentFrame();
  const r = reveal(frame, start, 20, 24);
  return (
    <div style={{ opacity: r.opacity, transform: `translateY(${r.y}px)`, display: 'flex', alignItems: 'center', gap: 44, borderTop: `1px solid ${COLORS.line}`, padding: '34px 4px' }}>
      <div style={{ width: 200, height: 200, position: 'relative', flexShrink: 0 }}>{children}</div>
      <div>
        <div style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 46, color: COLORS.paper }}>{label}</div>
        <div style={{ fontFamily: monoFont, fontSize: 22, letterSpacing: '0.2em', color: COLORS.muted, textTransform: 'uppercase', marginTop: 8 }}>{en}</div>
      </div>
    </div>
  );
};

const MapMini: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const drop = pop(frame, start + 16, fps);
  const ripple = interpolate(frame, [start + 24, start + 70], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(13,26,51,0.4)', borderRadius: 6, overflow: 'hidden' }}>
      {[1, 2, 3, 4].map((i) => <div key={'h' + i} style={{ position: 'absolute', left: 0, right: 0, top: `${i * 20}%`, height: 1, background: 'rgba(143,163,192,0.10)' }} />)}
      {[1, 2, 3, 4].map((i) => <div key={'v' + i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${i * 20}%`, width: 1, background: 'rgba(143,163,192,0.10)' }} />)}
      <div style={{ position: 'absolute', left: '-10%', top: '62%', width: '120%', height: 6, background: 'rgba(91,157,255,0.18)', transform: 'rotate(-12deg)' }} />
      <div style={{ position: 'absolute', left: '50%', top: '46%', width: 16, height: 16, marginLeft: -8, marginTop: -8, borderRadius: '50%', border: `2px solid ${COLORS.signal}`, transform: `scale(${1 + ripple * 6})`, opacity: (1 - ripple) * 0.8 }} />
      <div style={{ position: 'absolute', left: '50%', top: '46%', transform: `translate(-50%, ${interpolate(drop, [0, 1], [-80, -30])}px) scale(${drop})` }}>
        <div style={{ width: 22, height: 22, borderRadius: '50% 50% 50% 0', background: COLORS.signal, transform: 'rotate(-45deg)', boxShadow: `0 0 16px ${COLORS.signal}` }} />
      </div>
    </div>
  );
};

const QrMini: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const N = 13;
  const scan = interpolate((frame - start - 14) % 60, [0, 60], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const show = frame > start + 8;
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'relative', width: 184, height: 184, opacity: show ? 1 : 0 }}>
        <div style={{ position: 'absolute', inset: 0, display: 'grid', gridTemplateColumns: `repeat(${N},1fr)`, gridTemplateRows: `repeat(${N},1fr)`, gap: 2 }}>
          {Array.from({ length: N * N }).map((_, i) => {
            const r = Math.floor(i / N), c = i % N;
            const finder = (r < 3 && c < 3) || (r < 3 && c >= N - 3) || (r >= N - 3 && c < 3);
            const h = Math.sin(r * 12.9898 + c * 78.233) * 43758.5453;
            const on = finder || h - Math.floor(h) > 0.55;
            return <div key={i} style={{ background: on ? COLORS.paper : 'transparent', borderRadius: 1, opacity: on ? 0.92 : 0 }} />;
          })}
        </div>
        <div style={{ position: 'absolute', left: -6, right: -6, top: `${scan * 100}%`, height: 3, background: COLORS.signal, boxShadow: `0 0 12px ${COLORS.signal}` }} />
      </div>
    </div>
  );
};

const CheckMini: React.FC<{ start: number }> = ({ start }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 18 }}>
      {[0, 1, 2].map((i) => {
        const at = start + 20 + i * 12;
        const p = pop(frame, at, fps);
        const done = frame > at + 2;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 28, height: 28, borderRadius: 6, border: `1.5px solid ${done ? COLORS.done : 'rgba(143,163,192,0.4)'}`, background: done ? 'rgba(61,220,151,0.14)' : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ color: COLORS.done, fontSize: 18, transform: `scale(${p})`, lineHeight: 1 }}>✓</span>
            </div>
            <div style={{ width: 96, height: 8, borderRadius: 4, background: done ? 'rgba(61,220,151,0.4)' : 'rgba(143,163,192,0.18)' }} />
          </div>
        );
      })}
    </div>
  );
};

export const SigninV: React.FC = () => {
  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', padding: PAD }}>
        <SignRow start={10} label="位置签到" en="Location"><MapMini start={10} /></SignRow>
        <SignRow start={28} label="二维码" en="QR Code"><QrMini start={28} /></SignRow>
        <SignRow start={46} label="一键签全部" en="Sign-all"><CheckMini start={46} /></SignRow>
        <div style={{ borderTop: `1px solid ${COLORS.line}` }} />
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 5 · NIGHT-SHIFT ──────────────────────────────────────── */
const NS_TASKS = [
  { time: '01:00', course: '高等数学 · 章节测验', start: 10, dur: 44 },
  { time: '01:48', course: '大学英语 · 视频刷课', start: 36, dur: 44 },
  { time: '02:35', course: '心理学 · 见面课', start: 64, dur: 44 },
  { time: '03:20', course: '创业基础 · 自动答题', start: 92, dur: 46 },
];
const NS_LOG = ['01:00:04  login ok · tenant_you', '01:48:00  video chapter=2 ▸ 100%', '04:07:00  queue empty · sleep well'];

export const NightshiftV: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const head = reveal(frame, 4, 18);
  const thread = interpolate(frame, [10, 150], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', padding: PAD }}>
        <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, marginBottom: 50 }}>
          <MonoEyebrow style={{ fontSize: 22 }}>夜班 · the night shift</MonoEyebrow>
        </div>
        <div style={{ position: 'relative', paddingLeft: 130 }}>
          <div style={{ position: 'absolute', left: 116, top: 6, bottom: 6, width: 2, background: 'rgba(143,163,192,0.16)' }} />
          <div style={{ position: 'absolute', left: 116, top: 6, bottom: 6, width: 2, transformOrigin: 'top', transform: `scaleY(${thread})`, background: 'linear-gradient(180deg,#FFB454,#5B9DFF)' }} />
          {NS_TASKS.map((t, i) => {
            const active = frame >= t.start && frame < t.start + t.dur;
            const done = frame >= t.start + t.dur;
            const prog = interpolate(frame, [t.start, t.start + t.dur], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
            const checkP = pop(frame, t.start + t.dur, fps);
            const r = reveal(frame, t.start - 12, 16);
            const nodeColor = done ? COLORS.done : active ? COLORS.lamp : '#22324F';
            return (
              <div key={i} style={{ position: 'relative', height: 132, opacity: r.opacity }}>
                <span style={{ position: 'absolute', left: -116, top: 2, fontFamily: monoFont, fontSize: 24, color: COLORS.lamp, fontVariantNumeric: 'tabular-nums' }}>{t.time}</span>
                <span style={{ position: 'absolute', left: -20, top: 6, width: 14, height: 14, borderRadius: '50%', background: nodeColor, transform: `scale(${active ? 1.3 : 1})`, boxShadow: active ? `0 0 14px ${COLORS.lamp}` : done ? '0 0 10px rgba(61,220,151,0.7)' : 'none' }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 18 }}>
                  <span style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 34, color: COLORS.paper }}>{t.course}</span>
                  {done && <span style={{ fontFamily: monoFont, fontSize: 20, color: COLORS.done, transform: `scale(${checkP})` }}>✓</span>}
                </div>
                <ProgressBar progress={prog} width={460} color={done ? COLORS.done : COLORS.signal} height={6} />
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 30, paddingLeft: 130 }}>
          {NS_LOG.map((l, i) => {
            const r = reveal(frame, 30 + i * 26, 14, 8);
            return <div key={i} style={{ opacity: r.opacity * 0.9, fontFamily: monoFont, fontSize: 22, lineHeight: 2.1, color: i === NS_LOG.length - 1 ? COLORS.done : COLORS.muted }}>{l}</div>;
          })}
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 6 · ISOLATION ────────────────────────────────────────── */
const YOU = 12;
const LATE = [3, 16, 21];
const DormV: React.FC = () => {
  const frame = useCurrentFrame();
  const youGlow = 0.32 + 0.28 * (0.5 - 0.5 * Math.cos(frame * 0.09));
  return (
    <div style={{ width: 420, padding: 36, paddingTop: 48, background: '#02060D', borderRadius: 8, position: 'relative', boxShadow: 'inset 0 1px 0 rgba(143,163,192,0.14)' }}>
      <div style={{ position: 'absolute', top: -26, right: 54, width: 42, height: 26, background: '#02060D' }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 18 }}>
        {Array.from({ length: 25 }).map((_, i) => {
          const isYou = i === YOU;
          const li = LATE.indexOf(i);
          const lit = li >= 0 && frame < 22 + li * 16;
          let bg = '#0A1322'; let glow = 'none';
          if (isYou) { bg = '#5B9DFF'; glow = `0 0 ${16 + youGlow * 22}px rgba(91,157,255,${youGlow})`; }
          else if (lit) { bg = '#E8A04C'; glow = '0 0 16px rgba(255,180,84,0.4)'; }
          return <div key={i} style={{ aspectRatio: '1 / 1.05', borderRadius: 2, background: bg, boxShadow: glow }} />;
        })}
      </div>
    </div>
  );
};
const ISO = [['每位用户 · 独立数据库', 'tenant_<you>'], ['Fernet 凭证加密存储', 'AES-128 + HMAC'], ['非 root 容器运行', 'rootless'], ['登录限流 · 防护', '5 req/min'], ['全部开源', 'MIT']];

export const IsolationV: React.FC = () => {
  const frame = useCurrentFrame();
  const head = reveal(frame, 6, 18);
  const dorm = reveal(frame, 14, 24);
  const cap = reveal(frame, 60, 18);
  return (
    <SceneWrap pad={0} inF={12} outF={16}>
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: PAD, gap: 40 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ opacity: dorm.opacity, transform: `translateY(${dorm.y}px)` }}><DormV /></div>
          <div style={{ opacity: cap.opacity, marginTop: 22, fontFamily: monoFont, fontSize: 22, letterSpacing: '0.1em', color: COLORS.signal }}>你的数据库 · tenant_you</div>
        </div>
        <div style={{ width: '100%', maxWidth: 880 }}>
          <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, textAlign: 'center', marginBottom: 14 }}>
            <div style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 56, color: COLORS.paper }}>自托管，数据是你的</div>
          </div>
          {ISO.map((p, i) => {
            const r = reveal(frame, 40 + i * 12, 18, 22);
            return (
              <div key={i} style={{ opacity: r.opacity, transform: `translateY(${r.y}px)`, display: 'flex', alignItems: 'baseline', gap: 18, padding: '16px 0', borderTop: `1px solid ${COLORS.line}` }}>
                <span style={{ color: COLORS.lamp, fontSize: 26 }}>▸</span>
                <span style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 32, color: COLORS.paper }}>{p[0]}</span>
                <span style={{ marginLeft: 'auto', fontFamily: monoFont, fontSize: 20, color: COLORS.signal, opacity: 0.85 }}>{p[1]}</span>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 7 · DEPLOY ───────────────────────────────────────────── */
const DSTART = [10, 30, 50];
export const DeployV: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const head = reveal(frame, 6, 18);
  const copied = frame > 70;
  const copyPop = pop(frame, 70, fps);
  const COPY_W = 1500;
  const marqueeX = -((frame * 2.0) % COPY_W);
  const stack = [...TECH_STACK, ...TECH_STACK, ...TECH_STACK].join('   ✦   ');
  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <AbsoluteFill style={{ flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: PAD }}>
        <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, textAlign: 'center', marginBottom: 50 }}>
          <MonoEyebrow style={{ fontSize: 22 }}>启动 · deploy</MonoEyebrow>
          <div style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 50, color: COLORS.paper, marginTop: 16 }}>三行命令，跑起来。</div>
        </div>
        <div style={{ position: 'relative', width: '100%', borderLeft: '2px solid rgba(255,180,84,0.55)', borderTop: `1px solid ${COLORS.line}`, borderBottom: `1px solid ${COLORS.line}`, paddingLeft: 36, paddingRight: 24, paddingTop: 36, paddingBottom: 36 }}>
          <div style={{ position: 'absolute', top: 18, right: 18, fontFamily: monoFont, fontSize: 20, letterSpacing: '0.08em', color: copied ? COLORS.done : COLORS.muted, border: `1px solid ${copied ? 'rgba(61,220,151,0.5)' : COLORS.line}`, borderRadius: 4, padding: '6px 14px', transform: `scale(${interpolate(copyPop, [0, 1], [1, 1.04])})` }}>{copied ? '已复制 ✓' : '复制命令'}</div>
          {DEPLOY_CMD.map((line, i) => {
            const r = reveal(frame, DSTART[i], 14, 12);
            const parts = line.split('#');
            return (
              <div key={i} style={{ opacity: r.opacity, transform: `translateY(${r.y}px)`, display: 'flex', gap: 14, fontFamily: monoFont, fontSize: 23, lineHeight: 2.3, whiteSpace: 'nowrap' }}>
                <span style={{ color: COLORS.lamp }}>$</span>
                <span><span style={{ color: COLORS.paper }}>{parts[0]}</span>{parts[1] && <span style={{ color: COLORS.muted, opacity: 0.7 }}>#{parts[1]}</span>}</span>
              </div>
            );
          })}
        </div>
        <div style={{ position: 'absolute', left: 0, right: 0, bottom: 150, borderTop: `1px solid ${COLORS.lineSoft}`, borderBottom: `1px solid ${COLORS.lineSoft}`, padding: '14px 0', overflow: 'hidden', opacity: 0.55 }}>
          <div style={{ display: 'flex', whiteSpace: 'nowrap', transform: `translateX(${marqueeX}px)`, fontFamily: monoFont, fontSize: 18, letterSpacing: '0.26em', color: COLORS.faint, textTransform: 'uppercase' }}>
            <span>{stack}   ✦   </span><span>{stack}   ✦   </span>
          </div>
        </div>
      </AbsoluteFill>
    </SceneWrap>
  );
};

/* ── 8 · DAYBREAK ─────────────────────────────────────────── */
const STATS: [string, number][] = [['签到', 6], ['视频', 12], ['章节测验', 9], ['见面课', 3]];
export const DaybreakV: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const heroReveal = lineReveal(frame, 14, 30);
  const dev = develop(frame, 14, 38);
  const ctx = interpolate(frame, [44, 66], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const statsR = interpolate(frame, [58, 78], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const pushIn = interpolate(frame, [0, 306], [1, 1.035], { extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <AbsoluteFill style={{ background: 'radial-gradient(54% 32% at 50% 42%, rgba(5,10,20,0.5) 0%, transparent 72%)' }} />
      <div style={{ position: 'relative', textAlign: 'center', transform: `scale(${pushIn})` }}>
        <div style={{ overflow: 'hidden', padding: '0 12px 20px' }}>
          <div style={{ fontFamily: serifSC, fontWeight: 900, fontSize: 196, lineHeight: 1.05, color: COLORS.paper, transform: `translateY(${(1 - heroReveal) * 110}%)`, filter: `blur(${dev.blur}px)`, textShadow: '0 0 56px rgba(255,238,200,0.45), 0 2px 26px rgba(5,10,20,0.8)' }}>天亮了。</div>
        </div>
        <div style={{ opacity: ctx, fontFamily: sansSC, fontWeight: 500, fontSize: 40, color: COLORS.paper, marginBottom: 44 }}>6 门课，<span style={{ color: COLORS.done }}>全部完成</span>。</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '28px 60px', justifyContent: 'center', opacity: statsR }}>
          {STATS.map((s, i) => {
            const at = 60 + i * 9;
            const p = pop(frame, at, fps);
            const val = Math.round(interpolate(frame, [at, at + 16], [0, s[1]], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }));
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 12, justifyContent: 'center', transform: `scale(${interpolate(p, [0, 1], [0.92, 1])})` }}>
                <span style={{ color: COLORS.done, fontSize: 30 }}>✓</span>
                <span style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 36, color: COLORS.muted }}>{s[0]}</span>
                <span style={{ fontFamily: monoFont, fontWeight: 500, fontSize: 40, color: COLORS.paper, fontVariantNumeric: 'tabular-nums' }}>{val}</span>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ── 9 · ENDCARD ──────────────────────────────────────────── */
export const EndcardV: React.FC = () => {
  const frame = useCurrentFrame();
  const dev = develop(frame, 4, 24);
  const meta = reveal(frame, 16, 20);
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <AbsoluteFill style={{ background: 'radial-gradient(56% 30% at 50% 46%, rgba(5,10,20,0.5) 0%, transparent 72%)' }} />
      <AbsoluteFill style={{ background: 'linear-gradient(0deg, rgba(5,10,20,0.55) 0%, rgba(5,10,20,0) 18%)' }} />
      <div style={{ position: 'relative', textAlign: 'center', opacity: dev.opacity, transform: `scale(${dev.scale})` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 22, marginBottom: 28 }}>
          <Img src={staticFile('favicon.svg')} style={{ width: 80, height: 80, borderRadius: 18 }} />
          <span style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 58, color: COLORS.paper }}>University&nbsp;Helper</span>
        </div>
        <div style={{ fontFamily: serifSC, fontWeight: 700, fontSize: 52, color: COLORS.paper, letterSpacing: '0.06em', textShadow: '0 0 50px rgba(255,213,142,0.35)' }}>{ENDCARD.tagline}</div>
        <div style={{ opacity: meta.opacity, transform: `translateY(${meta.y}px)`, marginTop: 48 }}>
          <div style={{ fontFamily: monoFont, fontSize: 22, letterSpacing: '0.28em', color: COLORS.lamp, textTransform: 'uppercase', marginBottom: 24 }}>开源 · 自托管</div>
          <div style={{ fontFamily: monoFont, fontSize: 28, color: COLORS.paper, lineHeight: 1.9 }}>
            {ENDCARD.url}<br />{ENDCARD.repo}<br /><span style={{ color: COLORS.signal }}>{ENDCARD.license}</span>
          </div>
        </div>
      </div>
      <div style={{ position: 'absolute', bottom: 40, width: '100%', textAlign: 'center', opacity: meta.opacity, fontFamily: monoFont, fontSize: 18, letterSpacing: '0.05em', color: '#FFFFFF' }}>
        Music: “Hymn to the Dawn” by Scott Buckley — CC BY 4.0
      </div>
    </AbsoluteFill>
  );
};
