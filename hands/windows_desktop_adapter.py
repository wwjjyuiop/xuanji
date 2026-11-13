"""
玄机 · Windows 桌面操控适配器 desktop_adapter.py
============================================================
让玄机核心通过 dispatch.run("desktop", {...}) 像人一样操作 Windows 桌面。
用玄机 Python 环境里已装的 pyautogui（鼠标/键盘/截图/窗口）实现，
完全 Windows 原生，不依赖 OpenClaw(mac 专用)或任何 key。

操作集：
    - open     : 启动一个程序(如 notepad / calc / explorer 或 exe 路径)
    - click    : 在屏幕坐标点击 或 按窗口/坐标
    - type     : 键盘输入文字
    - key      : 按快捷键(如 ctrl+s / enter / alt+tab)
    - screenshot: 截图存盘(玄机可配合千问看图)
    - windows  : 列出当前窗口标题(用 pygetwindow)
    - move     : 移动鼠标

用法(经 dispatch)：
    import dispatch
    dispatch.run("desktop", {"action": "open", "app": "notepad"})
    dispatch.run("desktop", {"action": "type", "text": "你好玄机"})
    dispatch.run("desktop", {"action": "windows"})
"""

import os
import subprocess
import sys
import time


def _require(pkg):
    try:
        return __import__(pkg)
    except Exception as e:
        raise RuntimeError(f"缺少依赖 {pkg}: {e}")


def desktop_action(action: str, params: dict):
    """按 Windows 原生桌面操控执行。返回 dict{ok, result, error}。"""
    action = (action or "").lower()

    try:
        import pyautogui
        pyautogui.PAUSE = 0.2
    except Exception as e:
        return {"ok": False, "error": f"pyautogui 不可用: {e}"}

    try:
        if action == "open":
            app = params.get("app") or params.get("path") or ""
            if not app:
                return {"ok": False, "error": "open 需要 app 名(如 notepad)或 exe 路径"}
            # 用 subprocess 打开(程序 / 文件 / URL 都能打开)
            try:
                subprocess.Popen(["cmd", "/c", "start", "", app], shell=True)
                time.sleep(1)
                return {"ok": True, "result": f"已启动: {app}"}
            except Exception as e:
                return {"ok": False, "error": f"启动失败: {e}"}

        elif action == "click":
            x = params.get("x")
            y = params.get("y")
            if x is not None and y is not None:
                pyautogui.click(int(x), int(y))
                return {"ok": True, "result": f"点击 ({x},{y})"}
            # 点击窗口中心的图片/按钮 by coords 未提供则报错
            return {"ok": False, "error": "click 需要 x,y 坐标"}

        elif action == "move":
            x = params.get("x")
            y = params.get("y")
            if x is None or y is None:
                return {"ok": False, "error": "move 需要 x,y"}
            pyautogui.moveTo(int(x), int(y), duration=0.2)
            return {"ok": True, "result": f"鼠标移到 ({x},{y})"}

        elif action == "type":
            text = params.get("text", "")
            if not text:
                return {"ok": False, "error": "type 需要 text"}
            pyautogui.write(text, interval=0.03)
            return {"ok": True, "result": f"已输入: {text[:30]}"}

        elif action == "key":
            key = params.get("key", "")
            if not key:
                return {"ok": False, "error": "key 需要键名(如 enter/ctrl+s)"}
            pyautogui.hotkey(*[k.strip() for k in key.split("+")])
            return {"ok": True, "result": f"已按下: {key}"}

        elif action == "screenshot":
            save = params.get("save") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_desktop_shot.png")
            img = pyautogui.screenshot()
            img.save(save)
            return {"ok": True, "result": f"已截图: {save}"}

        elif action == "windows":
            try:
                import pygetwindow as gw
                titles = [w.title for w in gw.getAllWindows() if w.title and w.title.strip()]
                # 去重保序
                seen, uniq = set(), []
                for t in titles:
                    if t not in seen:
                        seen.add(t); uniq.append(t)
                return {"ok": True, "result": uniq[:30]}
            except Exception as e:
                return {"ok": False, "error": f"列出窗口失败: {e}"}

        elif action == "activate":
            # 按标题激活窗口
            title = params.get("title", "")
            if not title:
                return {"ok": False, "error": "activate 需要 title"}
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(title)
                if not wins:
                    return {"ok": False, "error": f"未找到窗口: {title}"}
                wins[0].activate()
                return {"ok": True, "result": f"已激活窗口: {title}"}
            except Exception as e:
                return {"ok": False, "error": f"激活失败: {e}"}

        return {"ok": False, "error": f"未知桌面操作: {action}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def register(dispatch):
    """把 desktop 工具注册进 dispatch 调度桥。"""
    @dispatch.tool("desktop", owner="windows_desktop")
    def _desktop(params):
        action = params.get("action", "")
        if not action:
            return {"ok": False, "error": "缺少 action（open/click/type/key/screenshot/windows/activate/move）"}
        return desktop_action(action, params)
    return _desktop
