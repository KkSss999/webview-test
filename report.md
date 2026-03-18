# 跨平台 (Windows/macOS) Tauri2 桌面应用无头自动化测试技术报告

## 1. 背景与目标

在开发 Tauri2 桌面应用时，传统的 `localhost:1420` 前端开发服务器存在一个根本性问题：**该端口仅提供前端页面渲染，无法访问 Rust 侧功能**。这会导致典型的前端 invoke 报错。为了进行真实的端到端测试，必须连接到已启动的、完整的桌面应用实例。

然而，在跨平台场景下，遇到了极大的技术壁垒：
1. **Windows** 底层是基于 Chromium 的 WebView2，天然支持强大的 CDP (Chrome DevTools Protocol)。
2. **macOS** 底层是 Apple 的 WKWebView，完全不支持 CDP，只支持通过特定插件（如 `tauri-plugin-webdriver`）暴露有限的 W3C WebDriver 协议。

本报告旨在提供一种**纯 Playwright 驱动**的跨平台统一测试方案，它不仅完美桥接了两种底层协议，还通过深度定制突破了 macOS 原生 WebDriver 的种种限制。

## 2. 核心技术方案

### 2.1 架构设计

| 平台 | 底层引擎 | 通信协议 | 客户端实现方式 |
|------|----------|----------|----------------|
| Windows | WebView2 (Chromium) | CDP (端口 9222) | Playwright 原生 `connect_over_cdp` |
| macOS | WKWebView (WebKit) | WebDriver (端口 4445) | Playwright HTTP `APIRequestContext` 模拟 |

**方案亮点**：完全移除了沉重的 Selenium 依赖。对于 macOS 平台，直接利用 Playwright 强大的异步 HTTP 客户端功能，手工封装了一个微型、轻量级的 WebDriver 客户端，从而在代码层面统一了测试工具栈。

### 2.2 macOS (WebDriver) 模式的高阶突破

原生的 WebDriver 协议在测试现代前端框架（如 React/Vue）时存在两个致命缺陷，本方案通过“**JS 代码级注入**”完美解决：

#### 突破 1：全局 Console 错误监听
**痛点**：W3C WebDriver 标准对 WKWebView 的日志捕获支持极差，无法像 CDP 那样直接监听 `console.error`。
**解法**：在确认 Tauri 就绪后，通过 `execute_script` 向页面注入“内鬼”代码，劫持全局的 `console.error`、`window.onerror` 和 `unhandledrejection`，将错误存入全局数组 `window.__E2E_ERRORS__`。Python 脚本在每次点击后实时读取该数组，实现了等价于 CDP 的报错拦截能力。

#### 突破 2：防 "Stale Element Reference" (陈旧元素引用)
**痛点**：WebDriver 默认返回静态绑定的内存元素 ID，一旦前端因点击发生重渲染，旧 ID 立刻失效并抛出 `Stale Element` 异常。
**解法**：废弃直接收集元素 ID 的做法。注入一段高级 JS 算法 (`cssPath`)，为页面上每个可点击元素逆向推导出一根**绝对唯一的 CSS 选择器路径**。在执行点击时，脚本采用**延迟求值 (Lazy Evaluation)** 策略，拿着这条路径去实时查询最新的 DOM 节点并点击。这完全模仿了 Playwright 官方 Locator 的黑科技。

## 3. 测试流程设计

```
1. 识别并连接协议端点 (CDP 或 WebDriver)
         ↓
2. 查找目标页面并等待加载完成
         ↓
3. 检测 Tauri invoke 是否就绪（兼容 v2 的三路径探测）
         ↓
4. (仅 Mac) 注入 JS 错误拦截器与 CSS 寻址算法
         ↓
5. 渲染断言（确认关键选择器数量满足要求）
         ↓
6. 提取元素的精确 CSS 路径并放入点击队列
         ↓
7. 遍历点击（实时寻址防 Stale Element）
         ↓
8. 提取拦截到的 console_errors 校验并尝试返回首页
         ↓
9. 汇总所有错误，输出 JSON 测试结论
```

## 4. 实测验证结果

### 4.1 Windows (CDP)
- 成功识别页面并获取 8 个业务按钮。
- Playwright 原生 Locator 点击顺畅，无 Stale Element 问题。
- 原生 Console 监听准确捕获所有前端异常。

### 4.2 macOS (WebDriver)
- **环境**：需在 Tauri 的 `main.rs` 的 debug 构建中挂载 `tauri_plugin_webdriver` 插件。
- 成功建立 HTTP Session 握手。
- JS 拦截器成功拦截了 Vue 路由级别的 `unhandledrejection` 报错。
- 基于精确 CSS 路径的实时寻址点击，完美抵抗了 Vue 组件频繁销毁重建带来的 `Stale Element Reference` 崩溃。
- 测试流程顺畅跑完，最终输出结构化测试报告。

## 5. 总结

本方案不仅成功绕过了 `localhost:1420` 无法测试 Rust 侧代码的限制，更在行业内极少有人涉足的 **“Mac 端 Tauri WKWebView 自动化”** 领域给出了教科书级别的解法：
- 抛弃 Selenium，用一套 Playwright 搞定双协议。
- 利用 JS 注入降维打击了 WebDriver 协议的底层缺陷（日志盲区与静态 ID）。
- 生成了极度稳定、抗重渲染的 E2E 循环点击基建。