import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { COLORS } from '../tokens';
import { sansSC, monoFont } from '../fonts';
import { SceneWrap, MonoEyebrow } from '../components/ui';
import { reveal, pop } from '../lib/anim';
import { TECH_STACK } from '../script';

const LINES = [
  { prompt: '$', cmd: 'git clone https://github.com/sweetcornna/university-helper.git', comment: '' },
  { prompt: '$', cmd: 'cp .env.example .env', comment: '  # 填入密钥' },
  { prompt: '$', cmd: 'docker compose -f docker-compose.server.yml up -d --build', comment: '' },
];
const START = [6, 22, 38];
const TYPE = 15; // frames to "type" a line — all three land by ~local 53

const TypeLine: React.FC<{ line: (typeof LINES)[number]; start: number }> = ({ line, start }) => {
  const frame = useCurrentFrame();
  const shown = frame < start ? 0 : 1;
  const clip = interpolate(frame, [start, start + TYPE], [0, 100], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const typing = frame >= start && frame <= start + TYPE;
  const cursorOn = Math.floor(frame / 8) % 2 === 0;
  return (
    <div style={{ display: 'flex', gap: 16, lineHeight: 2.5, opacity: shown }}>
      <span style={{ color: COLORS.lamp, userSelect: 'none' }}>{line.prompt}</span>
      <span style={{ position: 'relative', whiteSpace: 'pre', overflow: 'hidden', display: 'inline-block' }}>
        <span style={{ display: 'inline-block', clipPath: `inset(0 ${100 - clip}% 0 0)` }}>
          <span style={{ color: COLORS.paper }}>{line.cmd}</span>
          <span style={{ color: COLORS.muted, opacity: 0.7 }}>{line.comment}</span>
        </span>
        {(typing || (frame > start + TYPE && start === START[START.length - 1])) && cursorOn && (
          <span style={{ position: 'absolute', left: `${clip}%`, color: COLORS.signal }}>▌</span>
        )}
      </span>
    </div>
  );
};

export const Scene7Deploy: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const head = reveal(frame, 6, 18);
  const copied = frame > 62;
  const copyPop = pop(frame, 62, fps);

  const COPY_W = 1750;
  const marqueeX = -((frame * 2.2) % COPY_W);
  const stack = [...TECH_STACK, ...TECH_STACK, ...TECH_STACK].join('   ✦   ');

  return (
    <SceneWrap pad={0} inF={12} outF={14}>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 188, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ opacity: head.opacity, transform: `translateY(${head.y}px)`, textAlign: 'center', marginBottom: 40 }}>
          <MonoEyebrow>启动 · deploy</MonoEyebrow>
          <div style={{ fontFamily: sansSC, fontWeight: 700, fontSize: 40, color: COLORS.paper, marginTop: 14 }}>三行命令，跑起来。</div>
        </div>

        {/* codeblock */}
        <div style={{ position: 'relative', width: 1180, borderLeft: `2px solid rgba(255,180,84,0.55)`, borderTop: `1px solid ${COLORS.line}`, borderBottom: `1px solid ${COLORS.line}`, paddingLeft: 40, paddingRight: 40 }}>
          {/* copy button */}
          <div
            style={{
              position: 'absolute',
              top: 18,
              right: 20,
              transform: `scale(${interpolate(copyPop, [0, 1], [1, 1.04])})`,
              fontFamily: monoFont,
              fontSize: 15,
              letterSpacing: '0.1em',
              color: copied ? COLORS.done : COLORS.muted,
              border: `1px solid ${copied ? 'rgba(61,220,151,0.5)' : COLORS.line}`,
              borderRadius: 4,
              padding: '6px 14px',
            }}
          >
            {copied ? '已复制 ✓' : '复制命令'}
          </div>
          <div style={{ fontFamily: monoFont, fontSize: 21, padding: '34px 0' }}>
            {LINES.map((l, i) => (
              <TypeLine key={i} line={l} start={START[i]} />
            ))}
          </div>
        </div>
      </div>

      {/* tech marquee */}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 220, borderTop: `1px solid ${COLORS.lineSoft}`, borderBottom: `1px solid ${COLORS.lineSoft}`, padding: '15px 0', overflow: 'hidden', opacity: 0.6 }}>
        <div style={{ display: 'flex', whiteSpace: 'nowrap', transform: `translateX(${marqueeX}px)`, fontFamily: monoFont, fontSize: 15, letterSpacing: '0.28em', color: COLORS.faint, textTransform: 'uppercase' }}>
          <span style={{ paddingRight: 0 }}>{stack}   ✦   </span>
          <span>{stack}   ✦   </span>
        </div>
      </div>
    </SceneWrap>
  );
};
