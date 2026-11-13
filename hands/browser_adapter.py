"""
玄机 · 浏览器手脚（本地化 Playwright 版）browser_adapter.py
============================================================
二档去框架化：替代原 openclaw_browser_adapter（靠 subprocess 调 vendor OpenClaw）。
本版用玄机 Python 环境自装的 playwright 直接控制 Chromium，零外部框架依赖。

能力（经 dispatch.run("browser", {...})）：
    - start      启动浏览器（幂等，复用已开实例）
    - open       打开一个 http/https URL
    - snapshot   抓取当前页面可交互结构，压缩成玄机能读懂的 ref 树文本
    - click      按 ref 点击一个元素
    - fill       按 ref 在输入框填文字
    - type       模拟键盘输入（聚焦后）
    - press      按快捷键 enter / escape / ctrl+s 等
    - screenshot 给当前页面截图（配合千问看图）
    - title      返回当前页面 URL + 标题
    - close      关闭当前页/全部
    - status     返回浏览器状态

用法：
    import dispatch
    dispatch.run("browser", {"action": "open", "url": "https://..."})
    dispatch.run("browser", {"action": "snapshot"})
    dispatch.run("browser", {"action": "click", "ref": "2"})
    dispatch.run("browser", {"action": "fill", "ref": "3", "text": "关键词"})
"""

import os
import re
import json
import time

# 惰性 import playwright——避免玄机其它模块加载时若 playwright 缺崩掉
_PW = None
_BROWSER = None
_CONTEXT = None
_PAGE = None
_SNAPSHOT_CACHE = []   # 与本轮 snapshot 的 ref 一一对应，供 click/fill 定位


def _get_pw():
    """惰性加载 playwright 库。返回 (sync_playwright 工厂 or None)。"""
    global _PW
    if _PW is None:
        try:
            from playwright.sync_api import sync_playwright
            _PW = sync_playwright
        except Exception as e:
            print("[浏览器] playwright 库加载失败: " + str(e))
            _PW = False
    return _PW if _PW else None


def _ensure_browser():
    """确保浏览器实例+context+page 就绪。返回 page 或 None。"""
    global _BROWSER, _CONTEXT, _PAGE, _SNAPSHOT_CACHE
    sp = _get_pw()
    if sp is None:
        return None
    if _PAGE is not None:
        try:
            _PAGE.title()  # 探活
            return _PAGE
        except Exception:
            _PAGE = None
    try:
        if _BROWSER is None:
            _BROWSER = sp().start().chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            )
        if _CONTEXT is None:
            _CONTEXT = _BROWSER.new_context(
                locale="zh-CN",
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True,
            )
        if _PAGE is None:
            _PAGE = _CONTEXT.new_page()
            _PAGE.set_default_timeout(15000)
        return _PAGE
    except Exception as e:
        print("[浏览器] 启动失败: " + str(e))
        return None


def _visible_text(page):
    """抽当前页可点/可填元素，生成 ref 树文本 + 填 _SNAPSHOT_CACHE。"""
    global _SNAPSHOT_CACHE
    _SNAPSHOT_CACHE = []
    try:
        elems = page.query_selector_all(
            "a, button, input, textarea, select, [role=button], [role=link], "
            "[role=textbox], [contenteditable=true], [onclick]"
        )
    except Exception:
        return "（无法扫描页面结构）"
    lines = []
    ref = 0
    for el in elems:
        try:
            if not el.is_visible():
                continue
            tag = (el.evaluate("e => e.tagName") or "").lower()
            # 跳过空/隐藏导航残留
            txt = (el.inner_text() or "").strip().replace("\n", " ")[:60]
            role = ""
            try:
                role = (el.get_attribute("role") or "").lower()
            except Exception:
                role = ""
            # 类型归类
            kind = tag
            if tag == "input":
                t = (el.get_attribute("type") or "text").lower()
                kind = "textbox" if t in ("text", "search", "email", "url") else ("button" if t == "submit" else f"input:{t}")
            elif tag == "button" or role == "button":
                kind = "button"
            elif tag == "a":
                kind = "link"
            elif tag == "textarea":
                kind = "textbox"
            elif tag == "select":
                kind = "select"
            # 内容描述
            desc = txt
            if tag in ("input", "textarea"):
                ph = ""
                try:
                    ph = el.get_attribute("placeholder") or ""
                except Exception:
                    ph = ""
                desc = f"{txt} [{ph}]" if (txt and ph) else (txt or ph or kind)
            if not desc:
                continue
            if re.fullmatch(r"\s*", desc):
                continue
            _SNAPSHOT_CACHE.append(el)
            lines.append(f"[{ref}] {kind}: {desc}")
            ref += 1
        except Exception:
            continue
    if not lines:
        return "（页面上没有可交互元素）"
    return "\n".join(lines)[:3000]


