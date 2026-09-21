# University Helper iOS 应用实施文档

## 目标

将现有 University Helper 做成原生 SwiftUI iOS 客户端，并复用仓库内已经稳定运行的 FastAPI 服务端。最终产物为可通过自签名安装的 `UniversityHelper.ipa`，同时保留可重复构建脚本。

## 已确认的现有系统

- 后端：FastAPI，API 前缀为 `/api/v1`，认证使用 Bearer JWT。
- 现有前端：React + Vite + Tailwind；桌面端另有 Tauri 壳。
- 主要能力：账号注册/登录、超星签到、超星泛雅刷课、智慧树/知到登录与刷课任务、任务状态与日志。
- 服务端路由分组：
  - `/auth/*`：登录、注册、验证码、密码重置、刷课令牌。
  - `/chaoxing/*`：学习通登录、课程、签到任务、签到历史、位置/二维码相关能力。
  - `/course/*`：泛雅课程任务、任务控制、智慧树登录/课程/进度/任务。

## iOS 产品方案

采用原生 SwiftUI，不把现有网页简单套进 WebView：

1. 启动时读取 Keychain 中的 JWT 与服务端地址。
2. 未登录显示登录、注册、忘记密码流程；服务端地址可在设置中修改。
3. 登录后使用 `TabView` 提供：首页、学习通签到、泛雅刷课、智慧树、设置。
4. 所有请求通过一个 `APIClient` 统一处理 Bearer 认证、超时、错误解析和 401 清理会话。
5. 长任务使用轮询刷新状态，支持暂停、继续、停止和任务历史查看。
6. QR 登录结果用系统 Core Image 生成二维码，照片/位置等系统能力只在对应流程实际使用时申请权限。
7. 凭据和 JWT 只写入 Keychain，不写入 UserDefaults；服务端地址、界面偏好等非敏感配置写入 UserDefaults。

## 页面与功能映射

| iOS 页面 | 对应现有 Web 页面 | 首版覆盖 |
|---|---|---|
| 登录/注册/重置密码 | `Login.jsx`、`Register.jsx`、`ForgotPassword.jsx` | 完整认证、错误提示、会话恢复 |
| 首页 | `Dashboard.jsx` | 三个服务入口、当前服务状态 |
| 学习通签到 | `ChaoxingSignin.jsx` | 账号会话、课程/班级、签到任务、历史、任务控制 |
| 泛雅刷课 | `ChaoxingFanya.jsx` | 登录、课程选择、章节、配置、启动任务、日志/轮询 |
| 智慧树 | `Zhihuishu.jsx` | QR/密码登录、课程、视频进度、启动/暂停/继续/取消 |
| 设置 | 原 Web 壳层能力 | 服务端地址、主题、退出登录、版本信息 |

## 视觉与图标

- 采用深蓝/青绿色为主色，延续现有产品的“夜间学习、进度推进”气质。
- 应用图标使用生成式图像作为创意源，再处理成 iOS AppIcon 所需的多尺寸 PNG。
- 图标不放小字号文字，保证主屏幕缩放后仍清晰；资源放在 `ios/UniversityHelper/Assets.xcassets`。

## 工程与打包

- 工程路径：`ios/UniversityHelper.xcodeproj`。
- Bundle ID 默认：`com.universityhelper.ios`，可通过构建脚本环境变量覆盖。
- 最低系统版本：iOS 16.0。
- 构建脚本：`ios/scripts/build_ipa.sh`。
- 产物目录：`ios/build/`，最终文件：`ios/build/UniversityHelper.ipa`。
- 构建使用本机 `/Users/nassa/Applications/Xcode-16.2.app`；脚本通过 `DEVELOPER_DIR` 固定 Xcode，避免受全局 Command Line Tools 选择影响。
- 当前这份 Xcode 没有注册可用的 iOS 设备/模拟器 runtime，因此脚本在生成 `.xcodeproj` 后使用同一份 iPhoneOS SDK 直接编译 SwiftUI 源码，再组装标准 `.app`/`Payload` IPA；安装完整 Xcode platform 后可改回标准 `xcodebuild archive`。

## 签名前置条件

构建脚本支持以下环境变量：

- `DEVELOPMENT_TEAM`：Apple Development Team ID（如果证书需要）。
- `CODE_SIGN_IDENTITY`：签名身份名称。
- `PROVISIONING_PROFILE_SPECIFIER`：Provisioning Profile 名称或 UUID。
- `EXPORT_OPTIONS_PLIST`：自定义导出配置；不提供时脚本生成 ad-hoc 配置。

当前检查到完整 Xcode 已安装，但当前登录钥匙串没有有效代码签名身份，项目目录和常用桌面/文档目录也没有发现 `.p12` 或 `.mobileprovision`。工程和构建链会先完成；真正导出可安装 IPA 仍需要把自签名证书、私钥和对应 provisioning profile 导入当前用户钥匙串，或在构建时显式提供可用签名参数。

## 验收标准

- `xcodebuild -list` 能识别 iOS 工程和 scheme。
- 模拟器 Debug 构建通过，Swift 编译无警告级错误。
- Release Archive / Export 流程能生成 `.app` 和 `.ipa`。
- IPA 内含 `Payload/*.app`、Info.plist、AppIcon，并通过 `codesign --verify` 与 `unzip -t` 检查。
- 文档明确记录服务端地址配置、签名方式、构建命令和当前环境限制。

## 实施顺序

1. 写入本实施文档并锁定接口/安全边界。
2. 生成图标、建立 SwiftUI 工程和资源目录。
3. 实现 API、Keychain 会话、认证和主导航。
4. 实现三类学习服务页面与长任务轮询。
5. 用 XCTest/本地编译检查基础行为，调用 `xcodebuild` 构建 Archive。
6. 导出并验证 IPA；若签名身份缺失，保留未签名构建日志和可直接重试的命令，不伪造“已签名完成”。

## 当前构建结果

已生成并验证：`ios/build/UniversityHelper.ipa`。它包含 arm64 Mach-O、Info.plist、AppIcon PNG 和 `_CodeSignature`，`unzip -t` 与 `codesign --verify --deep --strict` 均通过；因为当前钥匙串为 0 个有效身份，签名类型为 ad-hoc，不能作为正式开发证书签名包直接安装到受保护的 iPhone。

有证书后可重试：

```bash
cd ios
CODE_SIGN_IDENTITY="你的签名身份名称" \
PROVISIONING_PROFILE="/绝对路径/你的.mobileprovision" \
PRODUCT_BUNDLE_IDENTIFIER="你的 Bundle ID" \
./scripts/build_ipa.sh
```
