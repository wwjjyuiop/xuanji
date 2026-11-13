"""启动器：用 Popen 启动 main.py 后立即退出，不阻塞"""
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
# 用 pythonw.exe（无窗口版 Python）启动，隐藏后台黑窗口——日志已嵌入 GUI 左下日志框
python = r"C:\Users\WinJoy\AppData\Local\Programs\Python\Python310\pythonw.exe"
main = os.path.join(os.path.dirname(__file__), "main.py")

# ─── 心脏看门狗：启动前先检查，心脏坏则自动从备份恢复 ───
try:
    import heart_guard
    hg = heart_guard.heartbeat()
    if hg["restored"] > 0:
        print(f"[心脏] 已自动恢复 {hg['restored']} 个核心文件")
    if hg["problems"]:
        print("[心脏] 警告(不影响启动，建议查看):", hg["problems"])
except Exception as e:
    print("[心脏] 看门狗异常(忽略，继续启动): " + str(e))

proc = subprocess.Popen(
    [python, main],
    # 去掉 shell=True（它会让 python 用 cmd.exe 执行，弹出包着 pythonw 的 cmd 黑窗口）
    # 加 CREATE_NO_WINDOW 彻底不显现任何控制台窗口
    creationflags=subprocess.CREATE_NO_WINDOW,
)
print(f"玄机 GUI 已启动，PID: {proc.pid}")

# ─── 自我重启循环（方案三 · 3.3 self_restart 配套）───
# 玄机写 .restart.flag 请求重启时，这里循环拉起新实例。
# 每次循环先等旧进程退出，再检测 flag，有则重新 Popen。
try:
    import self_evolution as _se
    _restart_waits = 0
    while _se.restart_requested() and _restart_waits < 10:
        _req = _se.consume_restart_flag()
        _reason = (_req or {}).get("reason", "") or ""
        print(f"[重启] 玄机请求重启 ({_reason})，等待旧进程退出后拉起")
        try:
            proc.wait(timeout=20)
        except Exception:
            pass
        proc = subprocess.Popen(
            [python, main],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"[重启] 玄机已重启，新 PID: {proc.pid}")
        _restart_waits += 1
except Exception as _e:
    print("[重启] 自我重启循环异常(忽略): " + str(_e))
