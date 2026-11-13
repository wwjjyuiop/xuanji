"""
玄机 GUI · 主入口
极简启动，只做一件事：打开窗口
防多开：mutex锁防重复实例
"""

import sys
import os

# 确保当前目录在路径中
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ─── 单实例锁 ────────────────────────────────
_LOCKFILE = os.path.join(os.path.dirname(__file__), ".gui.lock")
try:
    old_pid = None
    if os.path.isfile(_LOCKFILE):
        with open(_LOCKFILE) as f:
            old_pid = int(f.read().strip())
        import subprocess
        r = subprocess.run(
            ["tasklist", "/NH", "/FI", f"PID eq {old_pid}"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if str(old_pid) in r.stdout:
            print(f"[启动] GUI已在运行(PID:{old_pid})，禁止多开")
            sys.exit(0)
except Exception:
    pass
with open(_LOCKFILE, "w") as f:
    f.write(str(os.getpid()))
import atexit
atexit.register(lambda: os.remove(_LOCKFILE) if os.path.isfile(_LOCKFILE) else None)

# ─── 手机端Web服务已移除（2026-08-15，玄机只在电脑上运行）───

from PySide6.QtWidgets import QApplication
from window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("玄机")
    
    window = MainWindow()
    # 2026-10-15 公子要求：开机即最大化
    window.showMaximized()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
