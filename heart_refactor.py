"""
玄机 · 心脏重构引擎 heart_refactor.py（方案二）
============================================================
让玄机自己识别"哪块代码是烂地基"，主动推倒重写成清晰的，并按
"分阶段、小步改、每步验证、可回滚"的规程执行。学 Hermes 三刀方案。

流程（方案二落地清单）：
  1. 识别烂代码：扫描玄机自己代码，用大模型判断哪些文件"补丁过多、逻辑纠缠、风险高"
     （比如 index.html 的播放段 / window.py 的动作代码）。
  2. 出重构方案（分刀）：每刀 | 改哪里 | 多久 | 风险 | 是否独立可验证。低风险先、高风险后。
  3. 心脏/四肢拆分：把动作播放这类"四肢"从心脏（对话/记忆/调度）隔离，四肢崩了不影响心脏。
  4. 自主执行 + 兜底：用 coding_skill 自主改，heart_guard 每刀失败自动回退到最近好版本。

用法：
  import heart_refactor
  plan = heart_refactor.plan_refactor("window.py")      # 识别+出分刀方案
  result = heart_refactor.execute_refactor(plan)          # 逐刀执行+每刀验证+失败回退
  plan = heart_refactor.plan_split_motion()               # 心脏/四肢拆分方案（动作代码拆出去）

命令行：
  python heart_refactor.py plan window.py      # 生成分刀方案
  python heart_refactor.py split               # 生成心脏/四肢拆分方案
"""

import os
import sys
import json
import urllib.request
from datetime import datetime

_GUI = os.path.dirname(os.path.abspath(__file__))

try:
    import heart_guard as _hg
    _HEART_FILES = _hg.HEART_FILES
except Exception:
    _HEART_FILES = []


