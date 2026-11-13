"""
玄机 · 自主任务执行器 agent_runner.py  （去 Hermes vendor 深提炼）
============================================================
给玄机一个"听得懂自然语言复杂目标、能自己一步步干成"的本地大脑，
替代原本 subprocess 调 vendor Hermes(456MB) 的外包做法。

原理（提炼自 Hermes agent 的自主执行核心，去其形存其神）：
  复杂任务本质是一条"多步工具链"。玄机用自己的 DeepSeek 大脑，
  面对自然语言目标 → 拆成逐步可执行的动作 → 每步调自己的本地
  手脚(dispatch: dir/read/write/run_cmd/browser/web/desktop) →
  失败时把报错喂回大脑让它诊断、改招、换工具 → 直到成功或到上限。

自愈机制（Hermes conversation_loop 的质变内核）：
  - max_steps: 总步数上限，防发散无限循环
  - step_retries: 单步失败重试上限
  - backoff:  失败后指数退避(带抖动)，避免打崩/连打
  - 失败反馈里带 <之前尝试过的做法>，让玄机不重复同样错误、改新招

用法：
  import agent_runner
  r = agent_runner.run("在D盘新建一个叫test的文件夹，并写入一个hello.txt",
                       max_steps=12)
  r -> {"ok":bool, "result":终终总结, "steps":[...步骤日志], "error":...}

注册进 dispatch 后，玄机核心的 dispatch.run("agent", {"goal": ...})
即可调用，成为 hermes 工具的原生替代。
"""

import os
import sys
import json
import time
import random

# 玄机根
_ROOT = os.path.dirname(os.path.abspath(__file__))  # D:\yuxuanji\xuanji-gui
_XJ_ROOT = os.path.dirname(_ROOT)

# ─── DeepSeek 直连（玄机自己的大脑，不靠 vendor）────────────────────
_DS_URL = "https://api.deepseek.com/v1/chat/completions"
_DS_MODEL = "deepseek-chat"   # 平时用便宜快的；复杂可切 v4-pro 由大脑选
_KEY = None


