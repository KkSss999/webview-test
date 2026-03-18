#!/usr/bin/env python3
"""
WebView Test Script - 支持 CDP 和 WebDriver 两种连接方式

使用方式:
    # macOS WebDriver (tauri-plugin-webdriver)
    uv run python main.py --driver webdriver --endpoint http://127.0.0.1:4445

    # Windows CDP (WebView2)
    uv run python main.py --driver cdp --endpoint http://127.0.0.1:9222

    # 自动检测
    uv run python main.py --driver auto
"""
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Iterable, List, Any, Optional

# 全部使用 Playwright
from playwright.sync_api import sync_playwright, APIRequestContext


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--driver",
        default="auto",
        choices=["auto", "cdp", "webdriver"],
        help="连接类型: cdp (Windows WebView2), webdriver (macOS tauri-plugin-webdriver), auto (自动检测)",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:4445")
    parser.add_argument("--cdp-endpoint", default="http://127.0.0.1:9222", help="CDP 端点 (Windows)")
    parser.add_argument("--webdriver-endpoint", default="http://127.0.0.1:4445", help="WebDriver 端点 (macOS)")
    parser.add_argument("--title-keyword", action="append", dest="title_keywords", default=["GoldenIdea"])
    parser.add_argument("--url-keyword", action="append", dest="url_keywords", default=["tauri://", "localhost:1420"])
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--expect-selector", default="body")
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--expect-text", action="append", dest="expect_texts", default=[])
    parser.add_argument("--home-selector")
    parser.add_argument("--max-click-targets", type=int, default=25)
    parser.add_argument("--click-wait-ms", type=int, default=700)
    parser.add_argument(
        "--forbid-console-pattern",
        action="append",
        dest="forbid_patterns",
        default=["[API Error]", "Cannot read properties of undefined (reading 'invoke')"],
    )
    parser.add_argument("--app-cmd")
    parser.add_argument("--app-cwd")
    parser.add_argument("--app-start-wait-ms", type=int, default=8000)
    return parser.parse_args()


def detect_driver_type(endpoint: str) -> str:
    """自动检测驱动类型"""
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/status", timeout=2):
            return "webdriver"
    except urllib.error.URLError:
        pass

    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=2):
            return "cdp"
    except urllib.error.URLError:
        pass

    return "webdriver"


def wait_endpoint(endpoint: str, timeout_ms: int, driver_type: str = "webdriver") -> bool:
    """等待端点就绪"""
    deadline = time.time() + timeout_ms / 1000
    
    if driver_type == "cdp":
        target = endpoint.rstrip("/") + "/json/version"
    else:
        target = endpoint.rstrip("/") + "/status"
    
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(target, timeout=2):
                return True
        except urllib.error.URLError:
            time.sleep(0.5)
    return False


def maybe_launch_app(args: argparse.Namespace):
    if not args.app_cmd:
        return None
    env = dict(os.environ)
    if args.driver == "cdp" or (args.driver == "auto" and args.endpoint == args.cdp_endpoint):
        if "--remote-debugging-port=" not in env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", ""):
            env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9222"
    process = subprocess.Popen(args.app_cmd, cwd=args.app_cwd or None, env=env, shell=True)
    time.sleep(args.app_start_wait_ms / 1000)
    return process


# ============== CDP (Playwright 原生) 实现 ==============

def pick_target_page_cdp(playwright, endpoint: str, title_keywords: list, url_keywords: list, timeout_ms: int):
    browser = playwright.chromium.connect_over_cdp(endpoint)
    normalized_title_keywords = [keyword.lower() for keyword in title_keywords if keyword]
    normalized_url_keywords = [keyword.lower() for keyword in url_keywords if keyword]
    print(f"已连接，当前上下文数量: {len(browser.contexts)}")
    
    for context in browser.contexts:
        for page in context.pages:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 3000))
            except Exception:
                pass
            try:
                title = page.title()
            except Exception:
                title = ""
            url = page.url or ""
            print(f"- 页面: title='{title}' url='{url}'")
            title_match = any(keyword in title.lower() for keyword in normalized_title_keywords)
            url_match = any(keyword in url.lower() for keyword in normalized_url_keywords)
            if title_match or url_match:
                print(f"命中目标页面: title='{title}'")
                return browser, page
    return None, None


