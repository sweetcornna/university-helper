/**
 * "一夜" night→dawn engine, ported 1:1 from the showcase site's setNight(p).
 * Drives a single normalized progress p∈[0,1] (p = frame / durationInFrames).
 * All screen positions resolved for the fixed 1920×1080 canvas.
 */

export const W = 1920;
export const H = 1080;

export const clamp = (x: number, a = 0, b = 1) => Math.max(a, Math.min(b, x));
export const ramp = (p: number, a: number, b: number) => clamp((p - a) / (b - a), 0, 1);
const PI = Math.PI;

export type NightState = {
  p: number;
  clock: string; // "HH:MM" mono
  phase: string; // 晚自习 / 深夜 / 凌晨 / 将明 / 天亮
  skyNight: number; // opacity
  skyPreDawn: number;
  skyDawn: number;
  stars: number; // stars container opacity
  lit: boolean; // p > 0.82 — dark text takes over
  moon: { x: number; y: number; scale: number; opacity: number };
  sun: { x: number; y: number; scale: number; opacity: number };
};

export function nightState(p: number, width = W, height = H): NightState {
  const vw = (v: number) => (v / 100) * width;
  const vh = (v: number) => (v / 100) * height;
  p = clamp(p);
  const mins = 22 * 60 + p * 480; // 22:00 over exactly 8h → 06:00
  const hh = Math.floor(mins / 60) % 24;
  const mm = Math.floor(mins % 60);
  const clock = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  const phase = p < 0.18 ? '晚自习' : p < 0.45 ? '深夜' : p < 0.72 ? '凌晨' : p < 0.92 ? '将明' : '天亮';

  // Moon: arc right→left on a sin() curve with a "cloud" dimming dip near 01:00.
  const tm = ramp(p, 0, 0.72);
  const cloud = 1 - 0.72 * (ramp(mins, 1485, 1515) * (1 - ramp(mins, 1605, 1645)));
  // Kept in the top band so it never crosses the content mid-band; opacity is
  // additionally masked in <Sky> so the moon is an opening-night element that
  // "clouds over" once the night shift begins (removes all foreground collisions).
  const moon = {
    x: vw(86 - 58 * tm),
    y: vh(23 - Math.sin(tm * PI) * 13),
    scale: 0.82 + 0.18 * cloud,
    opacity: (1 - ramp(p, 0.6, 0.74)) * cloud,
  };

  // Sun: rises from below the horizon at dawn.
  const ts = ramp(p, 0.78, 1);
  const sun = {
    x: vw(50),
    y: vh(112 - 44 * ts),
    scale: 0.85 + 0.25 * ts,
    opacity: ramp(p, 0.78, 0.86),
  };

  return {
    p,
    clock,
    phase,
    skyNight: 1 - 0.5 * ramp(p, 0.3, 0.7),
    skyPreDawn: ramp(p, 0.3, 0.62),
    skyDawn: ramp(p, 0.7, 0.95),
    stars: 1 - ramp(p, 0.62, 0.88),
    lit: p > 0.82,
    moon,
    sun,
  };
}

/** Deterministic per-star field (mirrors the site's hash placement). */
export type Star = { left: number; top: number; size: number; peak: number; durF: number; delayF: number };
export function makeStars(count = 130, fps = 30, width = W, height = H): Star[] {
  const out: Star[] = [];
  for (let i = 1; i <= count; i++) {
    const h = Math.sin(i * 127.1) * 43758.5453;
    const rx = h - Math.floor(h);
    const h2 = Math.sin(i * 311.7) * 26951.3571;
    const ry = h2 - Math.floor(h2);
    out.push({
      left: rx * width,
      top: ry * 0.72 * height,
      size: i % 9 === 0 ? 3 : 2,
      peak: 0.45 + rx * 0.5,
      durF: (2.4 + rx * 3.6) * fps,
      delayF: ry * 4 * fps,
    });
  }
  return out;
}
