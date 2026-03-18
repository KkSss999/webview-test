# Windows Tauri2 桌面应用无头 E2E 成功案例

本项目用于在 Windows 环境通过 CDP 控制“已启动”的 Tauri2 桌面应用，完成无头端到端测试。  
测试重点是完整用户行为，而不是直接调用 Rust command。

## 测试目标

- 连接已启动的 Tauri2 桌面应用
- 检查首页可正常渲染
- 检查控制台无关键报错（尤其是 invoke 未注入类错误）
- 自动提取可点击元素并逐步点击
- 每一步点击后检查错误并返回首页继续下一步
- 最终输出累计 `console_errors/page_errors`

## 当前脚本

- 单一入口：`main.py`
- 不依赖 `test_tauri_bridge.py` / `test_desktop_e2e.py`
- 直接运行即可完成完整 E2E 循环

## 环境要求

- Windows
- Python 3.13+
- `uv`
- Playwright Chromium
- 已启动 Tauri2 桌面应用并开放 CDP 端口（默认 `9222`）

## 安装

```bash
uv sync
```

```bash
uv run playwright install chromium
```

## 快速开始

连接已启动应用执行无头 E2E：

```bash
uv run python main.py --endpoint http://127.0.0.1:9222 --expect-selector body --min-count 1 --max-click-targets 8
```

由脚本启动应用后再测试：

```bash
uv run python main.py --app-cmd "path\\to\\GoldenIdea.exe" --app-cwd "path\\to" --expect-selector body --min-count 1
```

## 参数说明

- `--endpoint`：CDP 地址，默认 `http://127.0.0.1:9222`
- `--title-keyword`：目标页面标题关键字，可重复
- `--url-keyword`：目标页面 URL 关键字，可重复
- `--timeout-ms`：整体等待超时
- `--expect-selector`：渲染成功的关键选择器
- `--min-count`：关键选择器最小数量
- `--expect-text`：页面必须出现的文本，可重复
- `--home-selector`：回首页按钮选择器（回退失败时兜底）
- `--max-click-targets`：自动点击最大目标数
- `--click-wait-ms`：每次点击后等待时长
- `--forbid-console-pattern`：禁用错误模式，可重复
- `--app-cmd`：可选，测试前启动应用命令
- `--app-cwd`：可选，应用启动目录
- `--app-start-wait-ms`：应用启动后等待时长

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
- `console_errors` 与 `page_errors` 未命中禁用模式

末尾输出示例：

```json
{"selector":"body","count":1,"click_steps":8,"failed_steps":0}
{"console_errors":[],"page_errors":[]}
```

## 已验证结果（Windows）

- 已成功识别并输出导航与业务按钮（IDEA/TODO/仪表盘/设置/同步/新建想法等）
- 自动点击循环完成
- 累计报错为空
- 最终输出：`页面渲染成功，点击循环完成，未发现禁用报错`

## 排障

CDP 不可达时先检查：

```bash
Invoke-RestMethod http://127.0.0.1:9222/json/version
Invoke-RestMethod http://127.0.0.1:9222/json/list
```

若只连接到 `localhost:1420` 前端页，可能出现 invoke 未注入报错。应确保测试连接的是已启动桌面应用对应的 WebView2 目标页。
