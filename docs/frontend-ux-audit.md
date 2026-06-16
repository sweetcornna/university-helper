# 刷课/签到前端 UX/设计审计报告

> 范围：React + Vite + Tailwind 前端（认证、轨道首页、学习通签到、学习通泛雅、智慧树，以及设计系统/IA/冗余/a11y/反馈/响应式六大横切）。本报告基于已逐条对照源码核实的发现，按主题与严重度归并，保留 file:line 证据。

## 一、整体评估（评分 5/10）

底层有**真实的设计意图与工程功底**：完整的语义 token 体系（`index.css:13-37` 同时定义 `:root` 与完整 `.dark` 两套值）、封装的 `clay-card/clay-button/clay-input` 组件类、部分无障碍实现（44px 触控、`role`/`aria-live`、focus ring）、任务恢复与轮询竞态防护、URL 消毒。这不是随手堆的项目。

但**落地与底层意图严重背离**，三个系统性问题最伤用户：

1. **反馈系统碎片化、关键反馈看不见**——三页各发明一套通知机制，结果常渲染在用户视野之外，长任务切走即"失联"。
2. **设计系统名存实亡**——暗色是永不激活的死代码，100+ 处硬编码颜色绕过 token，状态色无语义层。
3. **表单几乎不替用户省事**——同一账号两页各填、从不记忆、默认抛出全部字段、移动端无法多选。

叠加首页把唯一入口做成持续自转、绕过 reduced-motion 的"移动靶"，整体更像**功能完备的炫技 Demo**，而非为高频签到/刷课优化过的成品。

---

## 二、按严重度/主题分组的发现

### P1 — 阻断体验/可访问性失败（优先修）

**反馈与状态可见性（最系统性的问题）**
- 学习通成功/失败提示埋在 6 按钮 + 超长表单之后，无 `role`/`aria-live`、不滚动入视、不自动消失，移动端必然滚出屏。`ChaoxingSignin.jsx:2425-2467`｜建议：统一 Toast（fixed + aria-live + 3-5s 消失），或至少 `scrollIntoView({block:'nearest'})` + `role="status"`。
- 结果反馈整块包在 `activeTab==='signin'` 内，但 tasks/config/banner 都会写结果——停在其它 tab 的用户看不到。`ChaoxingSignin.jsx:2425`｜建议：把反馈提升为页面级/Toast。
- 长任务轮询全程 `silent=true`，中途 failed/error 或轮询连续异常时界面零提示，进度条静止用户干等。`Zhihuishu.jsx:1109-1113,601-650`｜建议：检测终态/连续异常时主动去重提示，completed 给终态 success。
- 切 tab/课程后进行中任务的进度与日志不可见，无全局"进行中"指示。`Zhihuishu.jsx:1488-1567`、`ChaoxingSignin.jsx:2471-2581`｜建议：页头常驻 pill（X 个运行中 + 百分比）或 tab 标签运行中圆点。
- 三页三套反馈机制（底部 inline / 顶部双 div / 单 notice 槽），缺统一通知组件。`ChaoxingSignin.jsx:2425`、`ChaoxingFanya.jsx:188`、`Zhihuishu.jsx:1229`｜建议：抽 `useToast`/`<Notice>`。
- tasks tab「执行签到」无 loading/禁用态，可重复点击。`TasksTab.jsx:106`｜建议：透传 submitting，禁用 + "签到中..."。
- 注册页无 submitting 防抖、无 spinner、文案恒为「注册」，可重复提交。`Register.jsx:13-26,58-60`｜建议：对齐 Login。
- 泛雅 error/notice 无 aria-live、无图标、不自动消失。`ChaoxingFanya.jsx:188-189`。

**可访问性硬伤**
- 气泡 `aria-label={svc.name || svc.path}`，`svc.name` 恒 undefined，读屏对三主入口读出 `/chaoxing-signin` 等路径。`Dashboard.jsx:200`｜建议：`aria-label={`${svc.title}，${svc.desc}`}`。
- rAF 自转绕过 `prefers-reduced-motion`（媒体查询只管 CSS animation/transition，管不到 JS rAF），前庭敏感用户首页无限旋转。`Dashboard.jsx:86-103`、`index.css:101`｜建议：`matchMedia` 命中则不启动 tick。
- 学习通结果/错误消息无 aria-live，提交后读屏无反馈（知到页已用 `role=status`，不一致）。`ChaoxingSignin.jsx:2425-2467`。
- 纯图标按钮（刷新等）无可访问名称，读屏读为"按钮"。`ChaoxingSignin.jsx:1677-1692,1799-1813,2591-2609`。

