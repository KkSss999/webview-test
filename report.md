# Windows Tauri2 桌面应用无头自动化测试技术报告

## 1. 背景与目标

在 Windows 平台上使用 Tauri2 开发桌面应用时，传统的 `localhost:1420` 前端开发服务器存在一个根本性问题：**该端口仅提供前端页面渲染，无法访问 Rust 侧功能**。这会导致以下典型错误：

```
[API Error] unknown: TypeError: Cannot read properties of undefined (reading 'invoke')
    at tauriApi.js:149:29
```

该错误的根本原因是 `window.__TAURI__` 未被注入——因为 1420 端口不经过 Tauri 运行时。本报告旨在提供一种通过 **CDP (Chrome DevTools Protocol)** 连接已启动的 Tauri2 桌面应用进行完整自动化测试的方案。

## 2. 核心技术方案

### 2.1 连接方式

通过 WebView2 的远程调试端口 (`--remote-debugging-port`) 建立 CDP 连接，而非传统的 `localhost:1420`。这使得测试脚本可以直接操作已启动的完整桌面应用实例，Rust 侧功能正常可用。

### 2.2 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.13+ | 测试脚本运行环境 |
| Playwright | CDP 连接与自动化操作 |
| WebView2 (Windows) | Tauri2 底层渲染引擎 |
| CDP (DevTools Protocol) | 浏览器/应用远程控制协议 |

### 2.3 Tauri v2 兼容性处理

Tauri v2 在未启用 `withGlobalTauri` 配置时，`window.__TAURI__` 全局对象可能不存在。测试脚本需兼容三种 invoke 访问路径：

| 位置 | 检测方式 |
|------|----------|
| `window.__TAURI__.invoke` | root 模式 |
| `window.__TAURI__.core.invoke` | core 模式 |
| `window.__TAURI_INTERNALS__.invoke` | internals 模式（v2 常见）|

## 3. 测试流程设计

### 3.1 完整自动化测试流程

```
1. 启动/连接 CDP 端点
         ↓
2. 查找目标页面（按标题/URL 关键字）
         ↓
3. 等待页面加载完成
         ↓
4. 检测 Tauri invoke 是否就绪（三路径探测）
         ↓
5. 渲染断言（选择器数量、文本内容）
         ↓
6. 收集可点击元素并遍历点击
         ↓
7. 每一步点击后检查控制台错误
         ↓
8. 尝试返回首页，继续下一步
         ↓
9. 汇总错误，输出测试结论
```

### 3.2 关键检测点

- **CDP 连接成功**：确认已连接到真实桌面应用而非纯前端
- **Tauri invoke 就绪**：验证 Rust 侧通道可用
- **渲染成功**：页面元素正常渲染，数据来自 SQLite
- **无控制台错误**：拦截 `[API Error]` 和 `invoke undefined` 类错误
- **点击循环完成**：所有可交互元素可点击且无异常

## 4. 核心代码实现

### 4.1 Tauri invoke 就绪检测

```python
def wait_tauri_ready(page: Page, timeout_ms: int) -> bool:
    location = page.evaluate(
        "() => { "
        "  const api = globalThis.__TAURI__; "
        "  const internals = globalThis.__TAURI_INTERNALS__; "
        "  if (api && typeof api.invoke === 'function') return 'root'; "
        "  if (api && api.core && typeof api.core.invoke === 'function') return 'core'; "
        "  if (internals && typeof internals.invoke === 'function') return 'internals'; "
        "  return 'missing'; "
        "}"
    )
    return location in {"root", "core", "internals"}
```

### 4.2 可点击元素自动收集

```python
def collect_click_targets(page, limit: int):
    return page.evaluate(
        """({ limit }) => {
          const selector = 'button, a, [role="button"], input[type="button"]';
          const all = Array.from(document.querySelectorAll(selector));
          // 过滤不可见元素，计算 CSS 路径，返回 {selector, tag, text}
        }"""
    )
```

### 4.3 循环点击与错误检测

```python
for item in targets:
    page.click(item["selector"])
    page.wait_for_timeout(click_wait_ms)
    # 检查新增 console/page 错误
    if new_errors > 0:
        report["ok"] = False
    return_home(page, home_url, home_selector)
```

## 5. 实测验证结果

### 5.1 测试环境

- **操作系统**：Windows
- **应用**：GoldenIdea (Tauri2 + Vue 3)
- **CDP 端口**：9222
- **Python**：3.13+

