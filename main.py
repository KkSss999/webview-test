import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Iterable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--title-keyword", action="append", dest="title_keywords", default=["GoldenIdea"])
    parser.add_argument("--url-keyword", action="append", dest="url_keywords", default=["tauri://", "localhost:1420"])
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--expect-selector", default="body")
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--expect-text", action="append", dest="expect_texts", default=[])
    parser.add_argument("--home-selector")
    parser.add_argument("--max-click-targets", type=int, default=25)
    parser.add_argument("--click-wait-ms", type=int, default=700)
    parser.add_argument("--forbid-console-pattern", action="append", dest="forbid_patterns", default=["[API Error]", "Cannot read properties of undefined (reading 'invoke')"])
    parser.add_argument("--app-cmd")
    parser.add_argument("--app-cwd")
    parser.add_argument("--app-start-wait-ms", type=int, default=8000)
    return parser.parse_args()

def iter_pages(browser: Browser) -> Iterable[tuple[BrowserContext, Page]]:
    for context in browser.contexts:
        for page in context.pages:
            yield context, page

def pick_target_page(browser: Browser, title_keywords: list[str], url_keywords: list[str], timeout_ms: int) -> tuple[BrowserContext, Page] | None:
    normalized_title_keywords = [keyword.lower() for keyword in title_keywords if keyword]
    normalized_url_keywords = [keyword.lower() for keyword in url_keywords if keyword]
    print(f"已连接，当前上下文数量: {len(browser.contexts)}")
    for context, page in iter_pages(browser):
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
            return context, page
    return None


def wait_tauri_ready(page: Page, timeout_ms: int) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            location = page.evaluate(
                "() => { const api = globalThis.__TAURI__; const internals = globalThis.__TAURI_INTERNALS__; if (api && typeof api.invoke === 'function') return 'root'; if (api && api.core && typeof api.core.invoke === 'function') return 'core'; if (internals && typeof internals.invoke === 'function') return 'internals'; return 'missing'; }"
            )
        except Exception:
            location = "missing"
        if location in {"root", "core", "internals"}:
            print(f"Tauri invoke 已就绪，位置: {location}")
            return True
        time.sleep(0.5)
    return False

def wait_endpoint(endpoint: str, timeout_ms: int) -> bool:
    deadline = time.time() + timeout_ms / 1000
    target = endpoint.rstrip("/") + "/json/version"
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
    if "--remote-debugging-port=" not in env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", ""):
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9222"
    process = subprocess.Popen(
        args.app_cmd,
        cwd=args.app_cwd or None,
        env=env,
        shell=True,
    )
    time.sleep(args.app_start_wait_ms / 1000)
    return process


def collect_click_targets(page, limit: int):
    return page.evaluate(
        """
        ({ limit }) => {
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


def return_home(page, home_url: str, home_selector: str | None, timeout_ms: int):
    if page.url != home_url:
        try:
            page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(300)
            return
        except Exception:
            pass
    if home_selector:
        try:
            page.click(home_selector, timeout=timeout_ms)
            page.wait_for_timeout(300)
            return
        except Exception:
            pass
    page.goto(home_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(300)


def run() -> int:
    args = parse_args()
    app_process = maybe_launch_app(args)
    try:
        if not wait_endpoint(args.endpoint, args.timeout_ms):
            raise SystemExit(f"CDP 端点不可达: {args.endpoint}")
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(args.endpoint)
            picked = pick_target_page(browser, args.title_keywords, args.url_keywords, args.timeout_ms)
            if not picked:
                raise SystemExit("未找到目标页面")
            _, page = picked
            console_errors: list[str] = []
            page_errors: list[str] = []
            page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda err: page_errors.append(str(err)))
            try:
                page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
            except Exception:
                pass
            if not wait_tauri_ready(page, args.timeout_ms):
                raise SystemExit("Tauri invoke 未就绪")
            page.wait_for_selector(args.expect_selector, timeout=args.timeout_ms)
            count = page.locator(args.expect_selector).count()
            if count < args.min_count:
                raise SystemExit(f"渲染断言失败: {args.expect_selector} 数量 {count} < {args.min_count}")
            html = page.content()
            for text in args.expect_texts:
                if text not in html:
                    raise SystemExit(f"渲染断言失败: 未找到文本 {text}")
            home_url = page.url
            targets = collect_click_targets(page, args.max_click_targets)
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
                return_home(page, home_url, args.home_selector, args.timeout_ms)
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
            return 0
    finally:
        if app_process is not None:
            app_process.terminate()


if __name__ == "__main__":
    raise SystemExit(run())
