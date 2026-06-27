/**
 * University Helper — brand design tokens
 * Mirrors the showcase site (site/assets/style.css): the "一夜" night→day language.
 */

export const COLORS = {
  // Night (default canvas)
  night: '#050A14', // deep night sky — base background
  deep: '#0A1428', // dark panel
  panel: '#0D1A33', // card / container surface
  panelHi: '#11203D', // slightly lifted surface
  paper: '#E9F0FA', // moon-white — primary text
  muted: '#8FA3C0', // secondary / dimmed text
  faint: '#5C6E8C', // tertiary text / captions
  signal: '#5B9DFF', // signal blue — progress / data
  brand: '#2563EB', // primary action blue
  brandDeep: '#1D4ED8',
  lamp: '#FFB454', // amber/gold — time, highlights, lamplight
  lampDeep: '#E89B3C',
  done: '#3DDC97', // completion green — success only
  line: 'rgba(143,163,192,0.16)', // subtle divider
  lineSoft: 'rgba(143,163,192,0.10)',

  // Day (dawn payoff)
  dayBg: '#F3F7FC',
  dayCard: '#FFFFFF',
  dayInk: '#16243D',
  dayMuted: '#5A6B85',
  dayLine: '#DCE5F1',
} as const;

/** Sky gradient stops across the night → dawn arc (top, bottom) for interpolation. */
export const SKY = {
  // 22:00 deep night
  night: { top: '#03060F', mid: '#050A14', bottom: '#0A1428' },
  // 01:00 — coldest, deepest
  midnight: { top: '#02040C', mid: '#04081A', bottom: '#0B1A38' },
  // 03:00 — first hint of warmth at horizon
  preDawn: { top: '#070A18', mid: '#0E1430', bottom: '#241B3A' },
  // 04:30 — horizon warms
  dawn: { top: '#13213F', mid: '#3A3A57', bottom: '#6B4A50' },
  // 06:00 — sunrise
  sunrise: { top: '#9DB9E8', mid: '#E7C7A0', bottom: '#FFE2B0' },
} as const;

export const FONTS = {
  serif: '"Noto Serif SC", "Source Han Serif SC", "Songti SC", serif',
  sans: '"Noto Sans SC", "PingFang SC", "Hiragino Sans GB", system-ui, sans-serif',
  mono: '"IBM Plex Mono", "SF Mono", ui-monospace, monospace',
} as const;

/** Video spec */
export const VIDEO = {
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 1800, // 60s
} as const;

/** Premium easing — long, expensive ease-out (cubic-bezier .16,1,.3,1 equivalent). */
export const EASE = {
  out: [0.16, 1, 0.3, 1] as [number, number, number, number],
  inOut: [0.65, 0, 0.35, 1] as [number, number, number, number],
  outSoft: [0.22, 1, 0.36, 1] as [number, number, number, number],
};

export const SPRING = {
  // gentle, no overshoot — for type and large moves
  smooth: { damping: 200, stiffness: 90, mass: 1 },
  // subtle overshoot — for arrivals/snaps
  pop: { damping: 14, stiffness: 110, mass: 0.9 },
  // very soft drift — for ambient parallax
  drift: { damping: 200, stiffness: 40, mass: 1 },
};
