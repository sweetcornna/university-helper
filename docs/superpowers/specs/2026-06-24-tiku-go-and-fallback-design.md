# 题库功能补全：GO 题库 + 多题库回退 + LocalCache 修复

**Date:** 2026-06-24
**Branch:** `feat/tiku-go-and-fallback`
**Upstream reference:** [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) `api/answer.py`

## Background

本项目的超星答题 (题库) 模块 fork 自 Samueli924/chaoxing 的 `api/answer.py`，
但落后于上游：上游 `PROVIDER_REGISTRY` 含 `TikuYanxi / TikuGo / TikuLike /
TikuAdapter / AI / SiliconFlow` 并支持 `TikuFallback` 多题库链式回退
(`provider = TikuYanxi,TikuGo,AI`)，而本 fork 只有 5 个 provider 且工厂只支持
单一 provider。此外前端 `ConfigSection.jsx` 已经列出「本地缓存 / LocalCache」
选项，但后端工厂没有注册它 —— 选中后会因「未知的题库 provider」静默禁用题库。

这就是「题库功能不完整」的具体含义。

## Goals

1. **GO 题库 (`TikuGo`)** —— 移植上游免费搜题源 (网课小工具, `q.icodef.com`)，
   适配本 fork 的重构包结构与多租户实例隔离约定。
2. **多题库回退 (`TikuFallback`)** —— `provider` 支持逗号分隔的多个题库，
   按顺序兜底；某题库未命中/类型不符则回退到下一个。
3. **LocalCache 修复** —— 新增 `TikuLocalCache` 并注册为 `LocalCache`，
   让已存在的前端「本地缓存」选项真正生效（只用已缓存答案，不调外部 API）。
4. **前端** —— 题库选择改为多选 + 顺序回退（序号徽标），新增「GO 题库」。
5. **文档** —— 在 `README.md` / `README.zh-CN.md` 各加一节「题库来源」。
6. **交付** —— feature 分支跑通测试后开 PR 至 `sweetcornna/university-helper:main`。

## Non-goals

- 不动单一 provider 的 AI/SiliconFlow 既有行为（缺 key 仍按现状报错——预存在问题，超出范围）。
- 不引入离线题库数据语料。
- 不做前端题库选择之外的 UX 重构。

## Architecture

复用现有结构，不重构既有边界：

| 单元 | 职责 | 依赖 |
|------|------|------|
| `answer_providers/go.py :: TikuGo` | GO 题库查询（节流+重试+占位答案识别） | `Tiku`、`requests` |
| `answer_providers/local_cache.py :: TikuLocalCache` | 只读缓存题库（`_query` 恒返回 None） | `Tiku` |
| `answer_base.py :: TikuFallback` | 按序包裹多个 provider，逐个兜底 | `check_answer`、运行时导入 `AI/SiliconFlow` |
| `answer_base.py :: get_tiku_from_config` | 解析 CSV `provider` → 单题库 / 回退链 | provider 注册表 |
| `payload_mapper.py :: normalize_tiku_config` | CSV provider 的 token 门控 + 透传 `go_authorization` | — |
| `ConfigSection.jsx` / `useTaskConfig.js` / `ChaoxingFanya.jsx` | 多选题库 UI → CSV `provider` | — |

### TikuGo 适配要点

- 实例属性（多租户隔离），非类属性。
- `requests` 全部带 `timeout=`，用 `loguru` logger，不用 `verify=False`。
- 保留：每请求最小间隔节流、429/流控重试退避、`q.icodef.com` 的
  `code != 1`/占位答案 (「李恒雅正在努力撰写中」) 识别、标题前缀剥离重试。
- `_init_tiku` 从 `self._conf` 读 `go_authorization`（可选）、`go_min_interval`
  /`go_retry_times`/`go_retry_backoff`（带默认与校验）。

### TikuFallback 语义（关键正确性点）

`_query` 按序遍历子 provider：

```
for provider in self.providers:
    answer = provider._query(q_info)          # try/except 包裹，异常→下一个
    if not answer: continue
    answer = answer.strip()
    # 与 base.query() 的 AI/SiliconFlow 特例保持一致：
    if isinstance(provider, (AI, SiliconFlow)):
        if q_info type == judgement:
            n = provider._normalize_judgement_answer(answer)
            if n is None: continue
            return n
        return answer                         # AI 非判断题：非空即采纳
    if check_answer(answer, q_info['type'], provider):
        return answer                         # 普通题库：类型校验通过才采纳
    # 类型不符 → 回退下一个
return None
```

- `_init_tiku` 对每个子 provider 调 `init_tiku()`，**try/except 丢弃初始化失败者**
  （如缺 token 的 TikuYanxi、缺 key 的 AI），全部失败则 `self.DISABLE = True`。
  这天然让「共享单 token + 混合链」健壮：能用的留下，不能用的丢掉。
- 缓存由外层 `TikuFallback.query()`（基类）统一写入一次，子 provider 用 `_query`
  绕过各自缓存，避免重复写。
- 暴露消费者用到的全部字段：`DISABLE / COVER_RATE / true_list / false_list /
  judgement_select / get_submit_params`（均由基类 `init_tiku` 从 config 设置）。

### 工厂 CSV 解析

`get_tiku_from_config`：把 `provider` 按 `,` 拆分、去空白；空→禁用；
含未知名→禁用并报错；单个→返回该 provider 实例（保持今日行为）；
多个→构造 `TikuFallback(chain)`。`_provider_map` 增加
`TikuGo`、`LocalCache`(→`TikuLocalCache`)。

### 前端多选回退

- `useTaskConfig`: `tikuProvider` 由字符串改为数组，默认 `['TikuYanxi']`。
- `ConfigSection`: 题库 pills 改为多选，点击 toggle 成员，选中顺序=回退顺序，
  选中 pill 上显示 ①②③ 序号；新增 `{ value: 'TikuGo', label: 'GO 题库',
  hint: '免费搜题源' }`。
- `ChaoxingFanya.jsx`: `provider: taskConfig.tikuProvider.join(',')`。

## Error handling

- 子题库网络异常/超时：捕获并回退下一个，不中断整卷。
- 子题库初始化异常：丢弃该子题库（见上）。
- 全链不可用：`DISABLE=True`，与「未配置题库」一致地静默跳过答题。

## Testing (TDD)

后端单测扩展 `tests/unit/test_answer_cache_and_tiku.py`（或新增
`test_tiku_go_and_fallback.py`）：

1. `TikuGo`：命中、未命中(code!=1)、占位答案被丢弃、流控重试、标题前缀剥离。
2. `TikuFallback`：首个命中即返回；首个未命中→回退；类型不符→回退；
   链尾 AI 判断题经 `_normalize_judgement_answer` 归一化；全部失败→None；
   `_init_tiku` 丢弃失败子题库；无可用→DISABLE。
3. 工厂：单 provider 不变；CSV→TikuFallback；含未知名→DISABLE；
   `LocalCache`/`TikuGo` 可解析。
4. `TikuLocalCache`：命中缓存返回、未缓存返回 None、`_query` 恒 None。
5. `payload_mapper`：CSV provider 不被单 provider token 门控误删；`go_authorization` 透传。

全套 `pytest` + 前端 `vitest` + `ruff` 必须绿。实现后用多 agent 工作流对 diff 做对抗式审查。

## Delivery

`feat/tiku-go-and-fallback` → 测试全绿 → push → PR vs `main`（README 一节说明）。
