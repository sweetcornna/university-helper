# 学道 · 课程任务工作台

学道的前端，用 React、Vite 和 Tailwind CSS 写成。学习通签到、学习通泛雅和智慧树的课程任务都在这一个界面里操作。

## 技术栈

- React 18.2
- Vite 5.0
- TailwindCSS 3.3
- React Router 6.30
- Lucide React（图标）

## 项目结构

```
frontend/
├── src/
│   ├── pages/           # 页面组件
│   │   ├── Login.jsx           # 登录页
│   │   ├── Register.jsx        # 注册页
│   │   ├── Dashboard.jsx       # 用户仪表盘
│   │   ├── ChaoxingSignin.jsx  # 超星签到
│   │   ├── ChaoxingFanya.jsx   # 超星刷课
│   │   └── Zhihuishu.jsx       # 智慧树刷课
│   ├── components/      # 共享组件（含 UpdateNotice.jsx 更新提醒）
│   ├── utils/           # 工具函数
│   │   ├── api.js              # API 请求封装
│   │   └── auth.js             # JWT 认证工具
│   ├── assets/styles/
│   │   └── index.css           # 全局样式与颜色变量
│   ├── App.jsx          # 路由配置
│   └── main.jsx         # 入口文件
├── src-tauri/           # 桌面版外壳，见 src-tauri/README.md
├── package.json
├── vite.config.js
├── tailwind.config.js
└── postcss.config.js
```

## 功能

- 服务器版（server profile）用 JWT 登录，令牌只存在当前标签页的 `sessionStorage` 里。
- 桌面版（local profile，Tauri）不用学道账号，打开就进工作台。访问 `/login` 或 `/register` 会直接跳到 `/dashboard`；如果后端返回桌面版不需要登录的 409（`LocalProfileAuthUnavailable`），登录页和注册页也会切到桌面模式再跳转。
- 服务器出错（5xx）或连不上服务器时，界面会说清是哪种情况，并提示稍后重试、检查网络或请管理员查看服务端日志。
- 服务器版的管理员登录后，如果 GitHub 上有新版本，会弹出更新提醒：显示版本号、更新说明，以及可以直接复制的 bash 和 PowerShell 更新命令。可以选「稍后提醒」（24 小时内不再弹出，按 Esc 关闭也算）或「跳过这个版本」，选择记在浏览器的 localStorage 里。普通用户看不到这个提醒，桌面版也不显示。
- 导航、任务状态、Toast 通知和浅色/深色/跟随系统主题在各页面保持一致。
- 布局适配不同屏幕宽度，服务切换和页签都能用键盘操作。
- 三项服务按路由懒加载，地图和二维码相关的依赖打在单独的 chunk 里。

## 路由

- `/login`：登录页
- `/register`：注册页
- `/dashboard`：今日课程任务工作台
- `/chaoxing-signin`：学习通签到
- `/chaoxing-fanya`：学习通泛雅课程任务
- `/zhihuishu-panel`：智慧树课程任务

## 本地开发

```bash
npm install
npm run dev
```

然后打开 http://localhost:3000

## 构建

```bash
npm run build
npm run preview
```

## 接口

开发时前端通过 `/api` 代理访问后端，默认代理到 localhost:8000。前端直接用到的几个接口：

- `POST /api/v1/auth/login`：登录
- `POST /api/v1/auth/register`：注册
- `GET /api/v1/runtime`：判断当前是服务器版还是桌面版
- `GET /api/v1/system/update`：新版本信息，仅服务器版管理员可用，其他账号返回 403

## 设计

- 校园青 `#167C80`：主要操作和进行中的状态
- 墨蓝 `#172033`：正文和夜间底色
- 荧光橙 `#FF7A45`：下一步和需要注意的地方
- 讲义纸 `#F4F6F1`：日间背景
- 中文字体：`PingFang SC` / `Microsoft YaHei` / system-ui
- 整体风格参考课程表和夜里的自习桌，课表网格和今日任务轨道用来展示任务真实的进行状态

## 可访问性

- 文字对比度不低于 4.5:1
- 点击区域不小于 44x44px
- 可点击元素带 cursor-pointer
- 过渡动画 200ms
- 支持键盘导航