**移动端核心范式**
- 课程/班级用原生 `<select multiple>`，触屏几乎无法精确多选——而这是核心操作。`ChaoxingSignin.jsx:1695-1713,1817-1835`｜建议：可勾选列表/chips + 全选/清空。
- 首页轨道气泡是移动端持续自转的"移动靶"，无 hover 不暂停、无 reduced-motion。`Dashboard.jsx:86-98`。

**信息架构**
- 默认 `signType='all'` 一次展开照片/经纬度/海拔/二维码/手势/签到码全部字段，严重过载。`ChaoxingSignin.jsx:1911-2315`。
- 底部 6 个按钮（验证/课程签到/课程任务/班级签到/班级任务/打开泛雅）无层级、命名相近、语义差异无说明。`ChaoxingSignin.jsx:2317-2419`。
- 账号密码每次进页面都要重填，全仓无任何持久化/回填。`ChaoxingSignin.jsx:82-114`。

### P2 — 显著体验缺陷

**设计系统/视觉一致性**
- `.dark` token 齐全但无任何激活入口（无 ThemeProvider/切换/`prefers-color-scheme`，`grep dark:`=0），暗色纯属死代码。`index.css:26-37`、`tailwind.config.js:4`。
- 100+ 处硬编码 `bg-white/border-white/text-slate/裸状态色` 绕过 token，暗色即使激活也破裂、品牌色无法全局改。`ChaoxingSignin.jsx`、`Zhihuishu.jsx:28-35`、`chaoxing-signin/utils.js:27` 等。
- 状态色（成功/错误/危险）用裸 Tailwind 调色板，无 `success/danger/warning` 语义 token；主操作色不统一（cta 橙 / sky-600 / primary）。`ChaoxingFanya.jsx:188-189`、`TaskControlSection.jsx:45`、`Zhihuishu.jsx:1497`。
- 8 个手写 `<select>` 重复粘贴 ~10 个 class，无统一 Select 组件；多份 `FIELD_CLASS/GLASS_PANEL_CLASS` 漂移（白 /60 vs /70 vs /80）。`C1-design-3/4`。
- 首页背景与气泡全硬编码浅色，暗色形同虚设。`Dashboard.jsx:152-159,242-260`。

**表单摩擦/冗余**
- 同一超星账号在签到页与泛雅页各维护独立 state，跨页/刷新均重填。`ChaoxingSignin.jsx:84-86`、`ChaoxingFanya.jsx:90-113`。
- 经纬度作为并列裸 Input 暴露，地图选点被降级为旁边次要按钮；缺"使用当前位置"。`ChaoxingSignin.jsx:1985-2015`、`C6-responsive-5`。
- 二维码"上传图片"与"手动输入"两入口并存、主从不清。`ChaoxingSignin.jsx:2179-2261`。
- 海拔 state 已默认 `'100'` 却又显示占位"默认 100"，逻辑自相矛盾。`ChaoxingSignin.jsx:100,2157-2173`。
- 智慧树要求手敲不透明 taskId 才能按 ID 刷新，与下方任务列表功能重复。`Zhihuishu.jsx:1501-1512`。

**IA/导航/反馈**
- 泛雅页无任何站内返回/登出/服务切换，仅一个 h1，与另两页不一致。`ChaoxingFanya.jsx:179-185`。
- 无共享 Layout，三页各自硬编码 header/背景/返回文案；登出位置行为不一、404 返回落到登录页。`App.jsx:19-40`、`C2-ia-nav-4/7`。
- 泛雅配置区一次抛出 11+ 个晦涩参数，无分组/说明/折叠；题库来源直接暴露内部代号 TikuYanxi/SiliconFlow。`ConfigSection.jsx:19-286,117-124`。
- 智慧树登录方式无切换器，qr/password 两套表单同屏并列，loginMethod 名存实亡。`Zhihuishu.jsx:1248-1293`。
- 倍速/自动答题在"课程"与"设置"两处重复且持久化语义不清。`Zhihuishu.jsx:1335-1356,1572-1603`。
- 全局暂停/恢复/取消破坏性操作零确认、作用范围不明。`Zhihuishu.jsx:1494-1498,798-855`。
- 进度条无 ARIA、二维码轮询状态无 aria-live、低对比文本（text/30·/50·/60）。`Zhihuishu.jsx:1440-1442`、`Dashboard.jsx:178,259`。
- 任务状态以裸 `JSON.stringify` 黑底代码块呈现给学生。`ChaoxingSignin.jsx:2531`。
- todayStats 与历史口径潜在不一致（若存在非终态 status）。`ChaoxingSignin.jsx:355`。
- 字段级校验缺失，错误只在提交后汇成一行红字，无 aria-invalid；状态英文裸词直出。`ChaoxingSignin.jsx:468-502`、`A5-fanya-4`、`A1-auth-7`。
- 地图选点 modal 移动端搜索结果与地图争抢竖向空间。`BaiduMapPickerModal.jsx:241-332`。
- 泛雅日志不可读：无 level 着色、无自动滚动、无复制；CourseList 缺加载/空状态。`LogSection.jsx:14-41`、`CourseListSection.jsx:93-228`。

