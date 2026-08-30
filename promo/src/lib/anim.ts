import { Easing, interpolate, spring } from 'remotion';

/**
 * Shared motion system — a tiny token set reused everywhere (the playbook's
 * "lock 2–3 curves and reuse them" rule). expo.out for entrances, back-pop for ✓.
 */

export const expoOut = Easing.out(Easing.exp);
export const quintOut = Easing.bezier(0.22, 1, 0.36, 1);
export const emphasized = Easing.bezier(0.05, 0.7, 0.1, 1.0); // Material emphasized-decelerate
export const inOutCubic = Easing.bezier(0.65, 0, 0.35, 1);

/** Standard reveal: fade + rise, settling with expo.out. Returns {opacity, y}. */
export function reveal(frame: number, start: number, dur = 22, rise = 28) {
  const t = interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: expoOut,
  });
  return { opacity: t, y: (1 - t) * rise, t };
}

/** Blur-to-sharp "developing" reveal for hero lockups. */
export function develop(frame: number, start: number, dur = 30) {
  const t = interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: emphasized,
  });
  return { opacity: t, blur: (1 - t) * 8, scale: 0.985 + t * 0.015, t };
}

/** Back-out overshoot pop (the satisfying ✓ done-pop). */
export function pop(frame: number, start: number, fps: number) {
  return spring({
    frame: frame - start,
    fps,
    config: { damping: 13, stiffness: 200, mass: 0.8, overshootClamping: false },
  });
}

/** Soft entrance scale, no overshoot (for big calm moves). */
export function riseScale(frame: number, start: number, fps: number) {
  return spring({
    frame: frame - start,
    fps,
    config: { damping: 200, stiffness: 80, mass: 1 },
  });
}

/** Masked line reveal amount 0→1 (text rising from behind a horizon). */
export function lineReveal(frame: number, start: number, dur = 26) {
  return interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: quintOut,
  });
}

/** Scene-level fade in/out envelope by local frame within a Sequence. */
export function envelope(frame: number, duration: number, inF = 16, outF = 14) {
  const fin = interpolate(frame, [0, inF], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: expoOut });
  const fout = interpolate(frame, [duration - outF, duration], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic) });
  return Math.min(fin, fout);
}