def wait_tauri_ready_cdp(page, timeout_ms: int) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            location = page.evaluate(
                """() => {
            const api = globalThis.__TAURI__;
            const internals = globalThis.__TAURI_INTERNALS__;
            if (api && typeof api.invoke === 'function') return 'root';
            if (api && api.core && typeof api.core.invoke === 'function') return 'core';
            if (internals && typeof internals.invoke === 'function') return 'internals';
            return 'missing';
          }"""
            )
        except Exception:
            location = "missing"
        if location in {"root", "core", "internals"}:
            print(f"Tauri invoke 已就绪，位置: {location}")
            return True
        time.sleep(0.5)
    return False


def collect_click_targets_cdp(page, limit: int):
    return page.evaluate(
        """({ limit }) => {
          const selector = 'button, a, [role="button"], input[type="button"], input[type="submit"], [onclick]';
          const all = Array.from(document.querySelectorAll(selector));
          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };
          const cssPath = (el) => {
            if (el.id) return `#${CSS.escape(el.id)}`;
            const parts = [];
            let current = el;
            while (current && current.nodeType === 1 && parts.length < 6) {
              let part = current.localName;
              const siblings = current.parentElement ? Array.from(current.parentElement.children).filter((n) => n.localName === current.localName) : [];
              if (siblings.length > 1) {
                const index = siblings.indexOf(current) + 1;
                part += `:nth-of-type(${index})`;
              }
              parts.unshift(part);
              if (current.parentElement && current.parentElement.id) {
                parts.unshift(`#${CSS.escape(current.parentElement.id)}`);
                break;
              }
              current = current.parentElement;
            }
            return parts.join(' > ');
          };
          const result = [];
          for (const el of all) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
            result.push({ selector: cssPath(el), tag: el.tagName.toLowerCase(), text: text || '(no-text)' });
            if (result.length >= limit) break;
          }
          return result;
        }
        """,
        {"limit": limit},
    )


