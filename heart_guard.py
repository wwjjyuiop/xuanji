"""
玄机 · 心脏看门狗 heart_guard.py
============================================================
心脏保护：让玄机能改自己代码、能自我升级进化，但心脏永远有兜底——
即使她把某个核心文件改崩了，启动前诊断器能检测出来，自动从备份恢复，
保证玄机永远不会"起不来"。

分层：
  - 心脏（核心启动链，改动需谨慎、有快照）：
      main.py, launcher.py, connector.py, window.py, memory_service.py,
      self_awareness.py
  - 身体（玄机可自由改，改坏不影响心脏）：
      dispatch.py, skill_hands.py, learning_engine.py, hands/*.py, skills/

命令：
  python heart_guard.py check          # 扫描心脏文件健康(语法+import关键符)
  python heart_guard.py backup         # 备份当前心脏文件到 _heart_backup/
  python heart_guard.py snapshot       # 为健康状态打快照标记(启动时自动)
  python heart_guard.py restore        # 从备份恢复(有备份才恢复)
  python heart_guard.py heartbeat      # 完整心跳: 检查+必要时恢复(供启动前调用)
"""

import os
import sys
import shutil
import ast
import re
import time
from datetime import datetime

_GUI = os.path.dirname(os.path.abspath(__file__))
# 心脏核心文件(玄机"必走""能启动"的关键)
HEART_FILES = [
    "main.py", "launcher.py", "connector.py", "window.py",
    "memory_service.py", "self_awareness.py",
]
# 关键符号(每个心脏文件应含;缺失视为被改坏)
HEART_KEY = {
    "main.py": ["MainWindow", "QApplication"],
    "launcher.py": ["main.py", "Popen"],
    "connector.py": ["send_message", "_build_system_prompt", "DEEPSEEK_API_KEY"],
    "window.py": ["MainWindow", "ChatPanel"],
    "memory_service.py": ["MemoryService", "get_personality"],
    "self_awareness.py": ["build_self_prompt"],
}
_BACKUP_DIR = os.path.join(_GUI, "_heart_backup")
# 分刀重构快照目录（方案二：每刀前打快照，失败可精确回退到某刀）
_SNAPSHOT_DIR = os.path.join(_GUI, "_refactor_snapshots")