### 5.2 测试命令

```bash
python main.py --endpoint http://127.0.0.1:9222 --expect-selector body --min-count 1 --max-click-targets 8
```

### 5.3 输出结果

```
已连接，当前上下文数量: 1
- 页面: title='Tauri + Vue 3 App' url='http://localhost:1420/idea'
命中目标页面: title='Tauri + Vue 3 App'
Tauri invoke 已就绪，位置: internals

可点击目标列表:
1. button | (no-text) | #app > div > aside > div:nth-of-type(1) > button
2. a | IDEA | #app > div > aside > div:nth-of-type(3) > nav > a:nth-of-type(1)
3. a | TODO | #app > div > aside > div:nth-of-type(3) > nav > a:nth-of-type(2)
4. a | 仪表盘 | #app > div > aside > div:nth-of-type(3) > nav > a:nth-of-type(3)
5. a | 设置 | #app > div > aside > div:nth-of-type(3) > nav > a:nth-of-type(4)
6. a | 同步 | #app > div > aside > div:nth-of-type(3) > nav > a:nth-of-type(5)
7. button | 新建想法 | main > div > div > div:nth-of-type(1) > div > button
8. button | (no-text) | div:nth-of-type(2) > div > div > div:nth-of-type(1) > div:nth-of-type(2) > button

{"selector": "body", "count": 1, "click_steps": 8, "failed_steps": 0}
累计控制台错误:
{"console_errors": [], "page_errors": []}
✅ 页面渲染成功，点击循环完成，未发现禁用报错
```

### 5.4 验证结论

| 验证项 | 状态 |
|--------|------|
| CDP 连接已启动 Tauri2 | ✅ 通过 |
| Playwright 方式连接 | ✅ 通过 |
| 前端页面渲染 | ✅ 通过 |
| Rust 侧通道可用 (internals) | ✅ 通过 |
| 自动点击遍历 (8 个目标) | ✅ 通过 |
| 控制台错误检测 | ✅ 无错误 |
| 禁用模式拦截 | ✅ 未命中 |

## 6. 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--endpoint` | CDP 调试端点 | `http://127.0.0.1:9222` |
| `--title-keyword` | 页面标题关键字 | `GoldenIdea` |
| `--url-keyword` | URL 关键字 | `tauri://`, `localhost:1420` |
| `--expect-selector` | 渲染断言选择器 | `body` |
| `--min-count` | 最小元素数量 | 1 |
| `--expect-text` | 页面必须包含的文本 | [] |
| `--max-click-targets` | 最大点击元素数量 | 25 |
| `--click-wait-ms` | 点击后等待毫秒数 | 700 |
| `--forbid-console-pattern` | 禁用的错误模式 | `[API Error]`, `invoke undefined` |
| `--app-cmd` | 启动应用的命令行 | - |
| `--app-cwd` | 应用工作目录 | - |
| `--app-start-wait-ms` | 启动后等待毫秒数 | 8000 |

## 7. 常见问题

### Q1: 连接失败 `ECONNREFUSED`

**原因**：Tauri 应用未开启远程调试端口

**解决**：启动应用时添加参数
```bash
set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222
your-tauri-app.exe
```

### Q2: 页面已找到但 `__TAURI__.invoke` 未就绪

**原因**：使用的是 `localhost:1420` 而非真实桌面应用

**解决**：
1. 确保通过 CDP 连接已启动的桌面应用
2. Tauri v2 未开启 `withGlobalTauri` 时全局 API 不可见属正常，脚本已兼容 `__TAURI_INTERNALS__`

### Q3: 报错 `Command xxx not found`

**原因**：命令名为 Rust `#[tauri::command]` 注册名，非应用名

**说明**：本测试方案不直接调用 Rust 命令，仅验证页面行为和错误

## 8. 总结

本方案成功实现了以下目标：

1. **绕过 1420 端口限制**：通过 CDP 连接真实桌面应用实例
2. **Rust 侧功能可用**：`__TAURI_INTERNALS__.invoke` 确保通道可达
3. **端到端行为测试**：不依赖特定 Rust 命令，以页面渲染和交互作为验证依据
4. **自动化错误检测**：自动遍历点击元素并拦截控制台报错
5. **可集成至 LLM 测试流程**：输出结构化 JSON 结果，易于程序解析

该方案已在 Windows + Tauri2 + Vue 3 项目中验证通过，可作为类似技术栈的自动化测试参考。