def run_cdp(args) -> int:
    app_process = maybe_launch_app(args)
    try:
        if not wait_endpoint(args.endpoint, args.timeout_ms, "cdp"):
            raise SystemExit(f"CDP 端点不可达: {args.endpoint}")

        with sync_playwright() as p:
            browser, page = pick_target_page_cdp(p, args.endpoint, args.title_keywords, args.url_keywords, args.timeout_ms)
            if not page:
                raise SystemExit("未找到目标页面")

            console_errors = []
            page_errors = []

            def on_console(msg):
                if msg.type == "error":
                    console_errors.append(f"{msg.type}: {msg.text}")

            def on_pageerror(err):
                page_errors.append(str(err))

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)

            try:
                page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
            except Exception:
                pass

            if not wait_tauri_ready_cdp(page, args.timeout_ms):
                print("警告: Tauri invoke 未就绪，继续测试...")

            page.wait_for_selector(args.expect_selector, timeout=args.timeout_ms)
            count = page.locator(args.expect_selector).count()
            if count < args.min_count:
                raise SystemExit(f"渲染断言失败: {args.expect_selector} 数量 {count} < {args.min_count}")

            home_url = page.url
            targets = collect_click_targets_cdp(page, args.max_click_targets)
            
            print("可点击目标列表:")
            for idx, item in enumerate(targets, start=1):
                print(f"{idx}. {item['tag']} | {item['text']} | {item['selector']}")
            
            click_reports = []
            prev_console_len = len(console_errors)
            prev_page_error_len = len(page_errors)
            
            for idx, item in enumerate(targets, start=1):
                report = {"index": idx, "selector": item["selector"], "text": item["text"], "ok": True, "error_count": 0}
                try:
                    page.locator(item["selector"]).first.click(timeout=args.timeout_ms)
                    page.wait_for_timeout(args.click_wait_ms)
                except Exception as error:
                    report["ok"] = False
                    report["error"] = f"点击失败: {error}"
                
                new_errors = len(console_errors) - prev_console_len + len(page_errors) - prev_page_error_len
                report["error_count"] = max(new_errors, 0)
                if new_errors > 0:
                    report["ok"] = False
                
                click_reports.append(report)
                
                try:
                    if page.url != home_url:
                        page.go_back(wait_until="domcontentloaded", timeout=args.timeout_ms)
                        page.wait_for_timeout(300)
                except Exception:
                    pass
                
                prev_console_len = len(console_errors)
                prev_page_error_len = len(page_errors)
            
            violations = []
            for pattern in args.forbid_patterns:
                violations.extend([line for line in console_errors if pattern in line])
                violations.extend([line for line in page_errors if pattern in line])
            
            if violations:
                raise SystemExit("前端报错命中禁用模式: " + " | ".join(violations))
            
            failed_steps = [item for item in click_reports if not item["ok"]]
            print(json.dumps({"selector": args.expect_selector, "count": count, "click_steps": len(click_reports), "failed_steps": len(failed_steps)}, ensure_ascii=False))
            print("累计控制台错误:")
            print(json.dumps({"console_errors": console_errors, "page_errors": page_errors}, ensure_ascii=False))
            
            if failed_steps:
                raise SystemExit("点击循环存在失败步骤: " + json.dumps(failed_steps, ensure_ascii=False))
            
            print("✅ 页面渲染成功，点击循环完成，未发现禁用报错")
            browser.close()
            return 0
    finally:
        if app_process:
            app_process.terminate()


# ============== WebDriver (Playwright HTTP Client) 实现 ==============

class WebDriverClient:
    def __init__(self, request: APIRequestContext, endpoint: str):
        self.request = request
        self.endpoint = endpoint.rstrip("/")
        self.session_id: Optional[str] = None

    def start_session(self):
        print(f"正在连接 WebDriver: {self.endpoint}...")
        response = self.request.post(f"{self.endpoint}/session", data={"capabilities": {}})
        if not response.ok:
            raise Exception(f"无法创建会话: {response.status} {response.text()}")
        data = response.json()
        self.session_id = data.get("value", {}).get("sessionId")
        print(f"会话已创建: {self.session_id}")

    def delete_session(self):
        if self.session_id:
            self.request.delete(f"{self.endpoint}/session/{self.session_id}")

    def _url(self, path: str) -> str:
        return f"{self.endpoint}/session/{self.session_id}{path}"

    def navigate(self, url: str):
        self.request.post(self._url("/url"), data={"url": url})

    def get_url(self) -> str:
        return self.request.get(self._url("/url")).json()["value"]
        
    def go_back(self):
        self.request.post(self._url("/back"), data={})

    def find_elements(self, selector: str) -> List[str]:
        response = self.request.post(self._url("/elements"), data={"using": "css selector", "value": selector})
        if not response.ok:
            return []
        elements = response.json()["value"]
        return [list(el.values())[0] for el in elements]

    def get_text(self, element_id: str) -> str:
        response = self.request.get(self._url(f"/element/{element_id}/text"))
        return response.json()["value"] if response.ok else ""

    def get_tag_name(self, element_id: str) -> str:
        response = self.request.get(self._url(f"/element/{element_id}/name"))
        return response.json()["value"] if response.ok else ""

    def click(self, element_id: str):
        response = self.request.post(self._url(f"/element/{element_id}/click"), data={})
        if not response.ok:
            error = response.json().get("value", {}).get("error", "unknown")
            raise Exception(f"点击失败: {error}")

    def execute_script(self, script: str, args: List[Any] = []) -> Any:
        response = self.request.post(self._url("/execute/sync"), data={"script": script, "args": args})
        if response.ok:
            return response.json()["value"]
        return None

