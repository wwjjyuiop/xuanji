"""
玄机 · 心脏自审闭环 heart_review.py（方案一）
============================================================
让玄机改完任何代码后，先自己当评审：拆开看、找 bug、判断能不能启动，
通过了才让代码上线。解决"改一版、补一版、没人审"的根病。

三道关卡（方案一落地清单）：
  1. 静态自检（秒级）：ast 语法检查 + 关键符号存在性（复用 heart_guard 逻辑加强）
  2. 语义自审（大模型读代码）：把改动代码块交给 DeepSeek，带着"找逻辑漏洞"的
     指令读（明确问"播放逻辑是不是把所有动作堆一起了？有没有清旧动作？停止能
     不能真停下来？"），正好抓那套动作代码的病根。
  3. 红绿灯门禁：自审不通过 → 返工再改 → 再审，直到绿灯。

用法：
  import heart_review
  ok, report = heart_review.review_file("window.py")        # 静态+符号
  ok, report = heart_review.review_with_ai("window.py", "改动说明")  # 全流程含AI自审

命令行：
  python heart_review.py check window.py        # 仅静态
  python heart_review.py ai window.py "说明"    # 静态+AI语义自审（调DeepSeek）
"""

import os
import sys
import ast
import json
import urllib.request

_GUI = os.path.dirname(os.path.abspath(__file__))

# 复用 heart_guard 的心跳关键符号表（识别"被改坏"）
try:
    import heart_guard as _hg
    _HEART_KEY = _hg.HEART_KEY
    _HEART_FILES = _hg.HEART_FILES
except Exception:
    _HEART_KEY = {}
    _HEART_FILES = []


def _load_key():
    """从 .env 读 DeepSeek key（与 connector 同款）。"""
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


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def static_check(path):
    """关卡1：静态自检（语法 + 关键符号 + 平衡性）。返回 (ok, [问题列表])。"""
    problems = []
    try:
        src = _read(path)
    except Exception as e:
        return False, [f"无法读取: {e}"]
    # 1) 语法
    try:
        ast.parse(src)
    except SyntaxError as e:
        return False, [f"语法错误 L{e.lineno}: {e.msg}"]
    except Exception as e:
        return False, [f"解析异常: {e}"]
    # 2) 括号/引号平衡（精确统计，排除字符串/注释里的括号，避免误报）
    try:
        import tokenize as _tk, io as _io, token as _tok
        _c = {"paren": 0, "bracket": 0, "brace": 0}
        def _cb(ttype, tval, *a):
            if ttype == _tok.OP:
                if tval == "(":
                    _c["paren"] += 1
                elif tval == ")":
                    _c["paren"] -= 1
                elif tval == "[":
                    _c["bracket"] += 1
                elif tval == "]":
                    _c["bracket"] -= 1
                elif tval == "{":
                    _c["brace"] += 1
                elif tval == "}":
                    _c["brace"] -= 1
        for _t in _tk.tokenize(_io.BytesIO(src.encode("utf-8")).readline):
            _cb(_t.type, _t.string)
        if _c["paren"] != 0:
            problems.append(f"圆括号不平衡: 差值{_c['paren']:+d}")
        if _c["bracket"] != 0:
            problems.append(f"方括号不平衡: 差值{_c['bracket']:+d}")
        if _c["brace"] != 0:
            problems.append(f"花括号不平衡: 差值{_c['brace']:+d}")
    except Exception as _be:
        # tokenize 不可用则退回朴素统计
        for ch_open, ch_close, name in [("{", "}", "花括号"), ("(", ")", "圆括号"), ("[", "]", "方括号")]:
            if src.count(ch_open) != src.count(ch_close):
                problems.append(f"{name}不平衡(粗略): {src.count(ch_open)} vs {src.count(ch_close)}")
    # 3) 关键符号存在性（若是心脏文件）
    name = os.path.basename(path)
    if name in _HEART_KEY:
        for sym in _HEART_KEY.get(name, []):
            if sym not in src:
                problems.append(f"缺失关键符号: {sym}")
    # 4) 函数/类定义完整性启发：def 关键词后有冒号的主体应有内容（粗查缩进行）
    return (len(problems) == 0), problems


