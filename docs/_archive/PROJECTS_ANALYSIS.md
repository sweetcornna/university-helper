# 三个原项目深度分析报告

## 项目概览

### 1. chaoxing-fanya (超星学习通自动化刷课工具)
- **仓库**: E:/project/sign_in/chaoxing-fanya
- **技术栈**: Python (Flask) + React + TailwindCSS
- **目标平台**: 超星学习通 (Chaoxing)
- **架构模式**: 前后端分离 (Web + CLI)

### 2. zhihuishu_LOL (智慧树自动刷课脚本)
- **仓库**: E:/project/sign_in/zhihuishu_LOL
- **技术栈**: Python (纯后端)
- **目标平台**: 智慧树 (Zhihuishu)
- **架构模式**: CLI + API Server

### 3. chaoxing-signin (超星签到工具)
- **仓库**: E:/project/sign_in/chaoxing-signin
- **技术栈**: 未详细分析 (目录结构异常)
- **目标平台**: 超星学习通签到功能
- **状态**: 需进一步确认项目结构

---

## 一、chaoxing-fanya 项目分析

### 1.1 核心功能模块

#### 登录认证模块 (`api/base.py`)
- **账号密码登录**: AES加密传输
- **Cookies登录**: 支持持久化会话
- **会话管理**: 单例模式的SessionManager
- **速率限制**: RateLimiter防止请求过快

#### 课程学习模块 (`main.py`)
- **课程列表获取**: `get_course_list()`
- **章节点位获取**: `get_course_point()`
- **任务处理**:
  - 视频任务 (Video/Audio)
  - 文档任务 (Document)
  - 测验任务 (Work)
  - 阅读任务 (Read)
  - 直播任务 (Live)
- **并发控制**: ThreadPoolExecutor + PriorityQueue
- **重试机制**: 最多5次重试，支持retry/ask/continue策略

#### 题库答题模块 (`api/answer.py`)
- **多题库支持**:
  - Yanxi (燕溪题库)
  - Like (Like题库)
  - TikuAdapter (题库适配器)
  - AI (AI大模型答题)
  - SiliconFlow (硅基流动)
- **OCR识别**: PaddleOCR本地识别 + 外部大模型OCR
- **答案覆盖率**: 可配置cover_rate (0.0-1.0)
- **自动提交**: 可配置是否自动提交答案

#### 通知推送模块 (`api/notification.py`)
- **支持渠道**:
  - Server酱 (ServerChan)
  - Qmsg
  - Bark
  - Telegram
- **推送场景**: 任务完成、错误异常

#### Web可视化模块 (`app.py` + `web/`)
- **前端技术**: React + Vite + TailwindCSS
- **实时功能**:
  - 实时日志流 (log_queue)
  - 进度追踪 (task_status)
  - 视频播放进度 (video_progress_callback)
  - 章节完成统计 (chapter_done_callback)
- **API接口**:
  - `/api/login` - 用户登录
  - `/api/courses` - 获取课程列表
  - `/api/start` - 启动学习任务
  - `/api/task/<task_id>` - 获取任务状态
  - `/api/task/<task_id>/details` - 获取任务详情
  - `/api/logs/<task_id>` - 获取实时日志
  - `/api/config` - 配置管理

### 1.2 核心代码文件列表

```
chaoxing-fanya/
├── app.py                      # Flask后端入口 (553行)
├── main.py                     # CLI入口 (570行)
├── api/
│   ├── base.py                 # 核心API类 (Chaoxing, Account, SessionManager)
│   ├── answer.py               # 题库模块 (47492字节)
│   ├── decode.py               # 数据解码 (34076字节)
│   ├── notification.py         # 通知推送 (9502字节)
│   ├── vision_ocr.py           # OCR识别 (9901字节)
│   ├── live.py                 # 直播任务 (3165字节)
│   ├── captcha.py              # 验证码处理 (4127字节)
│   ├── cipher.py               # AES加密 (1585字节)
│   └── exceptions.py           # 异常定义 (650字节)
├── web/                        # React前端
└── requirements.txt            # Python依赖
```

### 1.3 API接口定义

#### 超星平台API
```python
# 登录接口
POST https://passport2.chaoxing.com/fanyalogin
参数: fid, uname(加密), password(加密), refer, t, forbidotherlogin

# 课程列表
GET https://mooc1-api.chaoxing.com/mycourse/backclazzdata

# 章节点位
GET https://mooc1-api.chaoxing.com/knowledge/cards

# 视频学习
GET https://mooc1-api.chaoxing.com/multimedia/log/a/{courseId}/{clazzId}

# 作业提交
POST https://mooc1-api.chaoxing.com/work/addStudentWorkNew
```

