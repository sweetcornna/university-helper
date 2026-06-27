/**
 * Fonts loaded via @remotion/google-fonts. loadFont() wires delayRender internally.
 * CJK families are large — scope to weights + the chinese-simplified subset to avoid
 * the default 30s delayRender timeout (render timeout also raised in remotion.config.ts).
 */
import { loadFont as loadSerifSC } from '@remotion/google-fonts/NotoSerifSC';
import { loadFont as loadSansSC } from '@remotion/google-fonts/NotoSansSC';
import { loadFont as loadPlexMono } from '@remotion/google-fonts/IBMPlexMono';

export const { fontFamily: serifSC } = loadSerifSC('normal', {
  weights: ['500', '700', '900'],
  subsets: ['chinese-simplified', 'latin'],
});

export const { fontFamily: sansSC } = loadSansSC('normal', {
  weights: ['400', '500', '700'],
  subsets: ['chinese-simplified', 'latin'],
});

export const { fontFamily: monoFont } = loadPlexMono('normal', {
  weights: ['400', '500'],
  subsets: ['latin'],
});
