"""
玄机 · Hermes 适配器（去 vendor 深提炼版）
============================================================
【二档B 深提炼】原版 subprocess 调 vendor/Hermes(456MB) 当"听得懂自然语言
的自主执行外援"。本版改为调用玄机本地自主执行器 agent_runner.py——
用玄机自己的 DeepSeek 大脑 + 本地 dispatch 手脚 + 失败自愈重试，
彻底脱离 vendor Hermes。

保留工具名 "hermes"（== 玄机自主执行 agent）：这样玄机核心所有
dispatch.run("hermes", ...) 的调用点（coding_skill/cron/skill_hands/
subagent/connector 等）无需改动，透明地把"外包给 vendor"换成"玄机自己干"。

能力对齐原版：
  - 接收自然语言复杂指令 ✓（agent_runner 多步拆解执行）
  - 终端/脚本/文件/联网/浏览器 综合调用 ✓（走玄机本地 dispatch 手脚）
  - 失败自愈 + 退避重试 ✓（agent_runner 内建）
  - 隔离玄机 HOME/不含外部 key ✓（用玄机 .env 的 DEEPSEEK_API_KEY）
"""

import os
import sys

# agent_runner 在玄机 GUI 目录
_XJ_GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # D:\yuxuanji\xuanji-gui
if _XJ_GUI not in sys.path:
    sys.path.insert(0, _XJ_GUI)

_agent_runner = None


def _get_runner():
    """惰性加载玄机本地自主执行器。失败返回 None。"""
    global _agent_runner
    if _agent_runner is None:
        try:
            import agent_runner
            _agent_runner = agent_runner
        except Exception as e:
            print("[手脚] agent_runner 加载失败: " + str(e))
            _agent_runner = False
    return _agent_runner if _agent_runner else None


def run_hermes(cmd, timeout=150):
    """让玄机本地 agent_runner 自主执行一个自然语言指令。返回 dict。"""
    if not cmd or not str(cmd).strip():
        return {"ok": False, "error": "缺少指令"}
    runner = _get_runner()
    if runner is None:
        return {"ok": False, "error": "玄机自主执行器(agent_runner)不可用，无法执行复杂任务"}
    # 转成 agent_runner 的 run()
    try:
        # timeout 大致折算成步数上限（每步约 10-20s）
        max_steps = max(6, min(25, int((timeout or 150) / 8)))
        r = runner.run(str(cmd).strip(), max_steps=max_steps)
        return {
            "ok": bool(r.get("ok")),
            "result": r.get("result") if r.get("ok") else (r.get("error") or "任务失败"),
            "error": r.get("error") if not r.get("ok") else None,
            "steps": r.get("steps", []),
            "exit": 0 if r.get("ok") else 1,
        }
    except Exception as e:
        return {"ok": False, "error": "自主执行异常: " + str(e)}


def register(dispatch):
    """把 hermes 工具注册进 dispatch（同名覆盖旧 vendor 版，透明切换）。"""
    @dispatch.tool("hermes", owner="xuanji_agent")
    def _hermes(params):
        cmd = params.get("cmd", "") or params.get("query", "")
        timeout = int(params.get("timeout", 150))
        if not cmd:
            return {"ok": False, "error": "缺少 cmd"}
        return run_hermes(cmd, timeout)
    return _hermes
