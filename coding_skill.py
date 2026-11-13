"""
玄机 · 编码闭环技能 coding_skill.py
============================================================
让玄机自主完成"写代码 → 执行测试 → 发现问题 → 修改 → 再测"直到通过。
关键：写代码用 DeepSeek v4-pro（最强编码模型），平时用便宜的 chat/flash。

流程（闭环）：
  1. generate  用 v4-pro 根据需求写代码(写文件)
  2. run       用 hermes/子代理 执行测试命令(如 pytest / python file)
  3. check     看结果: 通过则结束; 出错则带错误信息回步骤1让模型改
  4. loop      反复直到通过或达到上限(防死循环)

模型策略：
  - 写/改代码: deepseek-v4-pro (思考最强)
  - 说明/对话: 用玄机平时的模型(便宜)
  通过 dispatch 调用 —— 玄机手上已有 hermes(执行)、subagent(后台测)、web(查资料)

用法：
  import coding_skill
  result = coding_skill.code("写一个 python 脚本计算 1..N 的和")
"""

import os
import sys
import json
import re
import urllib.request

# ─── 自我修改四件套 + 学习循环（方案三 3.3 / 3.6）───
def _self(tool, **kw):
    """惰性调 self_evolution 四件套，失败返回错误 dict 不抛。"""
    try:
        import self_evolution as se
        if tool == "self_read":
            return se.self_read(**kw)
        if tool == "self_write":
            return se.self_write(**kw)
        if tool == "self_install":
            return se.self_install(**kw)
        if tool == "self_restart":
            return se.self_restart(**kw)
        return {"ok": False, "error": "未知工具: " + tool}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# 四件套对外（供 coding_skill 内部 / 外部调用）
def self_read(relpath):
    return _self("self_read", relpath=relpath)

def self_write(relpath, content, reason=""):
    return _self("self_write", relpath=relpath, content=content, reason=reason)

def self_install(package):
    return _self("self_install", package=package)

def self_restart(reason=""):
    return _self("self_restart", reason=reason)

# DeepSeek API（玄机 connector 同款 key / URL）
_DS_URL = "https://api.deepseek.com/v1/chat/completions"
# 最强编码模型 vs 便宜对话模型
CODE_MODEL = "deepseek-v4-pro"     # 写代码用最强
CHAT_MODEL = "deepseek-chat"       # 平时用便宜(connector 同款)

_MAX_LOOPS = 8   # 最多失败改几轮，防死循环