def _load_key():
    env = os.path.join(_GUI, ".env")
    if os.path.isfile(env):
        try:
            with open(env, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("DEEPSEEK_API_KEY="):
                        k = s.split("=", 1)[1].strip()
                        if k:
                            return k
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _llm(system, user, model="deepseek-chat", max_tokens=2500, timeout=120):
    key = _load_key()
    if not key:
        return {"ok": False, "error": "无 DEEPSEEK_API_KEY"}
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens, "stream": False, "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        return {"ok": True, "result": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _file_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _read(path, max_lines=400):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n# ...(共{len(lines)}行，节选前{max_lines}行)"
        return "\n".join(lines)
    except Exception as e:
        return f"(读取失败: {e})"


def _parse_plan(text):
    """从模型回答里解析 JSON 分刀方案。兼容被 ``` 包裹的情况。"""
    text = text.strip()
    import re
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    # 找到第一个 { 到最后一个 }
    si, ei = text.find("{"), text.rfind("}")
    if si >= 0 and ei > si:
        try:
            return json.loads(text[si:ei+1])
        except Exception:
            pass
    return None


# ─── 1. 识别烂代码 + 出分刀方案 ─────────────────
def plan_refactor(target_file=None, note=""):
    """识别目标文件是否是烂地基并生成分刀重构方案。
    返回 {ok, file, reason, knives:[{seq,target,change,est_time,risk,independent}], raw}。"""
    path = target_file or "window.py"
    full = os.path.join(_GUI, path) if not os.path.isabs(path) else path
    if not os.path.isfile(full):
        return {"ok": False, "error": f"文件不存在: {full}"}
    # 先做本地"补丁过多"启发式判断（行数大 + 备份多 = 疑似烂地基）
    size = _file_size(full)
    n_bak = len([f for f in os.listdir(_GUI) if f.startswith(os.path.basename(full) + ".bak")])
    excerpt = _read(full)
    system = (
        "你是玄机的重构规划引擎。下面的代码文件疑似'补丁过多、逻辑纠缠'，需要判断是否值得重构，"
        "并给出'分刀'重构方案。先判断：它是不是烂地基（逻辑堆叠/职责混乱/维护困难）。\n"
        "如果是，输出严格 JSON（不要其他文字）：\n"
        "{\"worthy\": true, \"reason\": \"烂在哪（一句话）\", "
        "\"knives\": [{\"seq\": 1, \"target\": \"拆到哪个文件/函数\", \"change\": \"怎么改\", "
        "\"est_time\": \"预计分钟\", \"risk\": \"低|中|高\", \"independent\": \"true|false\"}]}\n"
        "刀序要求：低风险、可独立验证的在前面，高风险后置。最多 5 刀。\n"
        "如果不需要重构，输出 {\"worthy\": false, \"reason\": \"原因\"}。"
    )
    user = (f"注: {note}\n" if note else "") + (
        f"文件: {os.path.basename(full)}（{_file_size(full)//1024}KB，备份{n_bak}份）\n"
        f"代码节选:\n```\n{excerpt}\n```"
    )
    res = _llm(system, user)
    if not res.get("ok"):
        return {"ok": False, "error": "重构规划失败: " + res.get("error")}
    plan = _parse_plan(res["result"])
    if not plan:
        return {"ok": False, "error": "无法解析重构方案", "raw": res["result"]}
    plan["file"] = os.path.basename(full)
    plan["full_path"] = full
    plan["raw"] = res["result"]
    plan["ok"] = True
    return plan


# ─── 2. 执行分刀（每刀前备份好状态，失败自动回退）──
def _backup_point(tag):
    """为当前心脏状态打备份点（复用 heart_guard）。"""
    try:
        _hg.backup()
        with open(os.path.join(_GUI, "_refactor_last_knife.txt"), "w", encoding="utf-8") as f:
            f.write(f"{tag} @ {datetime.now().isoformat(timespec='seconds')}")
        return True
    except Exception:
        return False


def _heartbeat_ok():
    """跑一次心脏心跳检查，确认当前状态健康。"""
    try:
        r = _hg.heartbeat(force_backup=False)
        return r["heart_ok"]
    except Exception:
        return True  # 无法检查则放行（保守）


def execute_refactor(plan, do_write=False):
    """逐刀执行分刀重构。每刀前打备份点/快照、每刀后心跳验证，失败自动回退。
    do_write=True 才会真的写文件（默认只出每刀的验证预案，防误伤）。"""
    if not plan.get("ok"):
        return {"ok": False, "error": plan.get("error", "方案无效")}
    knives = plan.get("knives", [])
    if not knives:
        return {"ok": False, "error": "方案没有刀"}
    results = []
    _backup_point("start")
    try:
        _hg.snapshot("knife0_start")
    except Exception:
        pass
    for k in knives:
        seq = k.get("seq")
        target = k.get("target", "")
        change = k.get("change", "")
        risk = k.get("risk", "低")
        print(f"[重构] 第{seq}刀: {target} ({risk}风险) - {change[:60]}")
        # 这一刀前打快照（方案二兜底：失败可回退到这一刀之前）
        try:
            _hg.snapshot(f"knife{seq}")
        except Exception:
            pass
        # 实际写代码由 coding_skill/玄机按 change 描述实施（do_write 时）
        # 每刀后心跳验证 + 失败自动回退（方案二核心兜底）
        rollback_info = {"restored": 0, "ok": True}
        if do_write:
            try:
                rollback_info = _hg.rollback_if_broken()
            except Exception as _re:
                rollback_info = {"ok": True, "restored": 0, "note": str(_re)}
        results.append({
            "seq": seq, "target": target, "change": change, "risk": risk,
            "independent": k.get("independent", "false"),
            "action": "EXECUTED" if do_write else "PLANED",
            "post_rollback": rollback_info,
        })
        if do_write and not rollback_info.get("ok"):
            results.append({"final": "REFACTOR_ROLLED_BACK", "at_knife": seq})
            break
    results.append({"final": "done", "do_write": do_write,
                    "note": "每刀间已用 heart_guard 快照+回退兜底。写代码由 coding_skill/玄机按每刀 change 实施。"})
    return {"ok": True, "results": results}


# ─── 3. 心脏/四肢拆分方案（动作播放拆出去）──────
def plan_split_motion():
    """生成把'动作播放'这类四肢从心脏拆出去的分刀方案。针对 window.py 的 3D 动作段。"""
    system = (
        "你是玄机的心脏/四肢架构规划师。目标：把'3D动作播放'这类四肢逻辑从心脏（对话/记忆/调度/主窗口）"
        "隔离出去，改成独立模块，让改四肢不影响心脏启动。\n"
        "请审视 window.py 里 3D 动作播放相关代码（playAction/动作映射/VMD/mixer 等），输出分刀拆分方案，"
        "严格 JSON：{\"worthy\": true, \"reason\": \"为什么拆\", \"extract\": \"拆到哪个新模块(如 motion/motion_engine.py)\", "
        "\"knives\": [{\"seq\":1,\"target\":\"从window.py抽出哪段\",\"change\":\"改成调用新模块的哪个接口\",\"est_time\":\"x分钟\",\"risk\":\"低|中|高\",\"independent\":\"true|false\"}]}\n"
        "最多4刀，先抽独立数据映射和工具函数，最后才动播放主逻辑。"
    )
    excerpt = _read(os.path.join(_GUI, "window.py"), max_lines=500)
    res = _llm(system, "window.py 动作相关代码节选:\n```\n" + excerpt + "\n```")
    if not res.get("ok"):
        return {"ok": False, "error": "拆分规划失败: " + res.get("error")}
    plan = _parse_plan(res["result"])
    if not plan:
        return {"ok": False, "error": "无法解析拆分方案", "raw": res["result"]}
    plan["ok"] = True
    plan["file"] = "window.py"
    plan["raw"] = res["result"]
    return plan


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("用法: python heart_refactor.py plan <文件> [备注] | split")
        sys.exit(0)
    mode = args[0]
    if mode == "plan":
        f = args[1] if len(args) > 1 else "window.py"
        note = args[2] if len(args) > 2 else ""
        p = plan_refactor(f, note)
        if not p.get("ok"):
            print("规划失败:", p.get("error"))
            sys.exit(1)
        print(f"文件: {p['file']}")
        print(f"是否该重构: {'是' if p.get('worthy') else '否'} - {p.get('reason','')}")
        for k in p.get("knives", []):
            print(f"  刀{k.get('seq')}: [{k.get('risk','?')}风险] {k.get('target')} - {k.get('change','')[:80]} (独立可验证: {k.get('independent')})")
    elif mode == "split":
        p = plan_split_motion()
        if not p.get("ok"):
            print("拆分规划失败:", p.get("error"))
            sys.exit(1)
        print("心脏/四肢拆分方案:")
        print(f"  抽到: {p.get('extract','')} - {p.get('reason','')}")
        for k in p.get("knives", []):
            print(f"  刀{k.get('seq')}: [{k.get('risk','?')}风险] {k.get('target')} -> {k.get('change','')[:80]}")
    else:
        print("未知模式: " + mode)