def wait_tauri_ready_webdriver(client: WebDriverClient, timeout_ms: int) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            result = client.execute_script("""
                const api = globalThis.__TAURI__;
                const internals = globalThis.__TAURI_INTERNALS__;
                if (api && typeof api.invoke === 'function') return 'root';
                if (api && api.core && typeof api.core.invoke === 'function') return 'core';
                if (internals && typeof internals.invoke === 'function') return 'internals';
                return 'missing';
            """)
        except Exception:
            result = "missing"
        
        if result in {"root", "core", "internals"}:
            print(f"Tauri invoke 已就绪，位置: {result}")
            return True
        time.sleep(0.5)
    return False

def run_webdriver(args) -> int:
    app_process = maybe_launch_app(args)
    try:
        if not wait_endpoint(args.endpoint, args.timeout_ms, "webdriver"):
            raise SystemExit(f"WebDriver 端点不可达: {args.endpoint}")

        with sync_playwright() as p:
            request = p.request.new_context()
            client = WebDriverClient(request, args.endpoint)
            
            try:
                client.start_session()
                
                if not wait_tauri_ready_webdriver(client, args.timeout_ms):
                    print("警告: Tauri invoke 未就绪，继续测试...")

                # 注入 JS 拦截器来捕获 Console Error 和全局错误
                client.execute_script("""
                    if (!window.__E2E_ERRORS__) {
                        window.__E2E_ERRORS__ = [];
                        const originalError = console.error;
                        console.error = function(...args) {
                            window.__E2E_ERRORS__.push("console.error: " + args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' '));
                            originalError.apply(console, args);
                        };
                        window.addEventListener('error', (e) => {
                            window.__E2E_ERRORS__.push("window.error: " + (e.message || String(e)));
                        });
                        window.addEventListener('unhandledrejection', (e) => {
                            window.__E2E_ERRORS__.push("unhandledrejection: " + (e.reason ? String(e.reason) : 'unknown'));
                        });
                    }
                """)
                print("已注入 JS Console 错误拦截器")

                # 检查元素数量
                elements = client.find_elements(args.expect_selector)
                count = len(elements)
                if count < args.min_count:
                    raise SystemExit(f"渲染断言失败: {args.expect_selector} 数量 {count} < {args.min_count}")

                home_url = client.get_url()
                
                # 收集点击目标 (使用 JS 注入计算精确的 CSS Path，避免缓存 ID 导致 Stale Element)
                js_script = f"""
                    const limit = {args.max_click_targets};
                    const selector = 'button, a, [role="button"], input[type="button"], input[type="submit"], [onclick]';
                    const all = Array.from(document.querySelectorAll(selector));
                    const isVisible = (el) => {{
                        const style = window.getComputedStyle(el);
                        if (style.visibility === 'hidden' || style.display === 'none') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    }};
                    const cssPath = (el) => {{
                        if (el.id) return `#${{CSS.escape(el.id)}}`;
                        const parts = [];
                        let current = el;
                        while (current && current.nodeType === 1 && parts.length < 6) {{
                            let part = current.localName;
                            const siblings = current.parentElement ? Array.from(current.parentElement.children).filter((n) => n.localName === current.localName) : [];
                            if (siblings.length > 1) {{
                                const index = siblings.indexOf(current) + 1;
                                part += `:nth-of-type(${{index}})`;
                            }}
                            parts.unshift(part);
                            if (current.parentElement && current.parentElement.id) {{
                                parts.unshift(`#${{CSS.escape(current.parentElement.id)}}`);
                                break;
                            }}
                            current = current.parentElement;
                        }}
                        return parts.join(' > ');
                    }};
                    const result = [];
                    for (const el of all) {{
                        if (!isVisible(el)) continue;
                        const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
                        result.push({{ selector: cssPath(el), tag: el.tagName.toLowerCase(), text: text || '(no-text)' }});
                        if (result.length >= limit) break;
                    }}
                    return result;
                """
                targets = client.execute_script(js_script) or []
                
                print("可点击目标列表:")
                for idx, item in enumerate(targets, start=1):
                    print(f"{idx}. {item['tag']} | {item['text']} | {item['selector']}")
                
                click_reports = []
                prev_error_len = 0
                all_errors = []
                
                for idx, item in enumerate(targets, start=1):
                    report = {"index": idx, "selector": item["selector"], "text": item["text"], "ok": True, "error_count": 0}
                    try:
                        # 实时查询最新的 DOM 节点，避免 Stale Element Reference
                        els = client.find_elements(item["selector"])
                        if not els:
                            raise Exception(f"元素在当前 DOM 中未找到: {item['selector']}")
                        
                        client.click(els[0])
                        time.sleep(args.click_wait_ms / 1000)
                    except Exception as error:
                        report["ok"] = False
                        report["error"] = f"点击失败: {error}"
                    
                    # 获取注入的错误
                    current_errors = client.execute_script("return window.__E2E_ERRORS__ || [];") or []
                    all_errors = current_errors
                    new_errors = len(current_errors) - prev_error_len
                    report["error_count"] = max(new_errors, 0)
                    if new_errors > 0:
                        report["ok"] = False
                    
                    click_reports.append(report)
                    
                    # 返回首页
                    try:
                        if client.get_url() != home_url:
                            client.go_back()
                            time.sleep(0.3)
                    except Exception:
                        pass
                    
                    prev_error_len = len(current_errors)
                
                # 检查违规
                violations = []
                for pattern in args.forbid_patterns:
                    violations.extend([line for line in all_errors if pattern in line])
                
                if violations:
                    raise SystemExit("前端报错命中禁用模式: " + " | ".join(violations))
                
                failed_steps = [item for item in click_reports if not item["ok"]]
                print(json.dumps({"selector": args.expect_selector, "click_steps": len(click_reports), "failed_steps": len(failed_steps)}, ensure_ascii=False))
                print("累计控制台错误:")
                print(json.dumps({"errors": all_errors}, ensure_ascii=False))
                
                if failed_steps:
                    raise SystemExit("点击循环存在失败步骤: " + json.dumps(failed_steps, ensure_ascii=False))
                
                print("✅ 页面渲染成功，点击循环完成，未发现禁用报错")
                return 0
            finally:
                client.delete_session()
    finally:
        if app_process:
            app_process.terminate()


def run() -> int:
    args = parse_args()

    if args.driver == "auto":
        if wait_endpoint(args.webdriver_endpoint, 3000, "webdriver"):
            args.driver = "webdriver"
            args.endpoint = args.webdriver_endpoint
            print(f"自动检测: 使用 WebDriver ({args.endpoint})")
        elif wait_endpoint(args.cdp_endpoint, 3000, "cdp"):
            args.driver = "cdp"
            args.endpoint = args.cdp_endpoint
            print(f"自动检测: 使用 CDP ({args.endpoint})")
        else:
            args.driver = "webdriver"
            args.endpoint = args.webdriver_endpoint
            print(f"自动检测: 默认使用 WebDriver ({args.endpoint})")
    else:
        if args.driver == "cdp":
            args.endpoint = args.cdp_endpoint
        else:
            args.endpoint = args.webdriver_endpoint

    print(f"驱动类型: {args.driver}, 端点: {args.endpoint}")

    if args.driver == "cdp":
        return run_cdp(args)
    else:
        return run_webdriver(args)


if __name__ == "__main__":
    raise SystemExit(run())