def _load_key():
    """从玄机 GUI .env 读 DeepSeek key。"""
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env):
        with open(env, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("DEEPSEEK_API_KEY="):
                    return s.split("=", 1)[1].strip()
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _llm(messages, model=CODE_MODEL, max_tokens=4000):
    """调 DeepSeek。返回文本。"""
    key = _load_key()
    if not key:
        return {"ok": False, "error": "无 DEEPSEEK_API_KEY"}
    payload = json.dumps({
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        _DS_URL, data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return {"ok": True, "result": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _dispatch_call(tool, params, timeout=120):
    """调玄机 dispatch 手脚。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import dispatch
        return dispatch.run(tool, params)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _extract_code(text):
    """从模型回答里抽代码块或代码。返回原始代码字符串。"""
    # 优先取 ``` 代码块
    m = re.search(r"```(?:python|py|bash|shell|powershell|cmd)?\s*\n(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    # 否则取文件名+代码（简单启发：去掉开头解释，取含关键符号部分）
    return text.strip()


def _extract_filepath(text):
    """尝试从"文件已写入: 路径"这类提示里找路径。"""
    m = re.search(r"['\"]?([A-Za-z]:\\[\w\\\.\-]+|[A-Za-z]:/[\w/\\.\-]+)['\"]?", text)
    return m.group(1) if m else None


def code(request):
    """编码闭环入口。request: 用户的编码需求。
    方案三 · 3.6 学习循环：开头查技能库+查教训，避免重犯；成功自动沉淀技能。"""
    print(f"[编码] 需求: {request}\n[编码] 使用模型: {CODE_MODEL}")
    # ─── 学习循环第1步：开工前查现成技能 + 查教训库（3.6）──
    try:
        import learning_engine as _le
        pre = _le.learning_preflight(request)
        if pre:
            print("[编码·学前]\n" + pre)
    except Exception as _e:
        pass
    # 阶段1：让 v4-pro 生成/定位文件
    gen = _llm([
        {"role": "system", "content":
            "你是玄机的编码引擎。根据需求写出代码。严格按下面 JSON 输出：\n"
            '{"action": "write"|"edit", "path": "目标文件路径", "code": "完整代码内容"}\n'
            "如果是新建脚本就 action=write；如果是改现有文件给路径和改动后完整内容。"},
        {"role": "user", "content": request},
    ])
    if not gen.get("ok"):
        return {"ok": False, "error": "代码生成失败: " + gen.get("error")}
    # 解析 JSON
    try:
        spec = json.loads(_extract_code(gen["result"]))
    except Exception:
        # 兜底：把整段当代码写进一个脚本
        spec = {"action": "write", "path": _extract_filepath(request) or r"D:\yuxuanji\_gen_code.py",
                "code": _extract_code(gen["result"])}
    path = spec.get("path") or r"D:\yuxuanji\_gen_code.py"
    code_text = spec.get("code", "")
    if not code_text:
        return {"ok": False, "error": "模型未给出代码"}

    loop = 0
    last_err = ""
    while loop < _MAX_LOOPS:
        loop += 1
        print(f"[编码] 第 {loop} 轮: 写/改 {path}")
        # 写文件
        w = _dispatch_call("write_file", {"path": path, "content": code_text})
        if not w.get("ok"):
            return {"ok": False, "error": "写文件失败: " + str(w.get("error"))}
        # ─── 启动前自审门禁（方案一）：如果是玄机自己目录内的文件，先静态+语义自审 ──
        try:
            _gui = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _abs = os.path.abspath(path)
            if _abs.startswith(_gui):
                import heart_review as _hr
                _stat_ok, _probs = _hr.static_check(_abs)
                if not _stat_ok:
                    print(f"[自审] 静态未过，返工: {_probs}")
                    last_err = "自审未过: " + "; ".join(_probs)
                    # 跳到返工分支（不跑测试，直接让模型改）
                    fix = _llm([
                        {"role": "system", "content": "你是玄机编码引擎。刚写的代码静态自审未过（语法/括号/关键符号问题）。请修正后严格按 JSON 输出 {\"action\":\"edit\",\"path\":\"原路径\",\"code\":\"修正后的完整代码\"}。"},
                        {"role": "user", "content": f"需求: {request}\n静态自审问题: {last_err}\n当前代码:\n```\n{code_text}\n```"},
                    ])
                    if fix.get("ok"):
                        try:
                            spec2 = json.loads(_extract_code(fix["result"]))
                            code_text = spec2.get("code", code_text)
                            path = spec2.get("path", path)
                        except Exception:
                            code_text = _extract_code(fix["result"])
                    continue
        except Exception as _he:
            print(f"[自审] 自审器异常(放行继续): {_he}")
        # 阶段2+3：跑 + 检查（用 hermes 执行 python 文件，拿错误）
        run = _dispatch_call("hermes", {"cmd": f"运行并检查这个文件 {path}，如果报错请原样贴出全部错误信息，如果成功请回复 RUN_OK", "timeout": 120})
        out = str(run.get("result") or run.get("error") or "")
        if "RUN_OK" in out:
            print("[编码] 通过！")
            # ─── 学习循环最后一步：干成一件有套路的活→沉淀技能+记教训（3.6）──
            try:
                import learning_engine as _le
                _le.create_skill(
                    name="编码闭环",
                    description="玄机自主写代码→执行测试→改错→通过" ,
                    summary="玄机用 coding_skill.code() 自主完成一套写代码闭环，遇到可复用套路会自动沉淀。",
                    how=f"1. 开工前 learning_preflight 查技能+查教训\n2. 需求: {request[:100]}\n3. 写→测→改→再审→通过",
                    tags=["编码", "自改", "循环"],
                    related=["self_write"],
                )
            except Exception as _e:
                pass
            return {"ok": True, "result": f"代码已写并测试通过：{path}\n{out[:300]}"}
        # 出错 → 模型带着错误改
        last_err = out
        fix = _llm([
            {"role": "system", "content":
                "你是玄机编码引擎。下面是根据需求写的代码，但运行时出错。请修正代码，"
                "严格按 JSON 输出 {\"action\":\"edit\",\"path\":\"原路径\",\"code\":\"修正后的完整代码\"}。"},
            {"role": "user", "content":
                f"需求: {request}\n当前代码:\n```\n{code_text}\n```\n运行错误:\n{last_err[:1500]}"},
        ])
        if not fix.get("ok"):
            return {"ok": False, "error": "修正生成失败: " + fix.get("error")}
        try:
            spec2 = json.loads(_extract_code(fix["result"]))
            code_text = spec2.get("code", code_text)
            path = spec2.get("path", path)
        except Exception:
            code_text = _extract_code(fix["result"])
        print(f"[编码] 出错，已带错误信息让模型修改 (错误前{100}字): {last_err[:100]}")

    return {"ok": False, "result": f"达到循环上限({_MAX_LOOPS}轮)，仍需人工查看: {path}", "error": last_err}


if __name__ == "__main__":
    import sys as _s
    if len(_s.argv) > 1:
        print(code(" ".join(_s.argv[1:])))
    else:
        test = "写一个 python 脚本 sum_1_to_n.py，定义函数 sum(n) 返回 1..n 的和，然后 print(sum(5)) 且能直接运行"
        print("自测中…（会真实写文件+执行）")
        r = code(test)
        print("\n最终:", r.get("result"), r.get("error") or "")
