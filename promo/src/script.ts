/**
 * University Helper promo — master timeline + bilingual copy (single source of truth).
 * 1920x1080 · 30fps · 1800 frames (60s). Frame ranges are [from, durationInFrames].
 * The continuous <Sky> reads the global frame; scenes are mounted via <Sequence>.
 */

export type Beat = {
  id: string;
  /** story clock label, shown on the time rail */
  clock: string;
  phase: string; // Chinese phase name
  from: number; // start frame (global)
  duration: number; // frames
  zh: string; // primary subtitle (Chinese)
  en: string; // secondary subtitle (English)
  /** 'full' = zh+en lower-third; 'enOnly' = scene shows hero zh, subtitle shows en only; 'none' = scene owns all copy */
  sub?: 'full' | 'enOnly' | 'none';
};

export const FPS = 30;
const s = (sec: number) => Math.round(sec * FPS);

// Sequences are authored with a small cross-fade overlap handled inside scenes.
export const BEATS: Beat[] = [
  {
    id: 'hook',
    clock: '22:00',
    phase: '晚自习',
    from: s(0),
    duration: s(6.2),
    zh: '又一个，要熬到凌晨的夜。',
    en: 'Another night that runs past midnight.',
  },
  {
    id: 'reveal',
    clock: '22:30',
    phase: '交接',
    from: s(6),
    duration: s(6.2),
    zh: '你睡觉，它上课。',
    en: 'You sleep. It goes to class.',
    sub: 'enOnly',
  },
  {
    id: 'access',
    clock: '23:30',
    phase: '接入',
    from: s(12),
    duration: s(5.2),
    zh: '一次登录，全部接管。',
    en: 'Log in once. It takes over.',
  },
  {
    id: 'signin',
    clock: '00:20',
    phase: '签到',
    from: s(17),
    duration: s(6.2),
    zh: '位置、二维码、一键签全部。',
    en: 'Location · QR · one-tap sign-all.',
  },
  {
    id: 'nightshift',
    clock: '01:00',
    phase: '夜班',
    from: s(23),
    duration: s(7.2),
    zh: '整夜运转，自动完成。',
    en: 'Running all night. On its own.',
  },
  {
    id: 'isolation',
    clock: '03:00',
    phase: '隔离',
    from: s(30),
    duration: s(10.2),
    zh: '独立数据库，加密存储，完全开源。',
    en: 'Your own database. Encrypted. Open-source.',
  },
  {
    id: 'deploy',
    clock: '04:30',
    phase: '启动',
    from: s(40),
    duration: s(8.2),
    zh: '三行命令，部署在你自己的服务器。',
    en: 'Three lines. On a server you own.',
  },
  {
    id: 'daybreak',
    clock: '06:00',
    phase: '天亮',
    from: s(48),
    duration: s(10.2),
    zh: '天亮了。一切，已完成。',
    en: 'Morning. And it is all done.',
    sub: 'enOnly',
  },
  {
    id: 'endcard',
    clock: '',
    phase: '',
    from: s(58),
    duration: s(2),
    zh: '开源 · 自托管',
    en: 'Open-source · Self-hosted',
    sub: 'none',
  },
];

export const ENDCARD = {
  wordmark: 'University Helper',
  tagline: '你睡觉，它上课',
  url: 'shuake.cornna.xyz',
  repo: 'github.com/sweetcornna/university-helper',
  license: 'MIT',
};

/** Tech-stack marquee (used as a flicker during the deploy beat). */
export const TECH_STACK = [
  'FastAPI 0.115',
  'React 18',
  'Vite 5',
  'PostgreSQL 15',
  'Alembic',
  'Tailwind',
  'Docker Compose',
  'GitHub Actions',
  'CodeQL',
  'Trivy',
];

/** The three-line self-host command shown in the deploy beat. */
export const DEPLOY_CMD = [
  'git clone https://github.com/sweetcornna/university-helper.git',
  'cp .env.example .env          # fill secrets',
  'docker compose -f docker-compose.server.yml up -d --build',
];
