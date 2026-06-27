import { Config } from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setConcurrency(null); // auto (≈ physical cores)
Config.setCodec('h264');
Config.setCrf(16); // near-visually-lossless for h264 (lower = better)
Config.setPixelFormat('yuv420p'); // QuickTime / web / social compatibility
// CJK woff2 fetches can be large on first render; don't let them abort the render.
Config.setDelayRenderTimeoutInMilliseconds(120000);
// No WebGL/Three content → leave the default Chromium renderer (don't force angle).
