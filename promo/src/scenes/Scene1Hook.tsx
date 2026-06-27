import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { serifSC, sansSC, monoFont } from '../fonts';
import { SceneWrap, MonoEyebrow } from '../components/ui';
import { reveal } from '../lib/anim';

const TASKS = [
  { course: '高等数学', plat: '超星学习通', task: '章节测验 ×3' },
  { course: '大学英语', plat: '超星学习通', task: '视频 48 min' },
  { course: '心理学', plat: '智慧树', task: '见面课 待完成' },
  { course: '中国近代史', plat: '超星学习通', task: '今日签到' },
  { course: '创业基础', plat: '智慧树', task: '视频 ×6' },
  { course: '线性代数', plat: '超星学习通', task: '章节测验' },
];
// diminishing gaps → the pile mounts faster and faster
const STARTS = [12, 28, 42, 53, 61, 67];

export const Scene1Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const count = STARTS.filter((s) => frame > s + 8).length;
  const headR = reveal(frame, 4, 20);

  return (
    <SceneWrap pad={0}>
      {/* left column — pile of tonight's tasks; right third left to the sky/moon */}
      <div style={{ position: 'absolute', left: 150, top: 196, width: 820 }}>
        <div style={{ opacity: headR.opacity, transform: `translateY(${headR.y}px)`, display: 'flex', alignItems: 'baseline', gap: 18, marginBottom: 30 }}>
          <MonoEyebrow color={COLORS.muted}>今夜待办 · tonight</MonoEyebrow>
          <span style={{ fontFamily: monoFont, fontWeight: 500, fontSize: 40, color: COLORS.lamp, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
            {String(count).padStart(2, '0')}
          </span>
          <span style={{ fontFamily: sansSC, fontSize: 22, color: COLORS.muted }}>门课</span>
        </div>

        {TASKS.map((t, i) => {
          const r = reveal(frame, STARTS[i], 18, 26);
          const dotPulse = 0.5 + 0.5 * Math.sin((frame - STARTS[i]) * 0.18);
          return (
            <div
              key={i}
              style={{
                opacity: r.opacity,
                transform: `translateY(${r.y}px)`,
                display: 'flex',
                alignItems: 'center',
                gap: 22,
                padding: '17px 0',
                borderTop: `1px solid ${COLORS.line}`,
              }}
            >
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: COLORS.muted, opacity: 0.45 + 0.4 * dotPulse }} />
              <span style={{ fontFamily: serifSC, fontWeight: 700, fontSize: 30, color: COLORS.paper, minWidth: 220 }}>{t.course}</span>
              <span style={{ fontFamily: monoFont, fontSize: 16, color: COLORS.muted, letterSpacing: '0.06em', minWidth: 150, opacity: 0.9 }}>{t.plat}</span>
              <span style={{ fontFamily: sansSC, fontSize: 19, color: COLORS.muted, marginLeft: 'auto' }}>{t.task}</span>
              <span style={{ fontFamily: monoFont, fontSize: 14, color: COLORS.muted, letterSpacing: '0.16em', opacity: 0.7 }}>待办</span>
            </div>
          );
        })}
        <div style={{ borderTop: `1px solid ${COLORS.line}` }} />
      </div>
    </SceneWrap>
  );
};