### P3 — 打磨项

- `hover:scale-105` 泛滥（40 处含 icon 按钮），密集按钮区抖动、观感廉价。`index.css:68`、`ChaoxingSignin.jsx` 多处、`Login/Register`。
- 毛玻璃 `backdrop-blur` 滥用（22 处）成唯一层级手段，对比下降；智慧树三层半透明白嵌套。`Dashboard.jsx:156-158`、`Zhihuishu.jsx:28-31,1404-1481`。
- 破坏性操作无确认：Dashboard 退出、智慧树系统退出/全局取消、泛雅停止。`Dashboard.jsx:148`、`Zhihuishu.jsx:1669-1673`、`TaskControlSection.jsx:57-144`。
- 列表用 index/`Math.random()` 作 key；状态徽章未中文化；空状态过于朴素无引导 CTA。`HistoryTab.jsx:27`、`CourseListSection.jsx:108`、`A4-cxsignin-tabs-15`。
- 注册密码无显隐/强度提示、缺 noValidate、错误硬编码 `text-red-600`。`Register.jsx:35,50-57`、`A1-auth-6/8/10`。
- 移动端 JSON 用 `pre`/`break-all` 可读性差；二维码 224px 固定在超窄屏局促；并发滑块最高 16 无风险提示。`ChaoxingSignin.jsx:2531-2575`、`Zhihuishu.jsx:1271-1272`、`ConfigSection.jsx:56-83`。
- 检查间隔静默 clamp 无提示无预设；info 静态提示常驻 spinner 误导；首屏纯 spinner 无骨架。`ConfigTab.jsx:52`、`ChaoxingSignin.jsx:2455-2459`、`RouteFallback.jsx:3-16`。

---

## 三、分阶段落地路线图

### 阶段 0｜确定性 a11y/反馈硬伤（1 个 sprint，全 S，零风险）
1. Dashboard 气泡 `aria-label` → `title+desc`（`Dashboard.jsx:200`）。
2. 学习通结果容器加 `role=status`/`aria-live` + `scrollIntoView`（`ChaoxingSignin.jsx:2425-2467`）。
3. rAF 读 `prefers-reduced-motion`，命中静止；气泡 `onFocus/onBlur` 接 `setPaused`（`Dashboard.jsx:86-103,200-210`）。
4. 纯图标按钮补 `aria-label`；Dashboard 退出补 `focus-visible:ring`；进度条加 `role=progressbar`。
5. 注册页对齐登录页（submitting/role=alert/Input id/autoComplete/from 回跳）。
6. 日志自动贴底滚动；info 态去掉常驻 spinner。
7. Input 补 autoComplete + 回填上次 username；删除手敲 taskId 框、修海拔占位矛盾。

### 阶段 1｜统一反馈与可见性（结构性，但收益最大）
- 建 `ToastProvider`/`useToast`（success/error/info、aria-live、自动消失、可叠加），三页全部反馈调用点接入。
- 新增跨 tab 的"进行中任务"全局指示；长任务轮询失败/完成主动去重提示。
- 把学习通结果反馈移出 `signin` tab。

### 阶段 2｜表单收敛与移动端范式
- `signType` 默认收窄到检测/normal，字段按类型按需展开；确立单一主签到 CTA，次级动作收入下拉；表单隐式提交指向主签到。
- 课程/班级与判分映射改 MultiSelect/TagInput（chips + 搜索 + 全选）；题库代号改中文友好名 + "推荐"，专家参数折叠进"高级"。
- 经纬度折叠为"高级/手动"，"在地图上选择位置"/"使用当前位置"为主路径。
- 跨页共享 chaoxing 凭据 Context。

### 阶段 3｜设计系统收敛与暗色决策
- 拍板暗色去留：删 `.dark`+`darkMode:'class'`，或补 ThemeProvider + 切换入口。
- 全局替换硬编码色 → `surface/text/border` + 新增 `success/danger/warning` token；抽 `<Select>`/`<StatusBadge>`/`<Alert>`，收敛各页 `FIELD_CLASS/GLASS_PANEL_CLASS`。
- 收敛 `hover:scale` 与毛玻璃滥用（blur 仅限浮层）。

### 阶段 4｜IA 与外壳重构
- 引入共享 `AppLayout`（Outlet + logo + 服务切换 + 面包屑 + 带确认登出）；按登录态分流根路由，修 404 返回。
- 首页改静态卡片网格 + 状态概览；智慧树 5-tab 精简、登录方式做切换器、倍速/自答单一来源。
- 破坏性操作统一二次确认；空状态统一 EmptyState（图标 + 说明 + CTA）。