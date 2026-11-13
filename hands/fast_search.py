# -*- coding: utf-8 -*-
"""
玄机 · 全盘秒搜手脚（走预建索引）
============================================================
来历：同批第三方框架 OpenTurri 的招牌能力是"读 NTFS 主文件表（MFT）做全盘秒搜"。
玄机用不了那条路——读 MFT / USN 日志要管理员权限，玄机跑在普通用户下
（实测 `fsutil usn readjournal C:` 报"错误 5: 拒绝访问"）；
Windows 自带的搜索索引也不含 D 盘（实测搜 xuanji 零结果）。

所以走第三条：自己建一份索引。
  · 首扫全盘一次（实测 D 盘 11.5 万文件 / 19 秒），存进 SQLite；
  · 之后按关键词查库，毫秒级返回（实测 26 毫秒）；
  · 不需要管理员权限，不改任何系统设置。

与内置 search_file 的分工：
  · search_file —— 每次一层层遍历目录（慢，必须指定 root，容易超时）
  · find_file   —— 查预建索引（快，不用指定 root，可全盘搜）
  要"找某个文件在哪"就用 find_file；要"列某个目录下符合模式的文件"用 search_file。

用法（玄机自己调）：
    find_file(keyword="玄机")              → 全盘搜，毫秒级
    find_file(keyword=".md", exts=["md"])  → 只找 md
    find_file(action="build")              → 重建/更新索引（约 20 秒）
    find_file(action="stats")              → 看索引状态
"""

import os
import sys
import time

# file_index.py 与 dispatch.py 同级（D:\yuxuanji），把它加进搜索路径
_XJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _XJ_ROOT not in sys.path:
    sys.path.insert(0, _XJ_ROOT)

_file_index = None


def _get_index():
    """惰性加载索引模块。失败返回 None。"""
    global _file_index
    if _file_index is None:
        try:
            import file_index
            _file_index = file_index
        except Exception as e:
            print("[手脚] file_index 加载失败: " + str(e))
            _file_index = False
    return _file_index if _file_index else None


def run_find(keyword="", limit=20, exts=None, action="search", root=None):
    """全盘秒搜。返回 dispatch 标准的 dict{ok, result, error}。"""
    idx = _get_index()
    if idx is None:
        return {
            "ok": False,
            "error": "秒搜索引模块 file_index.py 不可用（应在 D:\\yuxuanji\\file_index.py）",
        }

    # ── 建索引 ──
    if action == "build":
        try:
            t0 = time.time()
            root = root or "D:\\"
            total = idx.build(root, verbose=False)
            return {
                "ok": True,
                "result": "索引已刷新：%s 下共 %d 个文件，用时 %.1f 秒" % (
                    root, total, time.time() - t0),
            }
        except Exception as e:
            return {"ok": False, "error": "建索引失败: " + str(e)}

    # ── 看状态 ──
    if action == "stats":
        try:
            s = idx.stats()
            return {
                "ok": True,
                "result": "索引 %d 个文件，上次刷新 %s，扫描根 %s，库大小 %.1f MB" % (
                    s["total"], s["last_build"], s["root"], s["db_size_mb"]),
            }
        except Exception as e:
            return {"ok": False, "error": "读索引状态失败: " + str(e)}

    # ── 搜索 ──
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "要给 keyword 才能搜；要刷新索引用 action='build'"}

    # 索引没建过 → 明确说，别让她以为"盘上没有"
    if not idx.index_exists():
        return {
            "ok": False,
            "error": "秒搜索引还没建过（首次要先建一次，约 20 秒）。"
                     "请调 find_file(action='build') 建好再搜。",
        }

    limit = max(1, min(int(limit or 20), 200))
    try:
        t0 = time.time()
        rows = idx.search(kw, limit=limit, exts=exts)
        dt = (time.time() - t0) * 1000

        # 索引陈旧 → 附提示。陈旧的索引"能搜到但结果不可信"，
        # 不提示的话她会把过期结果当真话报出去。
        note = ""
        try:
            age = idx.index_age_days()
            if age > 7:
                note = "（提示：索引已 %.0f 天没刷新，结果可能缺新文件或含已删文件，" \
                       "可调 find_file(action='build') 刷新，约 20 秒）\n" % age
        except Exception:
            pass

        if not rows:
            return {
                "ok": True,
                "result": note + "没找到含「%s」的文件（耗时 %.0f 毫秒）。"
                          "若确认盘上有，可能是索引太旧，可用 action='build' 刷新。" % (kw, dt),
            }

        lines = ["找到 %d 个含「%s」的文件（耗时 %.0f 毫秒）：" % (len(rows), kw, dt)]
        for p, sz, mt in rows:
            lines.append("  %s  (%.1f KB, %s)" % (
                p, sz / 1024.0, time.strftime("%Y-%m-%d %H:%M", time.localtime(mt))))
        return {"ok": True, "result": note + "\n".join(lines)}
    except Exception as e:
        return {"ok": False, "error": "搜索失败: " + str(e)}


def register(dispatch):
    """把 find_file 注册进 dispatch。"""

    @dispatch.tool("find_file", owner="fast_search")
    def _find_file(params):
        keyword = params.get("keyword", "") or params.get("name", "") or params.get("q", "")
        limit = params.get("limit", 20)
        exts = params.get("exts")
        action = params.get("action", "search")
        root = params.get("root")
        return run_find(keyword=keyword, limit=limit, exts=exts,
                        action=action, root=root)

    return _find_file
