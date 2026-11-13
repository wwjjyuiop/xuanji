"""
玄机 · 子代理引擎 subagent_engine.py（Windows 端，独立实现）
============================================================
让玄机能把复杂任务拆成子任务，后台/并行执行（借鉴 Hermes async_delegation、
OpenClaw subagents 的思想，但用玄机自己的 Python 线程池，纯 Windows 端）。

设计：
  - submit(task, params)   提交一个子代理任务，立即返回 handle(不会阻塞)
  - poll(handle)            查询子任务是否完成及结果
  - wait(handle, timeout)   等待子任务完成并取结果
  - results()              查看所有子任务状态
  - 子任务动作：调玄机 dispatch 的手脚(hermes/browser/desktop/内置)

用法：
  import subagent_engine as sa
  h1 = sa.submit("列出D盘根目录")
  h2 = sa.submit("打开百度并截图")
  r1 = sa.wait(h1, 120)
  r2 = sa.wait(h2, 120)
"""

import os
import sys
import uuid
import time
import threading
import concurrent.futures
from datetime import datetime


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAX_WORKERS = 4  # 玄机最多并行跑几个子代理（适度并发）

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="xuanji-sub")
_tasks = {}           # handle -> {future, meta}
_LOCK = threading.Lock()


def _dispatch_call(action: str, params: dict = None):
    """在子线程里调 dispatch 干一件事。放根目录 import。"""
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    import dispatch
    params = params or {}
    # action 可能是 dispatch 工具名，或直接被 hermes 理解的自然语言
    if action in dispatch.list_tools():
        return dispatch.run(action, params)
    # 否则当自然语言指令交给 hermes
    return dispatch.run("hermes", {"cmd": action, "timeout": 120})


def submit(task, params=None, tool=None, title=None):
    """提交一个子代理任务。

    参数：
      task   - 要做的事（自然语言，或 tool 名）
      params - dispatch 工具参数（当 task 是工具名时用）
      tool   - 指定 dispatch 工具名（可选）
      title  - 任务名（可选）
    返回 handle。
    """
    handle = uuid.uuid4().hex[:12]
    if tool:
        # 明确指定工具
        fut = _executor.submit(lambda: _dispatch_tool(tool, params or {}))
    else:
        fut = _executor.submit(_dispatch_call, task, params)
    with _LOCK:
        _tasks[handle] = {
            "future": fut,
            "meta": {
                "task": task, "tool": tool, "title": title or task,
                "submitted": datetime.now().isoformat(timespec="seconds"),
                "status": "running",
            },
        }
    print(f"[子代理] 已提交: {title or task} (handle={handle})")
    return handle


def _dispatch_tool(tool, params):
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    import dispatch
    return dispatch.run(tool, params)


def _done(r):
    """提交完成回调：更新任务状态。"""
    h, fut = r
    with _LOCK:
        if h in _tasks:
            _tasks[h]["meta"]["status"] = "done"
            _tasks[h]["meta"]["finished"] = datetime.now().isoformat(timespec="seconds")


def status(handle=None):
    """查看子任务状态。handle 省略则返回全部。"""
    if handle:
        with _LOCK:
            t = _tasks.get(handle)
        if not t:
            return {"ok": False, "error": "未知 handle"}
        meta = dict(t["meta"])
        if t["future"].done():
            try:
                meta["result"] = t["future"].result()
            except Exception as e:
                meta["result"] = {"ok": False, "error": str(e)}
        return {"ok": True, **meta}
    out = {}
    with _LOCK:
        for h, t in list(_tasks.items()):
            out[h] = {"status": t["meta"]["status"], "title": t["meta"]["title"]}
    return {"ok": True, "tasks": out}


def poll(handle):
    """查询子任务完成没。返回 (完成?, 结果)。"""
    with _LOCK:
        t = _tasks.get(handle)
    if not t:
        return False, None
    if t["future"].done():
        try:
            return True, t["future"].result()
        except Exception as e:
            return True, {"ok": False, "error": str(e)}
    return False, None


def wait(handle, timeout=None):
    """等待子任务完成并取结果。timeout 秒后未完成返回 None。"""
    with _LOCK:
        t = _tasks.get(handle)
    if not t:
        return {"ok": False, "error": "未知 handle"}
    try:
        return t["future"].result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return {"ok": False, "error": "等待超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cancel_all():
    """取消/清理所有子任务（后续玄机重启时调用）。"""
    with _LOCK:
        _tasks.clear()


if __name__ == "__main__":
    import time as _t
    print("=== 玄机子代理引擎自测 ===")
    # 提交一个简单子任务
    h = submit("列出 D:/yuxuanji 目录下有哪些文件")
    print("handle:", h)
    print("立即返回(不阻塞): completed?", poll(h)[0])
    print("等待完成…")
    r = wait(h, 90)
    print("结果:", str(r.get("result"))[:200] if r else "None")
    print("全部任务:", status())
