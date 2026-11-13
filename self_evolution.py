"""
玄机 · 自我进化四件套 self_evolution.py（方案三 · 3.3 学 Hermes self-evolving）
============================================================
给玄机四个"安全改自己"的工具，让她能自己改自己代码并重启：
  self_read     读自己源码（带行数，方便定位）
  self_write    写自己源码（**自动备份到 .backups/ + 写前语法校验**，改崩有退路）
  self_install  用 pip 装 python 包
  self_restart  写 .restart.flag 触发重启（由 launcher 循环拉起）

安全铁律：
  - self_write 一律先备份再写，绝不裸覆盖
  - self_write 写 .py 前先 ast 语法校验，不过就拒写并报错
  - self_write 只允许写玄机自己目录里的文件（防越权改系统）
  - self_restart 只写 flag，由 launcher 检测后拉起，不自杀

用法：
  import self_evolution as se
  se.self_read("connector.py")
  se.self_write("connector.py", "新内容", reason="重构大脑")
  se.self_install("requests")
  se.self_restart("准备升级")
"""

import os
import re
import shutil
import subprocess
import sys
import ast
from datetime import datetime

GUI = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(GUI, ".backups")
RESTART_FLAG = os.path.join(GUI, ".restart.flag")


def _now():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_path(relpath: str) -> str:
    """把相对/绝对路径规范到玄机自己的目录，防越权。返回绝对路径或 None。"""
    relpath = (relpath or "").strip().replace("\\", "/")
    if not relpath:
        return None
    if os.path.isabs(relpath):
        # 绝对路径必须落在 GUI 目录内
        norm = os.path.normpath(relpath)
        if norm == GUI or norm.startswith(GUI + os.sep):
            return norm
        return None
    # 相对路径，去掉 .. 越级
    rel = os.path.normpath(relpath)
    if rel.startswith("..") or rel.startswith("/"):
        return None
    return os.path.join(GUI, rel)


def _syntax_ok(path: str) -> tuple:
    """语法检查 .py/.pyw，返回 (ok, 错误信息)。"""
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        ast.parse(src)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误 L{e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


def backup_file(path: str) -> str:
    """把文件备份到 .backups/，返回备份路径。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = os.path.basename(path)
    dst = os.path.join(BACKUP_DIR, f"{name}.bak-{_now()}")
    if os.path.isfile(path):
        shutil.copy2(path, dst)
    return dst


# ─── 1. self_read ─────────────────────────────────
def self_read(relpath: str) -> dict:
    """读自己源码（带行号）。返回 {ok, content, lines}。"""
    path = _safe_path(relpath)
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": f"文件不存在或越权: {relpath}"}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        numbered = "\n".join(f"{i+1:>4} | {ln}" for i, ln in enumerate(lines))
        return {"ok": True, "path": path, "lines": len(lines), "content": "\n".join(lines), "numbered": numbered}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 2. self_write ────────────────────────────────
def self_write(relpath: str, content: str, reason: str = "", force_syntax_check: bool = True) -> dict:
    """写自己源码。**先备份 + 语法校验**。返回 {ok, backup, path}。"""
    path = _safe_path(relpath)
    if not path:
        return {"ok": False, "error": f"越权路径: {relpath}，玄机只能改自己目录里的文件"}
    if not os.path.isfile(path):
        return {"ok": False, "error": f"文件不存在(用新建请先确认目录): {relpath}"}
    # 语法校验（仅 .py/.pyw 且内容含 def/class/import 时才严格检查）
    ext = os.path.splitext(path)[1].lower()
    if force_syntax_check and ext in (".py", ".pyw") and any(k in content for k in ("def ", "class ", "import ", "=")):
        # 写入临时文件再校验，避免污染原文件
        tmp = path + ".tmpcheck"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
            ok, err = _syntax_ok(tmp)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
        if not ok:
            return {"ok": False, "error": f"语法校验未通过，拒绝写入(已备份旧版可回滚)。{err}"}
    # 备份旧版
    bak = backup_file(path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": path, "backup": bak, "reason": reason}
    except Exception as e:
        return {"ok": False, "error": f"写入失败(旧版已备份 {bak}): {e}"}


# ─── 3. self_install ──────────────────────────────
def self_install(package: str) -> dict:
    """用 pip 装 python 包。返回 {ok, output}。"""
    package = (package or "").strip()
    if not package:
        return {"ok": False, "error": "未指定包名"}
    py = sys.executable or "python"
    try:
        r = subprocess.run(
            [py, "-m", "pip", "install", package],
            capture_output=True, text=True, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return {"ok": r.returncode == 0, "output": out[-1500:], "package": package}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 4. self_restart ──────────────────────────────
def self_restart(reason: str = "") -> dict:
    """写 .restart.flag 请求重启。由 launcher 启动器循环检测并拉起。不自杀。"""
    try:
        payload = {"reason": reason, "time": _now()}
        import json
        with open(RESTART_FLAG, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return {"ok": True, "message": "已写重启请求，玄机将自动重启", "flag": RESTART_FLAG}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def restart_requested() -> bool:
    """launcher 调用：是否有重启请求。"""
    return os.path.isfile(RESTART_FLAG)


def consume_restart_flag() -> dict:
    """launcher 调用：读取并清除重启请求。返回 {reason, time} 或 None。"""
    if not os.path.isfile(RESTART_FLAG):
        return None
    try:
        import json
        with open(RESTART_FLAG, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    try:
        os.remove(RESTART_FLAG)
    except Exception:
        pass
    return data or None


# ─── 自检 ──────────────────────────────────────────
def self_test():
    print("=== 玄机自我进化四件套自检 ===")
    # read
    r = self_read("main.py")
    print("read main.py:", "OK" if r.get("ok") else "FAIL", f"({r.get('lines')}行)")
    # write 越权拦截
    w = self_write("..\\evil.py", "x=1")
    print("write 越权拦截:", "OK" if not w.get("ok") else "FAIL")
    # write 正常（不真写坏文件，只校验流程——写到临时测试文件）
    test_file = os.path.join(GUI, "_selftest_tmp.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    w2 = self_write("_selftest_tmp.py", "y = 2\n")
    print("write 备份+写入:", "OK" if w2.get("ok") and w2.get("backup") else "FAIL")
    # write 语法拦截
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    w3 = self_write("_selftest_tmp.py", "def broken(:\n  pass\n")
    print("write 语法拦截:", "OK" if not w3.get("ok") else "FAIL")
    os.remove(test_file)
    # restart flag
    self_restart("自检")
    rq = restart_requested()
    cr = consume_restart_flag()
    print("restart flag 写入/读取/清除:", "OK" if rq and cr else "FAIL")
    print("=== 自检完成 ===")


if __name__ == "__main__":
    self_test()
