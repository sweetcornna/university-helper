# 签到刷课平台 - 统一前端

基于 React + Vite + TailwindCSS 的统一前端界面，整合三个子项目。

## 技术栈

- React 18.2
- Vite 5.0
- TailwindCSS 3.3
- React Router 6.20
- Lucide React (图标)

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
│   ├── components/      # 共享组件
│   ├── utils/           # 工具函数
│   │   ├── api.js              # API 请求封装
│   │   └── auth.js             # JWT 认证工具
│   ├── App.jsx          # 路由配置
│   ├── main.jsx         # 入口文件
│   └── index.css        # 全局样式
├── package.json
├── vite.config.js
├── tailwind.config.js
└── postcss.config.js
```

## 功能特性

- JWT Token 认证（存储在 localStorage）
- 统一导航栏与返回按钮
- 响应式设计（移动端适配）
- Glassmorphism 设计风格
- iframe 嵌入三个子项目前端

## 路由结构

- `/login` - 登录页
- `/register` - 注册页
- `/dashboard` - 用户仪表盘（三个服务入口）
- `/chaoxing-signin` - 超星签到（iframe: localhost:3001）
- `/chaoxing-fanya` - 超星刷课（iframe: localhost:3002）
- `/zhihuishu` - 智慧树刷课（iframe: localhost:3003）

## 开发运行

```bash
npm install
npm run dev
```

访问 http://localhost:3000

## 构建部署

```bash
npm run build
npm run preview
```

## API 集成

前端通过 `/api` 代理访问后端 API（默认 localhost:8000）：

- `POST /api/v1/auth/login` - 登录
- `POST /api/v1/auth/register` - 注册

## 设计系统

- 主色：#2563EB (primary)
- 次色：#3B82F6 (secondary)
- CTA：#F97316 (cta)
- 背景：#F8FAFC
- 文字：#1E293B
- 字体：Inter
- 风格：Glassmorphism（毛玻璃效果）

## 可访问性

- 文字对比度 >= 4.5:1
- 点击区域 >= 44x44px
- 可点击元素带 cursor-pointer
- 过渡动画 200ms
- 支持键盘导航