def _load_key():
    """从 .env 读 DeepSeek key（玄机自己的 .env，与 connector 同源）"""
    global _KEY
    if _KEY:
        return _KEY
    candidates = [
        os.path.join(_ROOT, ".env"),
        os.path.join(_XJ_ROOT, ".env"),
    ]
    for envf in candidates:
        if not os.path.isfile(envf):
            continue
        try:
            with open(envf, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY") and "=" in line:
                        _KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            continue
        if _KEY:
            break
    return _KEY


def _call_deepseek(messages, timeout=120, max_tokens=1600):
    """直连 DeepSeek 对话。错误返回 {"error":...}。带简单重试。"""
    import urllib.request
    import urllib.error
    key = _load_key()
    if not key:
        return {"error": "未找到 DEEPSEEK_API_KEY"}
    body = {
        "model": _DS_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_DS_URL, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })
    last_err = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            return obj["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            try:
                last_err = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                last_err = str(e)
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last_err = str(e)
            time.sleep(1.5 * (attempt + 1))
    return {"error": "LLM 调用失败: " + last_err}


# ─── 本地工具（调玄机自己的 dispatch 手脚）──────────────────────────
def _tool_call(name, params):
    """调玄机本地 dispatch。返回 dict{ok, result/error}。"""
    try:
        if _XJ_ROOT not in sys.path:
            sys.path.insert(0, _XJ_ROOT)
        import dispatch
        return dispatch.run(name, params or {})
    except Exception as e:
        return {"ok": False, "error": "工具调度异常: " + str(e)}


# 玄机当前实际可用的本地工具清单（供大脑选）
_TOOL_BRIEF = {
    "dir":         {"需要": "path", "说明": "列出目录内容"},
    "read_file":   {"需要": "path", "说明": "读文件文本"},
    "write_file":  {"需要": "path, content", "说明": "写文件"},
    "run_cmd":     {"需要": "cmd", "说明": "在Windows执行命令"},
    "search_file": {"需要": "root, pattern", "说明": "按文件名模式搜索"},
    "http_get":    {"需要": "url", "说明": "HTTP GET取网页/接口"},
    "web":         {"需要": "action(或query)", "说明": "联网搜索/抓页(web)"},
    "desktop":     {"需要": "action", "说明": "操作Windows桌面"},
    "browser":     {"需要": "action", "说明": "控制浏览器"},
    "agent":       {"需要": "goal", "说明": "自主执行复杂目标(本模块，可嵌套)"},
}


def _sys_prompt():
    """系统提示词：告诉玄机大脑怎么一步步完成任务并自愈。"""
    tools = "\n".join(f"- {n}: {d.get('说明')} (参数: {d.get('需要')})"
                      for n, d in _TOOL_BRIEF.items())
    return (
        "你是一个自主任务执行大脑。用户给你一个目标，你需要一步步完成它。\n"
        "规则：\n"
        "1. 必须输出合法 JSON，格式必须是：{\"tool\":\"工具名\",\"params\":{...},"
        "\"reason\":\"这步为什么这么做\"}\n"
        "   可用工具：\n" + tools + "\n"
        "2. 每轮只调用一个工具，等结果返回后再决定下一步。\n"
        "3. 若刚调用的工具失败了，看<上一步结果>里的错误信息，换思路/换参数/换工具，"
        "不要重复同样的错误操作。\n"
        "4. 当任务已完成，输出：{\"done\":true,\"summary\":\"给用户的最终结果总结\"}\n"
        "5. 除非目标明确要求，不要随意删除或覆盖未知文件。Windows路径用反斜杠，"
        "如 D:\\xxx\\yyy.txt\n"
        "6. 涉及多文件或复杂目标的，按逻辑拆成多步逐步执行，别想一步到位。"
    )


def _run_single_step(messages, goal):
    """让大脑决策下一步。若它输出 done 则任务完成。返回 (done, summary or toolspec)。"""
    resp = _call_deepseek(messages, timeout=120)
    if not resp or "error" in resp:
        return False, {"error": resp.get("error", "LLM无响应")}
    content = (resp.get("content") or "").strip()
    # 有的模型会包代码块```json ... ```，去掉
    if content.startswith("```"):
        content = content.strip("`")
        # 去掉可能的 json 字样头
        if content.lower().startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        obj = json.loads(content)
    except Exception:
        # 容忍模型在 JSON 前后带说明文字：抓第一个 { 到最后一个 }
        try:
            s, e = content.find("{"), content.rfind("}")
            obj = json.loads(content[s:e + 1])
        except Exception:
            return False, {"error": "大脑未输出合法JSON: " + content[:200]}
    if obj.get("done"):
        return True, obj.get("summary", "任务完成")
    tool = obj.get("tool")
    if not tool:
        return False, {"error": "大脑没指定工具: " + content[:200]}
    params = obj.get("params", {})
    reason = obj.get("reason", "")
    return False, {"tool": tool, "params": params, "reason": reason}


def run(goal, max_steps=12, step_retries=3, verbose=False):
    """执行一个自然语言目标。返回 {ok, result, steps}。"""
    key = _load_key()
    if not key:
        return {"ok": False, "error": "DeepSeek key 未配置", "steps": []}
    messages = [{"role": "system", "content": _sys_prompt()},
                {"role": "user", "content": f"目标：{goal}\n请开始一步步执行。"}]
    steps = []
    for step_i in range(1, max_steps + 1):
        # ── 让大脑决策下一步 ──
        msg = "你已完成上面的动作。请继续下一步，或若任务已完成输出 done。"
        if steps:
            last = steps[-1]
            msg = (
                f"<上一步动作结果>：工具={last['tool']} 结果截断="
                f"{str(last['result'] if last.get('ok') else last.get('error'))[:1500]}\n"
                f"基于上一步结果，请决定下一步（失败要换思路）或输出 done 收尾。"
            )
        dm = [{"role": "user", "content": msg}]
        done, decision = _run_single_step(messages + dm, goal)
        if isinstance(decision, dict) and decision.get("error"):
            # 大脑决策失败这一轮，但不放弃，重试决策一次
            messages = messages + dm + [{"role": "assistant", "content": msg},
                                        {"role": "user", "content": f"刚才报错：{decision['error']}，请重新给合法JSON决策。"}]
            continue
        if done:
            steps.append({"step": step_i, "status": "done", "summary": decision})
            return {"ok": True, "result": decision, "steps": steps}
        tool = decision["tool"]
        params = decision.get("params", {})
        # ── 单步执行 + 自愈重试 ──
        r = {"ok": False, "error": "未执行"}
        for attempt in range(1, step_retries + 1):
            r = _tool_call(tool, params)
            if r.get("ok"):
                break
            if verbose:
                print(f"[agent] {tool} 第{attempt}次失败: {str(r.get('error'))[:100]}，退避后重试")
            # 指数退避 + 抖动
            time.sleep(min(10, 1.2 ** attempt + random.uniform(0, 0.5)))
        steps.append({
            "step": step_i, "tool": tool, "ok": r.get("ok"),
            "result": r.get("result") if r.get("ok") else None,
            "error": None if r.get("ok") else str(r.get("error"))[:600],
            "reason": decision.get("reason", ""),
        })
        if not r.get("ok"):
            # 单步彻底失败就收尾，不给大脑空转耗死
            return {"ok": False,
                    "error": f"工具 {tool} 重试{step_retries}次仍失败: {str(r.get('error'))[:300]}",
                    "steps": steps}
        # 成功→把结果喂回上下文，进入下一轮决策
        messages = messages + [
            {"role": "assistant", "content": f"调用工具 {tool}，参数 {json.dumps(params, ensure_ascii=False)}"},
            {"role": "user", "content": f"上一步成功，结果摘要：{str(r.get('result'))[:1500]}。请继续或 done。"},
        ]
    return {"ok": False, "error": f"达到 {max_steps} 步上限未完成", "steps": steps}


def register(dispatch):
    """把 agent 工具注册进 dispatch，作为 hermes 的原生替代。"""
    @dispatch.tool("agent", owner="xuanji_agent")
    def _agent(params):
        goal = params.get("goal") or params.get("cmd") or params.get("query")
        if not goal:
            return {"ok": False, "error": "agent 需要 goal（自然语言目标）"}
        max_steps = int(params.get("max_steps", 12))
        return run(goal, max_steps=max_steps)
    return _agent


if __name__ == "__main__":
    test_goal = sys.argv[1] if len(sys.argv) > 1 else "把当前目录 D:\\ 下的文件列出来，告诉我前5个"
    print("=== 玄机自主执行器自测 ===")
    print("目标:", test_goal)
    rr = run(test_goal, max_steps=10)
    print("ok:", rr.get("ok"))
    if rr.get("result"):
        print("结果:", str(rr["result"])[:400])
    if rr.get("steps"):
        print("--- 执行步骤日志 ---")
        for s in rr["steps"]:
            print(f"  步{s['step']}: {s.get('tool','done')} ok={s.get('ok')} "
                  f"{str(s.get('result') or s.get('summary') or s.get('error'))[:120]}")
    if rr.get("error"):
        print("error:", rr["error"][:300])
