"""
玄机 · 结构http会话日志 session_log.py（Windows 端，独立实现）
============================================================
借鉴 DeepSeek Harness 的 append-only SessionEvent 思维：把玄机的每一次
交互沉淀为不可变的结构化事件日志。作为玄机的"记忆原始层"——比一句话
JSON 对话记忆更完整，能支撑回忆、回放、分析、复盘。

事件类型：
  - user      用户说
  - assistant 玄机回
  - action    玄机动了手脚(hermes/browser/desktop/工具)
  - learn     玄机学(沉淀技能/召回技能)
  - system    系统事件(启动/心跳/定时)

存储：D:\\yuxuanji\\xuanji-gui\\_session_log.jsonl  (append-only, 追加)

用法：
  import session_log as sl
  sl.log("user", "帮我查天气")
  sl.log("assistant", "好", meta={"model":"deepseek"})
  evs = sl.recent(20)          # 最近20条
  st  = sl.stats()             # 统计
"""

import os
import json
import time
from datetime import datetime

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_session_log.jsonl")
_MAX_LINES = 20000  # 日志上限(超了滚动截断，防无限增长)


def log(event_type: str, content: str, meta: dict = None):
    """追加一条事件。event_type 见模块注释。"""
    ev = {
        "t": datetime.now().isoformat(timespec="seconds"),
        "ts": time.time(),
        "type": event_type,
        "content": content,
        "meta": meta or {},
    }
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[session_log] 写入失败: " + str(e))
        return ev
    # 防无限增长：超限滚动截断
    try:
        if os.path.getsize(_LOG_FILE) > 50 * 1024 * 1024:
            _truncate()
    except Exception:
        pass
    return ev


def _read_all() -> list:
    evs = []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        evs.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    except Exception as e:
        print("[session_log] 读取失败: " + str(e))
    return evs


def _truncate():
    """只留最近 _MAX_LINES 条。"""
    evs = _read_all()
    if len(evs) > _MAX_LINES:
        evs = evs[-_MAX_LINES:]
        try:
            with open(_LOG_FILE, "w", encoding="utf-8") as f:
                for ev in evs:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception:
            pass


def recent(n=20, event_type=None):
    """取最近 n 条(可按类型过滤)。"""
    evs = _read_all()
    if event_type:
        evs = [e for e in evs if e.get("type") == event_type]
    return evs[-n:]


def stats() -> dict:
    """统计各类型事件数量。"""
    from collections import Counter
    c = Counter()
    for ev in _read_all():
        c[ev.get("type", "?")] += 1
    return dict(c)


def last_summary(kind="action", n=5):
    """最近几次某类型事件的一句话摘要(方便玄机回忆自己干过什么)。"""
    evs = recent(n, kind)
    if not evs:
        return []
    return [f"[{e.get('t','')}] {e.get('content','')}" for e in evs]


if __name__ == "__main__":
    # 自测
    log("user", "帮我查一下今天的天气")
    log("assistant", "好，我来看下，稍等", {"model": "deepseek-chat"})
    log("action", "appel web_search", {"tool": "web_search"})
    log("learn", "沉淀技能: 查天气", {"skill": "weather"})
    print("=== 最近事件 ===")
    for e in recent(5):
        print(f"[{e['type']}] {e['content'][:40]} @ {e['t']}")
    print("统计:", stats())
