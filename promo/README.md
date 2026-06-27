# University Helper — SaaS 宣传片 (Remotion)

一支 60 秒、1080p、中英双语字幕的产品宣传片，用 [Remotion](https://remotion.dev) 逐帧渲染为真·MP4。
沿用展示站 `site/` 的「一夜」夜→昼品牌语言：整片天空是一条连续的夜→晨色彩弧线，
讲述「你睡觉，它上课」——夜里替你在超星学习通 / 智慧树签到、刷课、答题，天亮时一切已完成。

## 结构

- `src/index.ts` — registerRoot 入口
- `src/Root.tsx` — `<Composition>`（1920×1080 · 30fps · 1800 帧）
- `src/Promo.tsx` — 合成根：连续 `<Sky>` + `<Atmosphere>` + 场景栈 + `<Hud>` + 双语字幕 + `<Audio>`
- `src/SceneStack.tsx` — 9 个场景按全局时钟用显式 `<Sequence>` 串联
- `src/scenes/*` — 9 个节拍：hook → reveal → access → signin → nightshift → isolation → deploy → daybreak → endcard
- `src/lib/night.ts` — 从 `site/assets/night.js` 1:1 移植的 `setNight(p)` 夜→晨引擎（月/日运行轨迹、星空、相位时钟）
- `src/lib/anim.ts` — 共享动效系统（expo.out 入场、back-out ✓ 弹跳、masked reveal 等）
- `src/tokens.ts` / `src/fonts.ts` — 品牌色 token 与字体（Noto Serif SC / Noto Sans SC / IBM Plex Mono）
- `src/script.ts` — 时间轴 + 中英双语文案单一事实源
- `public/music.mp3` — 60 秒配乐（见下方版权）

## 渲染

```bash
npm install
npx remotion studio                      # 交互预览
npx remotion render src/index.ts UniversityHelperPromo out/university-helper-promo.mp4
# 单帧快速检查：
npx remotion still src/index.ts UniversityHelperPromo out/frame.png --frame=1500
```

渲染参数（编解码 h264 / crf16 / yuv420p / 字体超时 120s）固定在 `remotion.config.ts`。

## 改文案 / 改时长

所有字幕与节拍时间都在 `src/script.ts` 的 `BEATS`。改完字幕即更新；改时长需同时调整对应 `from`/`duration`
并保持总帧数 = `VIDEO.durationInFrames`（`src/tokens.ts`）。

## 配乐版权（重要）

背景音乐为 **“Hymn to the Dawn” by Scott Buckley**，授权 **CC BY 4.0**，来源 https://www.scottbuckley.com.au 。
本片取其 75s–135s 片段并做淡入淡出 + 响度归一（CC-BY 允许商用与修改，需署名）。片尾已包含署名：

> Music: “Hymn to the Dawn” by Scott Buckley — CC BY 4.0 · scottbuckley.com.au

替换其它配乐时请同步更新片尾署名（`src/scenes/Scene9Endcard.tsx`），并确认新曲目授权允许商用。
`out/source_hymn.mp3` 为原始完整曲目（仅作裁剪源，不分发）。