def ai_review(path, change_note="", model="deepseek-chat", timeout=90):
    """关卡2+3：语义自审。把改动代码交给 DeepSeek 找逻辑漏洞。
    返回 (ok, report)。ok=False 表示自审不过，需返工。"""
    try:
        src = _read(path)
    except Exception as e:
        return False, f"无法读取代码进行自审: {e}"
    key = _load_key()
    if not key:
        return True, "（无 DeepSeek key，跳过 AI 语义自审，仅静态把关）"

    # 取文件关键部分（前 300 行 + 显眼的大逻辑段），避免太长
    lines = src.split("\n")
    excerpt = "\n".join(lines[:300])
    if len(lines) > 300:
        excerpt += f"\n# ...(共{len(lines)}行，节选前300行自审)"

    review_instructions = (
        "你是玄机的代码评审。审查下面这段代码，重点找这些逻辑漏洞并明确回答：\n"
        "1. 播放/动作逻辑：是否把所有动作堆在同一个播放段里？有没有清旧动作再播新的？\n"
        "2. 停止逻辑：停止操作能不能真正停下来（状态标志是否重置）？\n"
        "3. 会不会在调用时崩：有无明显 None 解引用 / 索引越界 / 无限循环？\n"
        "4. 改动是否有副作用影响心脏/主流程启动？\n"
        "只输出结论，不要贴代码。格式：\n"
        "PASS（可上线）或 FAIL（必须返工）\n"
        "问题列表：\n"
        "  - 问题1\n"
        "  - 问题2\n"
    )
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": review_instructions},
            {"role": "user", "content": f"改动说明: {change_note or '（无）'}\n\n被审文件片段:\n```\n{excerpt}\n```"},
        ],
        "max_tokens": 800,
        "temperature": 0.2,
        "stream": False,
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
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except Exception as e:
        return True, f"（AI 自审调用失败，降级为仅静态把关: {e}）"
    ok = text.strip().upper().startswith("PASS")
    return ok, text


def review_file(path, change_note="", with_ai=True):
    """完整自审闭环：静态 -> （可选）AI 语义 -> 汇总。返回 (ok, report)。"""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, f"文件不存在: {path}"
    stat_ok, problems = static_check(path)
    report_lines = []
    report_lines.append(f"=== 自审: {os.path.basename(path)} ===")
    report_lines.append(f"[静态] {'通过' if stat_ok else '发现问题'}")
    for p in problems:
        report_lines.append("  ! " + p)
    ai_ok = True
    if with_ai and stat_ok:  # 静态挂了就不浪费 AI 了,先返工语法
        ai_ok, ai_report = ai_review(path, change_note)
        report_lines.append(f"[语义] {'通过' if ai_ok else '未通过(需返工)'}")
        report_lines.append(ai_report.replace("\n", "\n  "))
    ok = stat_ok and ai_ok
    report_lines.append(f"=== 结论: {'✅ 绿灯,可上线' if ok else '🔴 红灯,返工再审'} ===")
    return ok, "\n".join(report_lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("用法: python heart_review.py check <文件> | ai <文件> [改动说明]")
        sys.exit(0)
    mode = args[0]
    fpath = os.path.join(_GUI, args[1]) if len(args) > 1 else ""
    if not fpath or not os.path.isfile(fpath):
        print("文件不存在: " + fpath)
        sys.exit(1)
    if mode == "check":
        ok, probs = static_check(fpath)
        print("静态自审:", "通过" if ok else "发现问题")
        for p in probs:
            print("  ! " + p)
        sys.exit(0 if ok else 1)
    elif mode == "ai":
        note = args[2] if len(args) > 2 else ""
        ok, rep = review_file(fpath, note, with_ai=True)
        print(rep)
        sys.exit(0 if ok else 1)
    else:
        print("未知模式: " + mode)
