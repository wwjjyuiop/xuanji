"""
玄机 · Web 能力插件 web_adapter.py（Windows 端，独立实现）
============================================================
给玄机 dispatch 补上统一的 web 能力：搜索 + 抓取页面。
纯 Windows 端 Python 实现，不依赖 WSL、不需要额外 key。

能力（经 dispatch.run("web", {...})）：
  - search : 网络搜索(query, 用可用的 bing 搜索)
  - fetch  : 抓取一个 URL 的文本内容
  - links  : 抓取一个 URL 页面的链接
"""

import os
import sys
import re
import urllib.request
import urllib.parse
import json
import html as html_mod


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _http_get(url, timeout=15, max_bytes=500000):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes)
            return resp.status, data
    except Exception as e:
        return None, str(e).encode("utf-8", errors="replace")


def _bing_search(query, count=8):
    """用 bing 搜索(国内可达，无需 key)。返回 [{title,url,snippet}]。"""
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query) + "&count=" + str(count)
    st, data = _http_get(url, timeout=18)
    if st != 200:
        return {"ok": False, "error": f"bing 返回 {st}"}
    text = data.decode("utf-8", errors="replace")

    results = []
    # 解析 bing 的 <li class="b_algo"> 块
    blocks = re.split(r'<li class="b_algo"', text)[1:]
    for b in blocks[:count]:
        # 标题
        tm = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not tm:
            continue
        url_m = tm.group(1)
        title = html_mod.unescape(re.sub(r"<[^>]+>", "", tm.group(2))).strip()
        # 摘要
        sm = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
        snippet = html_mod.unescape(re.sub(r"<[^>]+>", "", sm.group(1))).strip() if sm else ""
        # 过滤 bing 自家跳转
        if "cn.bing.com" in url_m and "go.microsoft" not in url_m:
            continue
        results.append({"title": title, "url": url_m, "snippet": snippet[:200]})
    if not results:
        return {"ok": True, "result": [], "note": "无结构化结果(可能被限流)，建议换关键词"}
    return {"ok": True, "result": results}


def _fetch_text(url, max_chars=20000):
    st, data = _http_get(url, timeout=20)
    if st != 200:
        return {"ok": False, "error": f"抓取失败 HTTP {st}"}
    text = data.decode("utf-8", errors="replace")
    # 抽正文：去 script/style/标签
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return {"ok": True, "result": text[:max_chars]}


def _fetch_links(url, max_links=20):
    st, data = _http_get(url, timeout=20)
    if st != 200:
        return {"ok": False, "error": f"抓取失败 HTTP {st}"}
    text = data.decode("utf-8", errors="replace")
    base = urllib.parse.urljoin(url, "/")
    links = []
    for m in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>', text):
        link = urllib.parse.urljoin(base, m)
        if link.startswith(("http://", "https://")):
            if link not in links:
                links.append(link)
    return {"ok": True, "result": links[:max_links]}


def web_action(action: str, params: dict):
    action = (action or "").lower()
    if action == "search":
        q = params.get("query") or params.get("q") or ""
        if not q:
            return {"ok": False, "error": "search 需要 query"}
        n = int(params.get("count") or params.get("n") or 8)
        return _bing_search(q, n)
    if action == "fetch":
        url = params.get("url", "")
        if not url:
            return {"ok": False, "error": "fetch 需要 url"}
        return _fetch_text(url)
    if action == "links":
        url = params.get("url", "")
        if not url:
            return {"ok": False, "error": "links 需要 url"}
        return _fetch_links(url)
    return {"ok": False, "error": f"未知 web 操作: {action} (search/fetch/links)"}


def register(dispatch):
    @dispatch.tool("web", owner="web")
    def _web(params):
        action = params.get("action", "")
        if not action:
            return {"ok": False, "error": "缺少 action (search/fetch/links)"}
        return web_action(action, params)
    return _web