def browser_action(action: str, params: dict):
    """统一入口，返回 dict{ok, result/error}。任何失败不抛异常。"""
    action = (action or "").lower()
    params = params or {}

    if action in ("start", "status", "title"):
        page = _ensure_browser()
        if page is None:
            return {"ok": False, "error": "浏览器不可用（playwright 或 chromium 未装）"}
        if action == "title":
            try:
                return {"ok": True, "result": f"url={page.url}\ntitle={page.title()}"}
            except Exception as e:
                return {"ok": False, "error": "取标题失败: " + str(e)}
        return {"ok": True, "result": "浏览器已就绪"}

    if action == "open":
        page = _ensure_browser()
        url = (params.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            return {"ok": False, "error": "仅支持 http/https URL"}
        try:
            if url.startswith("http://"):
                # 防 http 被 https 劫持导致 title 不同，直接 go
                pass
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(0.6)
            return {"ok": True, "result": f"已打开: {url}"}
        except Exception as e:
            return {"ok": False, "result": f"打开 {url} 异常: " + str(e)}

    if action == "snapshot":
        page = _ensure_browser()
        if page is None:
            return {"ok": False, "error": "浏览器不可用"}
        try:
            return {"ok": True, "result": _visible_text(page)}
        except Exception as e:
            return {"ok": False, "error": "snapshot 失败: " + str(e)}

    if action in ("click", "fill", "type", "press", "hover"):
        page = _ensure_browser()
        if page is None:
            return {"ok": False, "error": "浏览器不可用"}
        if action in ("press",):
            # press 偏向整页级快捷键（无 ref）
            key = params.get("key") or params.get("text")
            if not key:
                return {"ok": False, "error": "press 需要 key（如 Enter/Escape）"}
            try:
                page.keyboard.press(key)
                return {"ok": True, "result": f"已按键 {key}"}
            except Exception as e:
                return {"ok": False, "error": "press 失败: " + str(e)}
        # 其余要 ref
        ref_s = str(params.get("ref") or params.get("target") or "").strip()
        try:
            ref = int(ref_s)
        except Exception:
            return {"ok": False, "error": f"ref 需为数字，收到: {ref_s!r}（先 snapshot 拿 ref）"}
        if ref < 0 or ref >= len(_SNAPSHOT_CACHE):
            # cache 过期则重扫一次再试
            _visible_text(page)
            if ref < 0 or ref >= len(_SNAPSHOT_CACHE):
                return {"ok": False, "error": f"ref {ref} 超出范围，请重新 snapshot"}
        el = _SNAPSHOT_CACHE[ref]
        try:
            if action == "click":
                el.click(timeout=8000)
                time.sleep(0.4)
                return {"ok": True, "result": f"已点击 ref[{ref}]"}
            if action == "hover":
                el.hover()
                return {"ok": True, "result": f"已悬停 ref[{ref}]"}
            if action in ("fill", "type"):
                text = params.get("text", "")
                try:
                    el.fill(text) if action == "fill" else el.type(text)
                except Exception:
                    el.click()
                    el.press_sequentially(text, delay=20)
                return {"ok": True, "result": f"已在 ref[{ref}] 输入: {text}"}
        except Exception as e:
            return {"ok": False, "error": f"操作 ref[{ref}] 失败: {str(e)[:200]}"}

    if action == "screenshot":
        page = _ensure_browser()
        if page is None:
            return {"ok": False, "error": "浏览器不可用"}
        try:
            dest = params.get("path") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "_browser_shot.png"
            )
            page.screenshot(path=os.path.abspath(dest), full_page=False)
            return {"ok": True, "result": os.path.abspath(dest)}
        except Exception as e:
            return {"ok": False, "error": "截图失败: " + str(e)}

    if action == "close":
        global _PAGE, _CONTEXT, _BROWSER
        try:
            if _PAGE is not None:
                _PAGE.close(); _PAGE = None
            if _CONTEXT is not None:
                _CONTEXT.close(); _CONTEXT = None
            if _BROWSER is not None:
                _BROWSER.close(); _BROWSER = None
            return {"ok": True, "result": "浏览器已关闭"}
        except Exception as e:
            return {"ok": False, "error": "关闭异常: " + str(e)}

    return {"ok": False, "error": f"未知浏览器操作: {action}（可选 start/open/snapshot/click/fill/type/press/screenshot/close/status/title）"}


def register(dispatch):
    """把 browser 工具注册进 dispatch 调度桥（与旧 adapter 同名覆盖，透明替换）。"""
    @dispatch.tool("browser", owner="xuanji_browser")
    def _browser(params):
        action = params.get("action", "")
        if not action:
            return {"ok": False, "error": "缺少 action"}
        return browser_action(action, params)
    return _browser