#### 题库API
```python
# Yanxi题库
POST http://cx.icodef.com/wyn-nb
参数: question (题目文本)

# Like题库
GET https://www.likexueba.com/api/search
参数: title (题目)

# TikuAdapter
POST https://tikuadapter.com/api/v1/search
参数: question, options

# AI答题 (OpenAI兼容)
POST {api_base}/chat/completions
参数: model, messages, temperature
```

### 1.4 数据模型

#### Account (账户)
```python
class Account:
    username: str      # 手机号
    password: str      # 密码
    last_login: datetime
    isSuccess: bool
```

#### Course (课程)
```python
{
    "courseId": str,
    "clazzId": str,
    "cpi": str,
    "title": str,
    "teacherfactor": str
}
```

#### Point (章节点位)
```python
{
    "id": str,
    "title": str,
    "has_finished": bool,
    "jobCount": int,
    "knowledgeid": str
}
```

#### Job (任务点)
```python
{
    "jobid": str,
    "type": str,  # video/document/workid/read/live
    "name": str,
    "objectId": str,
    "otherInfo": str
}
```

#### StudyResult (学习结果)
```python
class StudyResult(Enum):
    SUCCESS = 0
    FORBIDDEN = 1  # 403
    ERROR = 2
    TIMEOUT = 3
```

### 1.5 依赖关系

```
核心依赖:
- requests>=2.32.5          # HTTP请求
- flask>=3.1.2              # Web框架
- flask-cors>=5.0.0         # 跨域支持
- beautifulsoup4>=4.14.2    # HTML解析
- loguru>=0.7.3             # 日志
- openai>=1.109.1           # AI题库
- ddddocr                   # 验证码识别
- httpx>=0.28.1             # 异步HTTP

可选依赖:
- paddlepaddle              # 本地OCR
- paddlex                   # PaddleOCR扩展
```

---

## 二、zhihuishu_LOL 项目分析

### 2.1 核心功能模块

#### 登录认证模块 (`fucker.py:140-252`)
- **二维码登录**: 主要登录方式
- **账号密码登录**: 备用方式
- **Cookies持久化**: 保存到cookies.json
- **会话恢复**: 自动从保存的cookies恢复

#### 课程学习模块 (`fucker.py`)
- **课程类型**:
  - 知到共享学分课 (Zhidao)
  - 校内学分课 (Hike)
  - AI课程 (AI Course)
- **视频学习**:
  - 自动播放
  - 速度控制 (最大444倍速)
  - 进度上报
  - 弹题自动回答
- **时间限制**: 可设置每节课学习时长上限

#### 弹题答题模块
- **知到AI答题**: 使用平台内置AI
- **外部AI答题**: OpenAI兼容接口
- **PPT处理**: MoonShot API转换PPT为文本
- **流式输出**: 支持流式响应

#### 推送通知模块 (`push.py`)
- **PushPlus**: 微信推送
- **Bark**: iOS推送

#### API服务模块 (`api/server.py`)
- 提供HTTP API接口供外部调用

### 2.2 核心代码文件列表

```
zhihuishu_LOL/
├── main.py                     # CLI入口 (336行)
├── fucker.py                   # 核心业务逻辑 (104329字节)
├── start.py                    # 启动脚本 (5115字节)
├── logger.py                   # 日志模块
├── utils.py                    # 工具函数 (5756字节)
├── zd_utils.py                 # 智慧树工具 (3219字节)
├── sign.py                     # 签名算法
├── push.py                     # 推送通知
├── ObjDict.py                  # 对象字典 (4970字节)
├── api/
│   └── server.py               # API服务器
├── decrypt/                    # 解密模块
│   ├── decrypt_api.py
│   ├── decrypt_hike.py
│   └── main.py
└── web/                        # Web界面 (可能)
```

### 2.3 API接口定义

#### 智慧树平台API
```python
# 二维码登录
GET https://passport.zhihuishu.com/qrCodeLogin/getLoginQrImg
GET https://passport.zhihuishu.com/qrCodeLogin/getLoginQrInfo

# 账号密码登录
POST https://passport.zhihuishu.com/user/validateAccountAndPassword

# 课程列表
# getZhidaoList() - 知到课程
# getHikeList() - 校内课程
# getZhidaoAiList() - AI课程

# 视频学习
# fuckVideo() - 单个视频
# fuckCourse() - 整个课程
# fuckAiCourse() - AI课程
```

