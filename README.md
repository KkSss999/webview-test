# 跨平台 (Windows/macOS) Tauri2 桌面应用无头 E2E 测试方案

本项目用于在 Windows 和 macOS 环境下，对“已启动”的 Tauri2 桌面应用进行端到端无头自动化测试。  
测试重点是完整用户行为，而不是直接调用 Rust command。

本项目的最大特色是**完全摒弃 Selenium，纯基于 Playwright 驱动**，同时完美兼容底层的 CDP 协议（Windows）与 W3C WebDriver 协议（macOS）。

## 测试目标

- 连接已启动的 Tauri2 桌面应用
- 检查首页可正常渲染
- 检查控制台无关键报错（尤其是 invoke 未注入类错误）
- 自动提取可点击元素并逐步点击（自带防 Stale Element 重渲染抵抗机制）
- 每一步点击后检查错误并返回首页继续下一步
- 最终输出累计 `console_errors/page_errors`

## 架构特性

- 单一入口：`main.py`
- **零 Selenium 依赖**：使用 Playwright 原生 CDP 控制 Windows，使用 Playwright HTTP Client 模拟 WebDriver 控制 macOS。
- **高阶 WebDriver 能力**：通过深度 JS 注入，在 macOS 实现了原本 WebDriver 不支持的 **全局 Console 错误监听** 与 **实时元素寻址 (防 Stale Element)**。

## 环境要求

- Python 3.13+
- `uv` 包管理器
- **Playwright** (`uv pip install playwright`)
- 已启动的 Tauri2 桌面应用

### 平台特定机制

| 平台 | 协议 | 默认端口 | 底层连接方式 |
|------|------|----------|------|
| Windows | CDP (WebView2) | 9222 | Playwright `connect_over_cdp` |
| macOS | WebDriver (tauri-plugin-webdriver) | 4445 | Playwright `APIRequestContext` 模拟 |

## 安装

```bash
# 安装依赖
uv sync

# 安装 Playwright 浏览器（仅 CDP 模式需要）
uv run playwright install chromium
```

## 快速开始

连接已启动应用执行无头 E2E：

```bash
# macOS WebDriver 模式 (依赖应用内开启 tauri-plugin-webdriver)
uv run python main.py --driver webdriver --endpoint http://127.0.0.1:4445 --expect-selector body --min-count 1 --max-click-targets 8

# Windows CDP 模式 (依赖 WebView2 开启远程调试)
uv run python main.py --driver cdp --endpoint http://127.0.0.1:9222 --expect-selector body --min-count 1 --max-click-targets 8

# 自动检测 (按端点存活状态自动选择协议)
uv run python main.py --driver auto
```

## 默认错误拦截

默认会拦截以下错误并判定失败：

- `[API Error]`
- `Cannot read properties of undefined (reading 'invoke')`

你可以追加更多错误模式：

```bash
uv run python main.py --forbid-console-pattern "TypeError" --forbid-console-pattern "Unhandled Promise Rejection"
```

## 成功判定

满足以下条件即判定通过：

- 成功连接目标页面
- `Tauri invoke` 状态就绪（兼容 `__TAURI__` 与 `__TAURI_INTERNALS__`）
- 首页渲染断言通过
- 点击循环执行完成且无失败步骤
- 控制台未命中禁用模式

## 排障

### Windows (CDP 模式)

CDP 不可达时先检查：
```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version
```
若只连接到 `localhost:1420` 前端页，可能出现 invoke 未注入报错。应确保连接的是 Tauri 启动的真实 App。

### macOS (WebDriver 模式)

确保 Tauri 应用在 debug 构建中已配置 `tauri-plugin-webdriver`：
```bash
# 检查 WebDriver 是否运行
curl http://127.0.0.1:4445/status
# 应返回 ready 状态
```
如果在点击时出现异常，多半是目标元素不可见或前端发生阻塞，脚本内部已内置针对 React/Vue 重渲染的 Stale Element 抵抗机制。
