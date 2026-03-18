# Tauri2 已启动实例自动化调试

这个项目用于在 Windows 环境连接“已经启动”的 Tauri2 桌面程序进行自动化调试，而不是只连 `localhost:1420` 的前端开发页。

## 目标

- 连接已启动的 Tauri2 应用调试端口
- 在页面中确认 `__TAURI__.invoke` 已可用
- 直接触发 Rust 命令调用，避免只测前端导致的 `invoke` 未注入错误
- 支持两种调用模式：
  - `playwright`：通过 Playwright 页面执行调用
  - `cdp`：通过 CDP `Runtime.evaluate` 执行调用

## 先决条件

- Python 3.13+
- 已安装依赖
- 已启动目标 Tauri2 程序，并开放远程调试端口（示例 `9222`）

## 安装

```bash
uv sync
```

```bash
uv run playwright install chromium
```

## 运行

默认命令：

```bash
uv run python main.py
```

常见参数：

```bash
uv run python main.py --endpoint http://127.0.0.1:9222 --mode playwright --command get_all_ideas --title-keyword GoldenIdea --url-keyword tauri://
```

使用 CDP 模式：

```bash
uv run python main.py --mode cdp --command get_all_ideas
```

## 参数说明

- `--endpoint`：CDP 入口，默认 `http://127.0.0.1:9222`
- `--mode`：`playwright` 或 `cdp`
- `--command`：要调用的 Rust 命令名
- `--title-keyword`：页面标题关键字，可重复传入
- `--url-keyword`：页面 URL 关键字，可重复传入
- `--timeout-ms`：等待页面与 Tauri API 的超时时间
- `--accept-command-not-found`：将“命令不存在”视为 Rust 通道连通（用于链路探测）

## 重要说明

- 应用名（例如 `GoldenIdea`）和 Rust 命令名是两回事。
- `--command` 需要填写 Rust 里 `#[tauri::command]` 注册的函数名，而不是应用窗口标题或进程名。
- 若命令名填成应用名，出现 `Command xxx not found` 代表桥已连通，只是命令名不正确。

## 结果判定

成功时会输出：

- 匹配到的页面信息
- `invoke` 可用位置
- 命令返回值（JSON）

失败时会给出明确退出原因：

- 连接失败
- 未匹配到目标页面
- 找到页面但 `__TAURI__.invoke` 未就绪
- 命令调用异常

## 排障建议

- 若看到 `页面已找到但 __TAURI__.invoke 未就绪`，先确认连接的是 Tauri 进程而不是普通浏览器页：

```bash
Invoke-RestMethod http://127.0.0.1:9222/json/version
Invoke-RestMethod http://127.0.0.1:9222/json/list
```

- 若你使用 Tauri v2 且未开启 `withGlobalTauri`，全局 `window.__TAURI__` 可能不存在，这是正常行为；本脚本已兼容 `__TAURI_INTERNALS__.invoke`。
- 若必须在前端代码里继续使用 `window.__TAURI__` 风格调用，需要在 Tauri 配置中启用 `app.withGlobalTauri`，否则请改为 `@tauri-apps/api/core` 的 `invoke`。
- 确认启动的是桌面应用实例并开启远程调试参数，不要只连接 `localhost:1420` 的纯前端页面。

## 连通测试脚本

使用下面命令一键验证 Playwright 与 CDP 两种模式都可连接到已启动 Tauri 且 Rust 通道可达：

```bash
uv run python test_tauri_bridge.py --endpoint http://127.0.0.1:9222 --probe-command GoldenIdea
```

说明：

- 这里 `GoldenIdea` 故意作为探测命令，若返回 `Command GoldenIdea not found` 也会判定为“Rust 通道已连通”。
- 你可再替换为真实命令名做功能级验证。

## 无头端到端渲染测试

这个测试用于验证你描述的目标：

- 自动连接已启动桌面应用前端
- 检查前端没有 `invoke` 未定义类错误
- 获取首页内容并输出可点击关键内容
- 逐步点击可交互元素，点击后检查错误并返回首页，循环执行
- 断言页面已渲染出数据
- 输出累计 console/page 错误并给出最终结论

命令示例：

```bash
uv run python test_desktop_e2e.py --endpoint http://127.0.0.1:9222 --expect-selector ".idea-item" --min-count 1 --expect-text "Idea" --max-click-targets 30
```

若你希望脚本先拉起应用再测试：

```bash
uv run python test_desktop_e2e.py --app-cmd "path\\to\\GoldenIdea.exe" --app-cwd "path\\to" --expect-selector ".idea-item" --min-count 1 --max-click-targets 30
```

说明：

- `--expect-selector` 与 `--expect-text` 需要按你的真实页面结构调整。
- `--home-selector` 可指定“返回首页”按钮，无法回退时会使用该选择器。
- `--max-click-targets` 控制自动点击上限，建议先小后大逐步放开。