### 2.4 数据模型

#### Fucker (核心类)
```python
class Fucker:
    uuid: str                   # 用户UUID
    cookies: RequestsCookieJar  # 会话cookies
    proxies: dict               # 代理配置
    limit: int                  # 时间限制(分钟)
    speed: float                # 播放速度
    end_thre: float             # 完成阈值(0.91)
    context: ObjDict            # 上下文信息
    courses: ObjDict            # 课程信息
```

#### Config (配置)
```python
{
    "username": str,
    "password": str,
    "qrlogin": bool,            # 默认True
    "save_cookies": bool,
    "proxies": dict,
    "logLevel": str,
    "tree_view": bool,
    "progressbar_view": bool,
    "image_path": str,
    "pushplus": {
        "enable": bool,
        "token": str
    },
    "bark": {
        "enable": bool,
        "token": str
    },
    "ai": {
        "enabled": bool,
        "use_zhidao_ai": bool,
        "openai": {
            "api_base": str,
            "api_key": str,
            "model_name": str
        },
        "ppt_processing": {
            "provide_to_ai": bool,
            "moonShot": {
                "base_url": str,
                "api_key": str,
                "delete_after_convert": bool
            }
        },
        "use_stream": bool
    }
}
```

### 2.5 依赖关系

```
核心依赖:
- requests                      # HTTP请求
- openai                        # AI答题
- urllib3                       # URL处理

工具依赖:
- qrcode (可能)                 # 二维码生成
- pillow (可能)                 # 图片处理
```

---

## 三、chaoxing-signin 项目分析

### 3.1 项目状态
- **目录异常**: api目录不存在
- **需要确认**: 项目结构与预期不符
- **建议**: 重新检查项目完整性

---

## 四、可复用代码识别

### 4.1 通用模块

#### 1. 会话管理
```python
# 来源: chaoxing-fanya/api/base.py
class SessionManager:
    - 单例模式
    - 自动重试 (HTTPAdapter)
    - Cookies管理
    - 请求超时控制
```

#### 2. 速率限制
```python
# 来源: chaoxing-fanya/api/base.py
class RateLimiter:
    - 线程安全
    - 随机延迟
    - 固定间隔
```

#### 3. 日志系统
```python
# 来源: chaoxing-fanya/api/logger.py
# 来源: zhihuishu_LOL/logger.py
- loguru集成
- 多级别日志
- 文件输出
```

#### 4. 通知推送
```python
# 来源: chaoxing-fanya/api/notification.py
# 来源: zhihuishu_LOL/push.py
- 多渠道支持
- 统一接口
- 错误处理
```

#### 5. 配置管理
```python
# 来源: chaoxing-fanya/main.py
# 来源: zhihuishu_LOL/main.py
- INI/JSON配置
- 命令行参数
- 环境变量
```

### 4.2 平台特定模块

#### 超星平台 (chaoxing-fanya)
```python
- AES加密 (api/cipher.py)
- 字体解码 (api/font_decoder.py)
- 课程解码 (api/decode.py)
- 验证码处理 (api/captcha.py)
- OCR识别 (api/vision_ocr.py)
```

#### 智慧树平台 (zhihuishu_LOL)
```python
- 签名算法 (sign.py)
- 加密工具 (zd_utils.py)
- 解密模块 (decrypt/)
- 对象字典 (ObjDict.py)
```

### 4.3 前端组件 (chaoxing-fanya)
```javascript
- React组件库
- TailwindCSS样式
- 实时日志组件
- 进度条组件
- 课程选择器
```

---

## 五、技术栈对比

| 技术项 | chaoxing-fanya | zhihuishu_LOL | chaoxing-signin |
|--------|----------------|---------------|-----------------|
| **后端语言** | Python 3.x | Python 3.10+ | Python |
| **Web框架** | Flask 3.1.2 | 无 (纯CLI) | 未知 |
| **前端框架** | React + Vite | 无 | 未知 |
| **CSS框架** | TailwindCSS | 无 | 未知 |
| **HTTP库** | requests + httpx | requests | 未知 |
| **日志库** | loguru | loguru | 未知 |
| **并发** | ThreadPoolExecutor | threading | 未知 |
| **任务队列** | PriorityQueue | 无 | 未知 |
| **OCR** | PaddleOCR + AI | 无 | 未知 |
| **AI集成** | OpenAI兼容 | OpenAI兼容 | 未知 |
| **配置格式** | INI + JSON | JSON | 未知 |
| **打包方式** | 便携版 (bat) | 便携版 (py) | 未知 |