def _now():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _syntax_ok(path):
    """返回 (ok, 错误信息)。语法检查。"""
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        ast.parse(src)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误 L{e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


def _check_one(name):
    """检查单个心脏文件。返回 (status, detail)。"""
    path = os.path.join(_GUI, name)
    if not os.path.isfile(path):
        return "MISSING", "文件不存在"
    ok, detail = _syntax_ok(path)
    if not ok:
        return "FAIL", detail
    # 关键符号存在性
    try:
        src = open(path, encoding="utf-8").read()
    except Exception as e:
        return "FAIL", str(e)
    for sym in HEART_KEY.get(name, []):
        if sym not in src:
            return "FAIL", f"缺失关键符号: {sym}"
    return "OK", ""


def check():
    """扫描所有心脏文件。返回 (健康?, 问题列表)。"""
    problems = []
    for name in HEART_FILES:
        st, det = _check_one(name)
        if st != "OK":
            problems.append(f"[{name}] {st}: {det}")
    return (len(problems) == 0), problems


def _backup_exists():
    return os.path.isdir(_BACKUP_DIR) and len(os.listdir(_BACKUP_DIR)) > 0


def backup():
    """把心脏文件备份到 _heart_backup/(覆盖式,保留最近一份)。"""
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    for name in HEART_FILES:
        src = os.path.join(_GUI, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(_BACKUP_DIR, name))
    # 写时间戳
    with open(os.path.join(_BACKUP_DIR, "backup_time.txt"), "w", encoding="utf-8") as f:
        f.write("last_backup: " + _now() + "\n")
    return True


def restore():
    """从备份恢复心脏文件。返回恢复的文件数。"""
    if not _backup_exists():
        return 0, "无备份可恢复"
    restored = 0
    for name in HEART_FILES:
        src = os.path.join(_BACKUP_DIR, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(_GUI, name))
            restored += 1
    return restored, ""


def heartbeat(force_backup=True):
    """启动前完整心跳：检查心脏→不健康则恢复→总是刷新备份。

    返回 dict{heart_ok, restored, problems}。
    """
    ok, problems = check()
    restored = 0
    if not ok:
        # 有备份且有坏文件，则尝试恢复
        if _backup_exists():
            restored, _ = restore()
            # 恢复后再查一次
            ok2, problems2 = check()
            ok = ok2
            problems = problems2
    # 即使健康也刷新备份(保证备份是最新可用的“最后好版本”)
    if force_backup and ok:
        backup()
    return {"heart_ok": ok, "restored": restored, "problems": problems}


def snapshot(tag=""):
    """方案二：为当前心脏状态打一个带标签的快照（供分刀重构每刀前调用）。
    返回快照目录路径。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"{tag}_{ts}" if tag else ts
    snap_dir = os.path.join(_SNAPSHOT_DIR, label)
    os.makedirs(snap_dir, exist_ok=True)
    for name in HEART_FILES:
        src = os.path.join(_GUI, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(snap_dir, name))
    with open(os.path.join(snap_dir, "snapshot_time.txt"), "w", encoding="utf-8") as f:
        f.write("tag: " + tag + "\ntime: " + ts + "\n")
    print(f"[心脏] 分刀快照已打: {label}")
    return snap_dir


def restore_snapshot(tag=None):
    """方案二：回退到某个分刀快照。tag 缺省则回退到最近一个快照。
    返回 (恢复文件数, 快照路径)。无快照返回 (0,'')。"""
    if not os.path.isdir(_SNAPSHOT_DIR):
        return 0, ""
    snaps = sorted([d for d in os.listdir(_SNAPSHOT_DIR)
                    if os.path.isdir(os.path.join(_SNAPSHOT_DIR, d))])
    if not snaps:
        return 0, ""
    target = tag if tag in snaps else (snaps[-1] if not tag else None)
    if target is None:
        return 0, ""
    snap_dir = os.path.join(_SNAPSHOT_DIR, target)
    restored = 0
    for name in HEART_FILES:
        src = os.path.join(snap_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(_GUI, name))
            restored += 1
    print(f"[心脏] 已回退到快照: {target} (恢复 {restored} 个文件)")
    return restored, snap_dir


def rollback_if_broken():
    """方案二：跑心跳，若不健康且有分刀快照，自动回退到最近快照。
    供重构每刀执行后调用。返回 {ok, restored}。"""
    ok, problems = check()
    if ok:
        return {"ok": True, "restored": 0}
    restored, snap = restore_snapshot()
    if restored == 0:
        # 无快照则退回普通备份
        restored, _ = restore()
    ok2, _ = check()
    print(f"[心脏] 重构兜底: 发现不健康，回退 {restored} 个文件，恢复后健康={ok2}")
    return {"ok": ok2, "restored": restored}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "heartbeat"
    if cmd == "check":
        ok, probs = check()
        print("心脏健康" if ok else "心脏有问题:")
        for p in probs:
            print("  " + p)
        sys.exit(0 if ok else 1)
    elif cmd == "backup":
        backup()
        print("已备份心脏文件 -> " + _BACKUP_DIR)
    elif cmd == "restore":
        n, err = restore()
        print(f"恢复 {n} 个文件" + (f" ({err})" if err else ""))
    elif cmd == "heartbeat":
        r = heartbeat()
        print(f"心跳: heart_ok={r['heart_ok']} restored={r['restored']} problems={r['problems']}")
        sys.exit(0 if r["heart_ok"] else 1)
    else:
        print("用法: check|backup|restore|heartbeat")
