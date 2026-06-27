import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { sansSC, monoFont } from '../fonts';
import { SceneWrap, ProgressBar, MonoEyebrow } from '../components/ui';
import { reveal, pop, expoOut } from '../lib/anim';

const TASKS = [
  { time: '01:00', course: '高等数学 · 章节测验', start: 10, dur: 44 },
  { time: '01:48', course: '大学英语 · 视频刷课', start: 38, dur: 44 },
  { time: '02:35', course: '心理学 · 见面课', start: 70, dur: 44 },
  { time: '03:20', course: '创业基础 · 自动答题', start: 102, dur: 46 },
];

const LOG = [
  { at: 8, t: '01:00:04  task#a41f  login ok · tenant_you' },
  { at: 22, t: '01:14:38  sign-in  location ✓ · all courses' },
  { at: 40, t: '01:32:11  chapter=4  quiz submitted  12/12' },
  { at: 62, t: '01:48:00  video  chapter=2  ▸ playing 100%' },
  { at: 88, t: '02:35:39  meeting  q#3 answered' },
  { at: 116, t: '03:20:50  retry  transient 502 · recovered' },
  { at: 150, t: '04:07:00  queue empty · sleep well', done: true },
];

export const Scene5Nightshift: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const head = reveal(frame, 4, 18);
  const thread = interpolate(frame, [10, 170], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });

  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <div style={{ position: 'absolute', left: 150, top: 120, right: 150, bottom: 120, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, marginBottom: 40 }}>
          <MonoEyebrow>夜班 · the night shift</MonoEyebrow>
        </div>

        <div style={{ display: 'flex', gap: 90, justifyContent: 'center' }}>
          {/* LEFT: vertical time rail */}
          <div style={{ position: 'relative', width: 720, paddingLeft: 96, flexShrink: 0 }}>
            {/* thread track + fill */}
            <div style={{ position: 'absolute', left: 86, top: 6, bottom: 6, width: 2, background: 'rgba(143,163,192,0.16)' }} />
            <div style={{ position: 'absolute', left: 86, top: 6, bottom: 6, width: 2, transformOrigin: 'top', transform: `scaleY(${thread})`, background: 'linear-gradient(180deg, #FFB454, #5B9DFF)' }} />

            {TASKS.map((t, i) => {
              const active = frame >= t.start && frame < t.start + t.dur;
              const done = frame >= t.start + t.dur;
              const prog = interpolate(frame, [t.start, t.start + t.dur], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
              const checkP = pop(frame, t.start + t.dur, fps);
              const r = reveal(frame, t.start - 12, 16);
              const nodeColor = done ? COLORS.done : active ? COLORS.lamp : '#22324F';
              return (
                <div key={i} style={{ position: 'relative', height: 92, opacity: r.opacity }}>
                  <span style={{ position: 'absolute', left: 0, top: 2, fontFamily: monoFont, fontSize: 18, color: COLORS.lamp, fontVariantNumeric: 'tabular-nums' }}>{t.time}</span>
                  <span
                    style={{
                      position: 'absolute',
                      left: 80,
                      top: 4,
                      width: 12,
                      height: 12,
                      borderRadius: '50%',
                      background: nodeColor,
                      transform: `scale(${active ? 1.3 : 1})`,
                      boxShadow: active ? `0 0 14px ${COLORS.lamp}` : done ? `0 0 10px rgba(61,220,151,0.7)` : 'none',
                    }}
                  />
                  <div style={{ paddingLeft: 130 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
                      <span style={{ fontFamily: sansSC, fontWeight: 500, fontSize: 25, color: COLORS.paper }}>{t.course}</span>
                      {done && <span style={{ fontFamily: monoFont, fontSize: 15, color: COLORS.done, transform: `scale(${checkP})` }}>✓ 已完成</span>}
                    </div>
                    <ProgressBar progress={prog} width={360} color={done ? COLORS.done : COLORS.signal} />
                  </div>
                </div>
              );
            })}
          </div>

          {/* RIGHT: monospace log */}
          <div style={{ width: 540, flexShrink: 0, paddingTop: 6 }}>
            {LOG.map((l, i) => {
              const r = reveal(frame, l.at, 14, 10);
              return (
                <div
                  key={i}
                  style={{
                    opacity: r.opacity * 0.92,
                    transform: `translateY(${r.y}px)`,
                    fontFamily: monoFont,
                    fontSize: 16,
                    lineHeight: 2.5,
                    letterSpacing: '0.02em',
                    color: l.done ? COLORS.done : COLORS.muted,
                    marginLeft: i % 2 === 1 ? 26 : i % 3 === 2 ? 12 : 0,
                  }}
                >
                  {l.t}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </SceneWrap>
  );
};