---

## 六、架构模式对比

### chaoxing-fanya
```
架构: 前后端分离 + CLI双模式
特点:
- Web可视化完整
- 实时进度追踪
- 多任务并发
- 回调机制完善
- 配置灵活

优势:
+ 用户体验好
+ 功能完整
+ 可扩展性强
+ 代码结构清晰

劣势:
- 复杂度较高
- 依赖较多
```

### zhihuishu_LOL
```
架构: CLI为主 + 可选API
特点:
- 命令行优先
- 配置驱动
- 简单直接
- 二维码登录

优势:
+ 轻量级
+ 易于自动化
+ 依赖少
+ 部署简单

劣势:
- 无可视化界面
- 实时反馈有限
```

---

## 七、融合架构建议

### 7.1 统一技术栈
```
后端: Python 3.10+ + FastAPI
前端: React 18 + TypeScript + TailwindCSS
数据库: PostgreSQL (用户/任务) + Redis (缓存/队列)
消息队列: Celery + Redis
API文档: OpenAPI 3.0
```

### 7.2 模块化设计
```
unified-signin-platform/
├── apps/
│   ├── api/                    # FastAPI后端
│   ├── web/                    # React前端
│   └── cli/                    # CLI工具
├── packages/
│   ├── core/                   # 核心业务逻辑
│   ├── platforms/              # 平台适配器
│   │   ├── chaoxing/
│   │   ├── zhihuishu/
│   │   └── base/
│   ├── services/               # 通用服务
│   │   ├── auth/
│   │   ├── notification/
│   │   ├── ocr/
│   │   └── ai/
│   └── shared/                 # 共享工具
│       ├── logger/
│       ├── config/
│       └── utils/
└── docs/
```

### 7.3 关键特性
1. **多平台支持**: 插件化平台适配器
2. **统一认证**: 抽象登录接口
3. **任务调度**: Celery分布式任务队列
4. **实时通信**: WebSocket推送
5. **配置中心**: 统一配置管理
6. **监控告警**: Prometheus + Grafana
7. **API网关**: 统一入口 + 鉴权
8. **微服务**: 可选的服务拆分

---

## 八、迁移路径

### 阶段1: 基础架构搭建
- [ ] 创建monorepo结构
- [ ] 搭建FastAPI后端框架
- [ ] 搭建React前端框架
- [ ] 配置数据库和Redis
- [ ] 实现核心抽象层

### 阶段2: 超星平台迁移
- [ ] 迁移chaoxing-fanya核心逻辑
- [ ] 适配新的架构模式
- [ ] 实现Web界面
- [ ] 测试验证

### 阶段3: 智慧树平台迁移
- [ ] 迁移zhihuishu_LOL核心逻辑
- [ ] 实现平台适配器
- [ ] 集成到统一界面
- [ ] 测试验证

### 阶段4: 功能增强
- [ ] 实现任务调度
- [ ] 添加监控告警
- [ ] 优化性能
- [ ] 完善文档

---

## 九、风险评估

### 技术风险
1. **反爬虫机制**: 平台可能加强检测
2. **API变更**: 接口可能随时失效
3. **验证码升级**: OCR可能失效
4. **并发限制**: 账号可能被封

### 合规风险
1. **使用协议**: 违反平台服务条款
2. **法律风险**: 可能涉及灰色地带
3. **数据安全**: 用户凭证保护

### 建议
- 仅供学习研究使用
- 添加免责声明
- 不提供商业服务
- 尊重平台规则

---

## 十、总结

### 项目特点
- **chaoxing-fanya**: 功能完整，Web体验好，代码质量高
- **zhihuishu_LOL**: 轻量简洁，CLI友好，易于自动化
- **chaoxing-signin**: 状态待确认

### 融合价值
1. 统一多平台学习工具
2. 提供一致的用户体验
3. 复用优秀的代码模块
4. 降低维护成本

### 下一步行动
1. 确认chaoxing-signin项目状态
2. 设计详细的融合架构
3. 制定开发计划
4. 开始基础架构搭建

---

**文档版本**: 1.0
**生成时间**: 2026-02-17
**分析者**: project-analyzer agent
