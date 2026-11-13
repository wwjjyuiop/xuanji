"""
玄机 · 虚拟形象模块 avatar/avatar_widget.py（方案二拆分第3刀）
BreathingAvatar（2D呼吸动画 + 3D/Live2D 动作核心），逻辑零改动仅移位置。
"""

import os
import random
import threading
import http.server
import socketserver
import datetime

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QFont, QRadialGradient, QPen,
)

try:
    import cv2
except ImportError:
    cv2 = None


class BreathingAvatar(QWidget):

    EMOTION_MAP = {
        "happy":    [4, 5, 6],
        "calm":     [0, 3, 6],
        "sad":      [0, 2],
        "question": [1, 3, 4],
        "surprise": [2, 5],
        "love":     [4, 6, 1],
    }

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 280)
        # 透明：让底层 AnimatedBackground 的科技感背景透上来（不再盖黑底）
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self._breath_phase = 0.0
        self._is_speaking = False
        self._current_emotion = "calm"
        self._emotion_idx = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

        self._petals = []

        # ─── 3D 动态形象（延迟加载，不影响主窗口启动） ───
        self._webview = None
        self._l2d_ready = False
        self._l2d_port = 18796
        QTimer.singleShot(500, self._try_init_live2d)

    def set_speaking(self, speaking):
        self._is_speaking = speaking
        if not speaking:
            self._petals.clear()
        self._sync_l2d_speaking()

    def set_emotion(self, emotion):
        if emotion == self._current_emotion:
            return
        self._current_emotion = emotion
        self._emotion_idx = 0
        print("[Avatar] 情感 -> " + emotion)
        self._sync_l2d_emotion()

    def _tick(self):
        self._breath_phase += 0.06
        self._update_petals()
        self.update()

    def _spawn_petal(self):
        return {
            "x": random.randint(0, self.width()),
            "y": -random.randint(10, 40),
            "w": random.randint(8, 16),
            "h": random.randint(4, 8),
            "vy": random.uniform(0.6, 1.8),
            "vx": random.uniform(-0.6, 0.6),
            "rot": random.uniform(0, 360),
            "vr": random.uniform(1, 4),
            "alpha": random.randint(60, 150),
            "color": random.choice([
                (255, 200, 210), (255, 180, 190),
                (240, 170, 200), (255, 210, 220),
            ]),
        }

    def _update_petals(self):
        if not self._is_speaking:
            self._petals.clear()
            return
        if random.random() < 0.15:
            self._petals.append(self._spawn_petal())
        h = self.height()
        kept = []
        for p in self._petals:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["rot"] += p["vr"]
            if p["y"] < h + 20:
                kept.append(p)
        self._petals = kept

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        # 静态立绘已移除，此 Widget 仅作 3D 容器背景。
        # 不填任何背景色：让底层 AnimatedBackground 的科技感光效透上来

    def _draw_glow(self, painter, cx, cy, r, color, alpha):
        g = QRadialGradient(cx, cy, r)
        g.setColorAt(0.0, QColor(*color, alpha))
        g.setColorAt(0.5, QColor(*color, alpha // 3))
        g.setColorAt(1.0, QColor(*color, 0))
        painter.setBrush(QBrush(g))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

    def _draw_fallback(self, painter, w, h):
        cx, cy = w // 2, h // 2
        r = min(w, h) // 3 * (1.0 + 0.03 * np.sin(self._breath_phase))
        g = QRadialGradient(cx, cy, r * 1.5)
        g.setColorAt(0.0, QColor(150, 130, 220, 180))
        g.setColorAt(0.5, QColor(80, 60, 160, 120))
        g.setColorAt(1.0, QColor(20, 10, 40, 0))
        painter.setBrush(QBrush(g))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        hg = QRadialGradient(cx, cy - r * 0.2, r * 0.3)
        hg.setColorAt(0.0, QColor(255, 255, 255, 100))
        hg.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(hg))
        painter.drawEllipse(int(cx - r * 0.3), int(cy - r * 0.2 - r * 0.3),
                           int(r * 0.6), int(r * 0.6))
        painter.setPen(QColor(200, 180, 255, 180))
        f = QFont("Microsoft YaHei", 10)
        painter.setFont(f)
        # 底部不画"玄机"字样（2026-08-16 用户要求去掉）

    # ─── 3D 动态形象（延迟加载，不影响主窗口） ─────────────

    _L2D_SERVER = None
    _L2D_SERVER_THREAD = None

    @staticmethod
    def _ensure_l2d_server(port):
        if BreathingAvatar._L2D_SERVER is not None:
            return True
        # 资源目录从玄机根目录定位（拆到 avatar/ 子目录后，__file__ 在 avatar 下，需向上进一级）
        _rw = os.path.dirname(os.path.abspath(__file__))
        l2d_dir = os.path.join(os.path.dirname(_rw), "3d_viewer")
        if not os.path.isdir(l2d_dir):
            print("[3D] 无3d_viewer资源目录，跳过: " + l2d_dir)
            return False
        try:
            import functools
            class _NoLogHandler(http.server.SimpleHTTPRequestHandler):
                def log_message(self, format, *args):
                    pass
                # 关键：禁用缓存，否则 QWebEngineView 永远加载旧版 index.html
                def end_headers(self):
                    self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    super().end_headers()
            # 关键：显式指定目录为 3d_viewer，否则 serve 的是进程 cwd（玄机根目录）
            handler = functools.partial(_NoLogHandler, directory=l2d_dir)
            server = socketserver.TCPServer(("127.0.0.1", port), handler)
            BreathingAvatar._L2D_SERVER = server
            BreathingAvatar._L2D_SERVER_THREAD = threading.Thread(
                target=server.serve_forever, daemon=True
            )
            BreathingAvatar._L2D_SERVER_THREAD.start()
            print("[3D] HTTP服务器 127.0.0.1:" + str(port))
            return True
        except Exception as e:
            print("[3D] 服务器启动失败:", e)
            return False

    def _try_init_live2d(self):
        try:
            if not self._ensure_l2d_server(self._l2d_port):
                return
            self._webview = QWebEngineView(self)
            self._webview.setStyleSheet("background: transparent; border: none;")
            self._webview.setVisible(False)
            self._webview.page().setBackgroundColor(Qt.transparent)
            # 转发 3D 页面 JS console 到玄机黑窗口 + 落盘文件，便于排查动作/dance 是否真的执行
            # (2026-08-31 方案一：GUI 被 pythonw 隐藏后黑窗口看不到，改同时落盘，外部进程可读文件定位)
            try:
                _self = self
                def _js_log(level, msg, line, srcid):
                    line_txt = "[JS]" + str(msg)
                    print(line_txt)
                    try:
                        # 落盘到玄机根目录（拆到 avatar/ 后需向上进一级），便于外部进程读日志定位动作问题
                        _jlf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_js_console.log")
                        with open(_jlf, "a", encoding="utf-8") as _f:
                            _f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), line_txt))
                    except Exception:
                        pass
                self._webview.page().javaScriptConsoleMessage.connect(_js_log)
            except Exception:
                pass
            self._webview.load(QUrl("http://127.0.0.1:" + str(self._l2d_port) + "/index.html"))
            self._webview.loadFinished.connect(self._on_l2d_loaded)
            print("[3D] 初始化...")
        except Exception as e:
            print("[3D] 初始化失败:", e)
            self._webview = None

    def _on_l2d_loaded(self, ok):
        if not ok:
            print("[3D] 页面加载失败，保持2D静态模式")
            if self._webview:
                self._webview.deleteLater()
                self._webview = None
            return
        print("[3D] 就绪")
        self._l2d_ready = True
        self._webview.setGeometry(0, 0, self.width(), self.height())
        self._webview.setVisible(True)
        self._sync_l2d_speaking()
        self._sync_l2d_emotion()

    def _js(self, code):
        if not self._l2d_ready or not self._webview:
            print("[GUI] _js 被拦截: _l2d_ready=" + str(self._l2d_ready) + " _webview=" + str(self._webview is not None))
            return
        try:
            self._webview.page().runJavaScript(code)
            print("[GUI] _js 已发送代码(" + code[:60] + "...)")
        except Exception as e:
            print("[GUI] _js 执行异常: " + str(e))

    def _sync_l2d_speaking(self):
        v = "true" if self._is_speaking else "false"
        self._js("window.__xuanji3d&&window.__xuanji3d.setSpeaking(" + v + ")")

    def _sync_l2d_emotion(self):
        self._js("window.__xuanji3d&&window.__xuanji3d.setEmotion('" + self._current_emotion + "')")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._l2d_ready and self._webview:
            self._webview.setGeometry(0, 0, self.width(), self.height())


