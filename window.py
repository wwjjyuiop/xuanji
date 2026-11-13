"""
玄机 GUI · 主窗口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
主框架包含四大区域：

  1. 摄像头画面（显示你的实时视频）
  2. 虚拟形象（呼吸动画，说话时闪烁）
  3. 聊天框（文字输入 + 文字回复）
  4. 语音对话（打开后直接说话，直接回复）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import os
import threading
import time
import struct
import wave
import io
import random
import http.server
import socketserver
import datetime
from collections import deque

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QLineEdit, QPushButton, QSplitter,
    QApplication, QFrame, QStackedWidget,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QUrl, QThread
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import (
    QFont, QAction, QKeySequence, QImage, QPixmap, QPainter,
    QColor, QBrush, QLinearGradient, QRadialGradient, QFontMetrics,
    QPainterPath, QPen,
)

import memory_service
import settings_window
import ability_panel
import coach_channel

# 摄像头组件（方案二第2刀：从 window.py 拆到独立模块 camera/camera_widget.py）
from camera.camera_widget import CameraWidget
from avatar.avatar_widget import BreathingAvatar
from voice.voice_engine import VoiceEngine

# 语音依赖（无key时允许降级，窗口依然能打开）
try:
    import sounddevice as sd
    import numpy as np
    import cv2
    _VOICE_AVAILABLE = True
except ImportError:
    _VOICE_AVAILABLE = False

try:
    from voice_input import VoiceInput
    from voice_output import VoiceOutput
    _VOICE_IMPORT_OK = True
except (ImportError, RuntimeError) as e:
    print("[GUI] 语音模块加载失败（窗口仍可正常使用）: " + str(e))
    _VOICE_IMPORT_OK = False

    # 兜底定义
    class VoiceInput:
        def transcribe_audio(self, audio_data): return None
    class VoiceOutput:
        def synthesize(self, text): return None
from connector import send_message, ping, describe_image
from connector import set_action_callback as _set_action_callback
from connector import set_play_callback as _set_play_callback


# ─── 参数 ──────────────────────────────────────

SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES_PER_BUFFER = 1024
DTYPE = "int16"

VOICE_THRESHOLD = 300
SILENCE_DURATION = 1.5
MIN_VOICE_DURATION = 0.5
MAX_RECORD_DURATION = 15
VOICE_CONFIRM_CHUNKS = 2
INTERRUPT_THRESHOLD = 800

# ─── 播放锁 ──────────────────
_PLAYBACK_LOCK = threading.Lock()


# ═══════════════════════════════════════════════
#  区域1: 摄像头画面
# ═══════════════════════════════════════════════

#  情感分析
# ═══════════════════════════════════════════════

from sentiment import analyze_sentiment

#  区域2: 虚拟形象
# ═══════════════════════════════════════════════

class _ChatSendWorker(QThread):
    """把发送这件事扔到独立线程，窗口线程不再被 send_message 的网络等待卡死。"""

    done = Signal(str)

    def __init__(self, text, visual=None, image=None, parent=None):
        super().__init__(parent)
        self._text = text
        self._visual = visual
        self._image = image

    def run(self):
        try:
            reply = send_message(self._text, visual=self._visual, image=self._image)
        except Exception as e:
            print("[GUI] 发送线程异常: " + str(e))
            reply = None
        self.done.emit(reply or "")


class ChatPanel(QWidget):
    """半透明对话浮层：叠在玄机形象前方，无独立方框，磨砂玻璃+霓虹描边"""

    send_text = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        # ─── 半透明对话区（无实心底色，靠整体半透明+边角光） ───
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setFrameStyle(0)   # 无边框
        self.chat_log.viewport().setAutoFillBackground(False)
        self.chat_log.setAttribute(Qt.WA_TranslucentBackground, True)
        self.chat_log.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: #eaffff;
                border: none;
                font-size: 15px;
                font-family: "Microsoft YaHei";
                padding: 4px;
            }
            QTextEdit::viewport { background: transparent; }
        """)
        layout.addWidget(self.chat_log, stretch=1)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入文字，按回车发送…")
        self.input_box.setStyleSheet("""
            QLineEdit {
                background: rgba(4, 12, 16, 0.55);
                color: #eaffff;
                border: 1px solid #00e5ff;
                border-radius: 18px;
                font-size: 14px;
                padding: 8px 16px;
            }
            QLineEdit:focus {
                border: 1px solid #ffc107;
                background: rgba(4, 12, 16, 0.72);
            }
        """)
        self.input_box.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_box, stretch=1)

        self.send_btn = QPushButton(">>")
        self.send_btn.setToolTip("发送")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #00e5ff, stop:1 #00b3a0);
                color: #03141a;
                border: none;
                border-radius: 18px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #ffc107, stop:1 #00e5ff);
            }
        """)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)
        layout.addLayout(input_layout)

    def paintEvent(self, event):
        # 磨砂半透明圆角面板 + 霓虹(青/金)描边，仅作悬浮背景，不挡形象
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 22, 22)
        p.fillPath(path, QColor(2, 8, 12, 130))
        p.setPen(QPen(QColor(0, 229, 255, 150), 1.5))
        p.drawPath(path)

    def _on_send(self):
        text = self.input_box.text().strip()
        if text:
            self.send_text.emit(text)
            self.input_box.clear()

    def append_user(self, text):
        self.chat_log.append('<span style="color:#00e5ff;">► 你：</span>' + text)

    def append_bot(self, text):
        self.chat_log.append('<span style="color:#ffc107;">✨ 玄机：</span>' + text)

    def append_system(self, text):
        self.chat_log.append('<span style="color:rgba(148,190,210,0.8);font-style:italic;">' + text + '</span>')

    def _on_send(self):
        text = self.input_box.text().strip()
        if text:
            self.send_text.emit(text)
            self.input_box.clear()


# ═══════════════════════════════════════════════
#  语音引擎
# ═══════════════════════════════════════════════

class CyberHUD(QWidget):
    """右侧统一 HUD 面板：摄像头 ＋ 操作按钮 ＋ 真实数据仪表（拉高拉宽，不遮挡形象主体）"""

    def __init__(self, camera=None, on_view=None, on_settings=None, on_ability=None):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setObjectName("cyberHUD")
        self.setFixedWidth(300)
        self.setMinimumHeight(430)
        self.setMaximumHeight(500)
        self._t0 = time.time()
        self._fps = 60.0
        self._fps_acc = 0
        self._fps_ts = time.time()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)

        # ── 标题 ──
        title = QLabel("◈ SYSTEM // 玄机")
        title.setStyleSheet("color:#00e5ff; font-size:13px; font-weight:bold; font-family:Consolas; background:transparent;")
        lay.addWidget(title)

        # ── 摄像头 HUD 小窗 ──
        if camera is not None:
            self._camera = camera
            camera.setFixedSize(268, 150)
            cam_box = QFrame()
            cam_box.setStyleSheet("QFrame{background:rgba(2,10,14,220); border:1px solid rgba(0,229,255,0.6); border-radius:8px;}")
            cb = QVBoxLayout(cam_box)
            cb.setContentsMargins(6, 6, 6, 6)
            cb.addWidget(camera)
            cb.addWidget(QLabel("Ctrl+C 摄像头 / Ctrl+V 语音开关"))
            for i in range(cb.count()):
                it = cb.itemAt(i)
                wgt = it.widget()
                if isinstance(wgt, QLabel):
                    wgt.setStyleSheet("color:rgba(0,229,255,0.75); font-size:10px; font-family:Microsoft YaHei; background:transparent;")
                    wgt.setAlignment(Qt.AlignCenter)
            lay.addWidget(cam_box)

        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for label, fn, is_view in [("显示", on_view, True), ("设置", on_settings, False), ("能力", on_ability, False)]:
            b = QPushButton(label)
            b.setStyleSheet("""
                QPushButton {
                    background: rgba(2,10,14,0.7);
                    color:#abf3ff;
                    border:1px solid rgba(0,229,255,0.55);
                    border-radius:6px;
                    font-size:12px;
                    padding:6px 0;
                }
                QPushButton:hover { border:1px solid #ffc107; color:#ffc107; background:rgba(2,10,14,0.9); }
            """)
            if is_view and fn is not None:
                self._view_btn = b
            if fn is not None:
                b.clicked.connect(fn)
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background:#ffc107; border:none;")
        lay.addWidget(sep)

        # ── 状态行 ──
        self._conn_label = QLabel("● 连接中...")
        self._conn_label.setStyleSheet("color:#ffc107; font-size:12px; font-family:Consolas; background:transparent;")
        lay.addWidget(self._conn_label)

        # ── 真实数据仪表（独立绘制区） ──
        self._metrics = MetricsArea(self)
        self._metrics.setFixedHeight(190)
        lay.addWidget(self._metrics)
        lay.addStretch()

        self.setStyleSheet("QWidget#cyberHUD{background:rgba(2,10,16,150);}")

        # 每 800ms 刷新真实数据
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(800)

    # ── 供外部刷新连接状态 ──
    def set_connection(self, text, ok):
        col = "#00e5ff" if ok else "#ff6b6b"
        self._conn_label.setText(text)
        self._conn_label.setStyleSheet("color:%s; font-size:12px; font-family:Consolas; background:transparent;" % col)

    def _tick(self):
        self._fps_acc += 1
        now = time.time()
        if now - self._fps_ts >= 1.0:
            self._fps = self._fps_acc / (now - self._fps_ts)
            self._fps_acc = 0
            self._fps_ts = now
        self._metrics.update()

    def _paint_metrics(self, p, w, h):
        # 实时指标（真实值）
        mems = 0
        prof = 0
        try:
            import memory_service as _ms
            svc = _ms.get_service()
            mems = len(svc.get_memories())
            prof = sum(1 for v in svc.get_profile().values() if v)
        except Exception:
            pass
        sess = int(time.time() - self._t0)
        hh, mm = sess // 3600, (sess % 3600) // 60
        rows = [
            ("记忆条目", str(mems), QColor(255, 193, 7)),
            ("画像完成", str(prof) + " / 6", QColor(0, 229, 255)),
            ("帧率", "%d fps" % int(self._fps), QColor(255, 193, 7)),
            ("会话时长", "%02d:%02d" % (hh, mm), QColor(0, 229, 255)),
        ]
        y = 14
        for label, val, col in rows:
            p.setPen(QColor(140, 200, 215, 200))
            p.setFont(QFont("Microsoft YaHei", 11))
            p.drawText(8, y, label)
            p.setPen(col)
            p.setFont(QFont("Consolas", 12, QFont.Bold))
            p.drawText(w - 8 - p.fontMetrics().horizontalAdvance(val), y, val)
            p.setPen(QColor(0, 229, 255, 60))
            p.drawLine(8, y + 7, w - 8, y + 7)
            y += 30

    def paintEvent(self, event):
        # 面板外框描边（青金）
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)
        p.setPen(QPen(QColor(0, 229, 255, 120), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        super().paintEvent(event)


class MetricsArea(QWidget):
    """真实数据绘制区（独立子控件，避免刷新整个HUD）"""

    def __init__(self, hud):
        super().__init__()
        self._hud = hud
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        zh = getattr(self, "_hud", None)
        if zh is not None:
            zh._paint_metrics(p, self.width(), self.height())


class LeftHUD(QWidget):
    """左侧实时活动日志 HUD：滚动显示玄机实时动态（对话/记忆/学习/系统事件），科技感监控台"""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setObjectName("leftHUD")
        self.setFixedWidth(240)
        self.setMinimumHeight(260)
        self.setMaximumHeight(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        title = QLabel("◈ 实时活动 // 玄机日志")
        title.setStyleSheet("color:#00e5ff; font-size:12px; font-weight:bold; font-family:Consolas; background:transparent;")
        lay.addWidget(title)
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background:#ffc107; border:none;")
        lay.addWidget(sep)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFrameStyle(0)
        self._log.viewport().setAutoFillBackground(False)
        self._log.setAttribute(Qt.WA_TranslucentBackground, True)
        self._log.setStyleSheet("""
            QTextEdit { background: transparent; color:#abf3ff; border:none;
                        font-size:11px; font-family:Consolas; }
        """)
        self._log.append('<span style="color:#00e5ff;">[系统] 玄机日志初始化</span>')
        lay.addWidget(self._log, stretch=1)

        self.setStyleSheet("QWidget#leftHUD{background:rgba(2,10,16,140);}")

    def add_log(self, text, color="#abf3ff"):
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        self._log.append('<span style="color:rgba(0,229,255,0.5);">[' + ts + ']</span> <span style="color:' + color + ';">' + text + '</span>')
        # 限长 100 行（保留最老行下面的最新内容）
        while self._log.document().blockCount() > 100:
            cur = self._log.textCursor()
            cur.movePosition(cur.MoveOperation.Start)
            cur.movePosition(cur.MoveOperation.Down, cur.MoveMode.KeepAnchor)
            cur.removeSelectedText()
        # 自动滚到底部：新日志追加后始终看到最新一行，不被未更新滚动条挡住
        try:
            sb = self._log.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())
            else:
                self._log.moveCursor(self._log.textCursor().MoveOperation.End)
        except Exception:
            pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)
        p.setPen(QPen(QColor(0, 229, 255, 110), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        super().paintEvent(event)


class AnimatedBackground(QWidget):
    """动态科技感背景：深蓝渐变 + 网格 + 流动光带 + 脉动光晕（垫在形象底下，QTimer驱动）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0
        self._stars = []
        import random as _r
        self._rnd = _r
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)  # 25fps 动画
        self._timer.timeout.connect(self._maybe_spawn_star)

    def _tick(self):
        self._t += 0.025
        # 星星上浮
        for s in self._stars:
            s["y"] -= s["vy"]
        self._stars = [s for s in self._stars if s["y"] > -8]
        self.update()

    def _maybe_spawn_star(self):
        w = self.width()
        if w <= 0:
            return
        if self._rnd.random() < 0.35:
            self._stars.append({
                "x": self._rnd.randint(0, w),
                "y": self._rnd.randint(int(self.height() * 0.6), self.height()),
                "vy": self._rnd.uniform(1.0, 3.0),
                "r": self._rnd.uniform(1.0, 2.6),
                "bright": self._rnd.randint(120, 230),
                "color": self._rnd.choice([
                    (0, 229, 255), (255, 193, 7), (170, 235, 255),
                ]),
            })

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # ── 暗冷灰蓝渐变底（与玄机3D小背景色调统一） ──
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor(16, 26, 50))
        g.setColorAt(0.5, QColor(12, 18, 38))
        g.setColorAt(0.85, QColor(8, 12, 28))
        g.setColorAt(1.0, QColor(6, 8, 20))
        p.fillRect(self.rect(), QBrush(g))

        # ── 发光网格（暗青，弱化，跟小背景网格色调协调） ──
        p.setPen(QPen(QColor(60, 110, 155, 70), 1))
        step = 46
        x = step
        while x < w:
            p.drawLine(x, 0, x, h)
            x += step
        y = step
        while y < h:
            p.drawLine(0, y, w, y)
            y += step

        # ── 横向流动光带（暗青+暗金，低调扫描） ──
        band = int((self._t * 55) % (h + 320)) - 160
        pg = QLinearGradient(0, 0, w, 0)
        pg.setColorAt(0.0, QColor(60, 110, 155, 0))
        pg.setColorAt(0.4, QColor(70, 125, 175, 120))
        pg.setColorAt(0.55, QColor(150, 120, 40, 90))
        pg.setColorAt(0.7, QColor(70, 125, 175, 120))
        pg.setColorAt(1.0, QColor(60, 110, 155, 0))
        p.setBrush(QBrush(pg))
        p.setPen(Qt.NoPen)
        p.drawRect(0, band, w, 60)

        # ── 底部能量光带（暗金，弱） ──
        bg = QLinearGradient(0, h - 140, 0, h)
        bg.setColorAt(0.0, QColor(150, 120, 40, 0))
        bg.setColorAt(0.5, QColor(60, 110, 155, 70))
        bg.setColorAt(1.0, QColor(150, 120, 40, 120))
        p.setBrush(QBrush(bg))
        p.drawRect(0, h - 150, w, 150)

        # ── 中央呼吸光晕（暗蓝，柔和衬托形象） ──
        cx, cy = w * 0.5, h * 0.52
        r = min(w, h) * 0.62
        pulse = 0.55 + 0.15 * ((self._t * 2) % 1.0)
        rg = QRadialGradient(cx, cy, r * pulse)
        rg.setColorAt(0.0, QColor(80, 130, 180, 80))
        rg.setColorAt(0.35, QColor(40, 70, 120, 55))
        rg.setColorAt(0.75, QColor(20, 35, 70, 30))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - r * pulse), int(cy - r * pulse),
                      int(r * 2 * pulse), int(r * 2 * pulse))

        # ── 数据粒子星星（暗青/暗金，低调闪烁） ──
        for s in self._stars:
            a = s["bright"]
            # 把星星颜色也压暗，统一色调
            cc = s["color"]
            dc = (cc[0] // 2, cc[1] // 2, cc[2] // 2)
            p.setPen(QPen(QColor(*dc, a), 1))
            p.setBrush(QBrush(QColor(*dc, a)))
            p.drawEllipse(int(s["x"] - s["r"]), int(s["y"] - s["r"]),
                          int(s["r"] * 2), int(s["r"] * 2))


class MainWindow(QMainWindow):
    _play_requested = Signal(str)   # 跨线程安全：语音线程 → 主线程投递 3D 动作
    _eval_js_requested = Signal(str)  # 跨线程安全：诊断用，把 JS 丢进 3D 页面执行
    _sig_state = Signal(str)
    _sig_error = Signal(str)
    _sig_user_text = Signal(str)
    _sig_bot_text = Signal(str)
    _sig_speaking = Signal(bool)
    _sig_emotion = Signal(str)
    # 黑窗口 stdout 嵌入 GUI 日志框：任意线程 print → 信号 → 主线程槽 → add_log
    _sig_console = Signal(str)
    # 连接状态跨线程桥：后台线程 ping 完 → 信号 → 主线程改控件（2026 修"连接中"卡死）
    _sig_conn = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("玄机 GUI")
        self.setMinimumSize(1080, 700)
        self.resize(1360, 820)
        self._view_mode = 'full'

        self._voice_in = VoiceInput()
        self._voice_out = VoiceOutput()
        self._engine = VoiceEngine(self._voice_in, self._voice_out)

        self._build_ui()

        # 语音引擎在独立线程运行，直接回调 GUI 会跨线程操作 Qt（runJavaScript 等）
        # 死锁卡死；改用 Signal 桥：线程 emit → Qt 自动排队 → 主线程槽执行
        self._engine.on_state = self._sig_state.emit
        self._engine.on_user_text = self._sig_user_text.emit
        self._engine.on_bot_text = self._sig_bot_text.emit
        self._engine.on_error = self._sig_error.emit
        self._engine.on_speaking = self._sig_speaking.emit
        self._engine.on_emotion = self._sig_emotion.emit
        self._engine.get_visual = self._get_visual_context

        self._sig_state.connect(self._on_state)
        self._sig_error.connect(self._on_error)
        self._sig_user_text.connect(self._on_user_text)
        self._sig_bot_text.connect(self._on_bot_text)
        self._sig_speaking.connect(self._on_speaking)
        self._sig_emotion.connect(self._on_emotion)
        self._sig_conn.connect(self._on_conn_result, Qt.QueuedConnection)

        QTimer.singleShot(500, self._delayed_start)

    def _delayed_start(self):
        self._chat.append_system("语音对话已开启，按 Ctrl+V 可关闭")
        # 黑窗口 stdout 嵌入 GUI 日志框：信号桥（线程安全）
        try:
            self._sig_console.connect(self._on_console_line)
        except Exception as e:
            print("[GUI] 日志桥连接失败(忽略): " + str(e))
        # 把玄机的工具动作实时推送到左边“实时活动”日志显示
        try:
            _set_action_callback(self._on_xuanji_action)
        except Exception as e:
            print("[GUI] 动作日志回调注册失败(忽略): " + str(e))
        # 注册 3D 动作触发回调：connector 让黛玉做动作时，驱动窗口里的黛玉
        try:
            _set_play_callback(self._on_play_action)
            # 2026-09-21 修：QTimer.singleShot 在非主线程静默失效（动作发不出），改用跨线程信号
            self._play_requested.connect(self._do_play_action, Qt.QueuedConnection)
        except Exception as e:
            print("[GUI] 3D动作回调注册失败(忽略): " + str(e))
        # 黑窗口 stdout → GUI 日志框：安装代理，所有 print 同时进左下日志
        self._install_stdout_bridge()
        # ── 玄机现身 · 报平安 ──（门童拉起时留的话，念一次就清掉）
        QTimer.singleShot(800, self._wake_greet)
        # 默认开启语音对话：开机即用，不必按 Ctrl+V（2026-10-15）
        QTimer.singleShot(3500, self._auto_start_voice)

    def _wake_greet(self):
        """读 .wake_greet.json（门童写的），合成语音念出来，然后删标记。"""
        try:
            import json as _json
            _gf = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.wake_greet.json')
            if not os.path.exists(_gf):
                return
            _txt = '公子，我在呢。'
            try:
                _d = _json.loads(io.open(_gf, encoding='utf-8').read())
                if _d.get('text') and abs(time.time() - float(_d.get('ts', 0))) < 180:
                    _txt = _d['text']
            except Exception as _e:
                print('[玄机] 报平安标记解析失败(用默认话): ' + str(_e))
            try:
                os.remove(_gf)
            except Exception:
                pass

            self._chat.append_system(_txt)
            if self._voice_out is None:
                return
            _wav = None
            try:
                _wav = self._voice_out.synthesize(_txt)
            except Exception as _e:
                print('[玄机] 报平安合成失败: ' + str(_e))
            if not _wav:
                return
            _tmp = os.path.join(os.environ.get('TEMP', '.'), '_wake_greet.wav')
            try:
                _wavb = _wav if isinstance(_wav, (bytes, bytearray)) else bytes(_wav)
                _wavb = self._fix_stream_wav(_wavb)   # 2026-10-15 修：假长度头导致 winsound 静默不出声
                with open(_tmp, 'wb') as _f:
                    _f.write(_wavb)
                import winsound
                winsound.PlaySound(_tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
                print('[玄机] 报平安已播出: ' + _txt)
            except Exception as _e:
                print('[玄机] 报平安播放失败: ' + str(_e))
        except Exception as _e:
            print('[玄机] 报平安流程异常: ' + str(_e))
        self._check_connection()
        # 启动教学/运维通道（后台线程；失败不影响窗口）
        try:
            ok = coach_channel.start()
            if ok:
                coach_channel.log("玄机启动，教学通道就绪")
                print("[coach] 教学通道已启动")
            else:
                print("[coach] 教学通道未启动(端口占用或失败)")
        except Exception as e:
            print("[coach] 教学通道初始化异常(忽略): " + str(e))
        # 教学通道 /teach 回调：收到动作名 → 驱动 3D 动作（供 WSL 师傅全自动下发指令，2026-08-31）
        try:
            def _coach_teach(payload):
                try:
                    cmd = str(payload.get("cmd") or "").strip()
                    # 统一用动作定义层校验（方案二第1刀：白名单从 window 抽到 motion/actions.py）
                    from motion.actions import is_valid_action
                    if is_valid_action(cmd):
                        # 2026-09-21 修：coach 的 HTTP 线程里 QTimer 静默失效，与 _on_play_action 一样改用跨线程信号
                        self._play_requested.emit(str(cmd))
                        print("[coach] 已投递挥手/动作到主线程: " + cmd)
                        return {"action": cmd, "dispatched": True}
                    return {"action": cmd or "", "dispatched": False, "note": "非动作指令，已记录"}
                except Exception as e:
                    return {"error": str(e)}
            coach_channel.set_teach_handler(_coach_teach)
            print("[coach] 教学通道已接上挥手/动作执行回调")
        except Exception as e:
            print("[coach] 教学通道动作回调注册失败(忽略): " + str(e))
        # 2026-09-21 加：/eval 只读诊断接口 —— 读 3D 页面内部状态（动作到没到、加载失败没）
        try:
            self._eval_js_requested.connect(self._do_eval_js, Qt.QueuedConnection)

            def _coach_eval(payload):
                js = str((payload or {}).get("js") or "").strip()
                if not js:
                    return {"error": "empty js"}
                self._eval_js_requested.emit(js)
                return {"dispatched": True}

            coach_channel.set_eval_handler(_coach_eval)
            print("[coach] /eval 诊断接口已就绪")
        except Exception as e:
            print("[coach] /eval 注册失败(忽略): " + str(e))

    def _on_xuanji_action(self, text):
        """玄机动了啥 → 推送到左边实时活动日志（简单一行）"""
        try:
            if hasattr(self, "_left_hud"):
                self._left_hud.add_log(text, "#7ad7ff")
        except Exception:
            pass

    def _on_play_action(self, action_name):
        """connector 让黛玉做动作 → 发跨线程信号，由主线程真正执行（2026-09-21 修）"""
        try:
            self._play_requested.emit(str(action_name or ""))
            print("[GUI] 动作已投递主线程: " + str(action_name))
        except Exception as e:
            print("[GUI] 3D动作投递失败: " + str(e))

    def _do_play_action(self, action_name):
        """真正驱动黛玉 3D 播放器做动作（主线程执行）"""
        try:
            if not action_name:
                return
            safe = str(action_name).replace("'", "").replace('"', "")
            print("[GUI] _do_play_action 转发: " + safe)
            self._avatar._js("window.__xuanji3d&&window.__xuanji3d.playAction('" + safe + "')")
            print("[GUI] 黛玉动作 → " + safe)
            # 回读确认（2026-09-21 加）：600ms 后读页面真实状态，画面没播就明确报错，不再假成功
            # 2026-09-21 撤掉：这段延迟回读探针（singleShot+lambda）疑似与 Qt6Gui 崩溃相关（有 crash dump），改由 /eval 诊断接口按需回读
            try:
                if hasattr(self, "_left_hud"):
                    self._left_hud.add_log("黛玉动作 → " + safe, "#ffb4c8")
            except Exception:
                pass
        except Exception as e:
            print("[GUI] 黛玉动作执行失败: " + str(e))

    def _do_eval_js(self, js):
        """诊断用：把一段 JS 丢进 3D 页面执行，结果打到日志（主线程执行）"""
        try:
            if not (self._avatar and self._avatar._webview):
                print("[EVAL] 没有 webview，无法执行")
                return

            def _cb(r):
                try:
                    print("[EVAL] 结果: " + str(r)[:3000])
                except Exception:
                    pass

            self._avatar._webview.page().runJavaScript(js, _cb)
            print("[EVAL] 已下发: " + str(js)[:200])
        except Exception as e:
            print("[EVAL] 异常: " + str(e))

    def _probe_play_action(self, action_name):
        """回读 3D 页面真实状态，判定动作到底播没播（主线程执行）"""
        try:
            if not (self._avatar and self._avatar._webview):
                print("[GUI] ❌ 动作回读失败: webview 不存在")
                return
            if not getattr(self._avatar, "_l2d_ready", False):
                print("[GUI] ❌ 动作回读失败: 3D 页面未就绪")
                return
            js = ("JSON.stringify((window.__xuanji3d && window.__xuanji3d.getState) "
                  "? window.__xuanji3d.getState() : {noGetState:true})")

            def _cb(r):
                try:
                    import json as _json
                    d = _json.loads(r) if isinstance(r, str) else {}
                except Exception:
                    d = {}
                if d.get("noGetState"):
                    print("[GUI] ⚠️ 动作回读: 页面无 getState（页面版本旧）")
                    return
                playing = bool(d.get("playingVmd"))
                cur = str(d.get("curVmdAction") or "")
                last = str(d.get("lastResult") or "")
                if str(action_name) == "stop":
                    ok = (not playing)
                    tag = "✅ 画面确认已停" if ok else "❌ 喊停了但画面还在播"
                else:
                    ok = playing or (str(action_name) in cur) or (str(action_name) in last)
                    tag = "✅ 画面确认在播" if ok else "❌ 画面说没在播（动作没生效）"
                print("[GUI] " + tag + " | 动作=" + str(action_name) + " | " + str(r))

            try:
                self._avatar._webview.page().runJavaScript(js, _cb)
            except Exception as e:
                print("[GUI] 动作回读异常: " + str(e))
        except Exception as e:
            print("[GUI] 动作回读失败: " + str(e))

    def _build_ui(self):
        central = QWidget()
        central.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ─── 动态科技感背景（整窗垫底，纯装饰，不参与交互） ───
        self._bg = AnimatedBackground(central)
        self._bg.setGeometry(central.rect())

        # ═══════════════════════════════════════════
        # 中段：左HUD | 玄机形象 | 右面板（三栏物理不重叠）
        # ═══════════════════════════════════════════
        mid = QHBoxLayout()
        mid.setSpacing(10)

        # 左：实时活动日志 HUD（固定宽，加宽方便看全部黑窗口日志）
        self._left_hud = LeftHUD()
        self._left_hud.setFixedWidth(380)
        mid.addWidget(self._left_hud)

        # 中：玄机 3D 形象（居中，限宽避免占满，往中间缩）
        self._avatar = BreathingAvatar()
        self._avatar.setMaximumWidth(760)
        mid.addWidget(self._avatar, stretch=1)

        # 右：摄像头＋按钮＋数据仪表面板（固定宽）
        self._camera = CameraWidget()
        self._hud = CyberHUD(camera=self._camera,
                             on_view=self._toggle_view_mode,
                             on_settings=self._open_settings,
                             on_ability=self._open_ability)
        mid.addWidget(self._hud)

        root.addLayout(mid, stretch=1)

        # ═══════════════════════════════════════════
        # 底部：对话栏（横跨整窗，独立一行，与形象/HUD 垂直分开、不重叠）
        # ═══════════════════════════════════════════
        self._chat = ChatPanel()
        self._chat.setFixedHeight(170)
        self._chat.send_text.connect(self._on_chat_send)
        root.addWidget(self._chat)

        # 状态栏信息（保持原有接口，隐藏）
        self._status_label = QLabel("就绪")
        self._status_label.setVisible(False)
        self._info_state = QLabel("就绪")
        self._info_state.setVisible(False)
        self._top_state = QLabel("◈ 玄机系统")
        self._top_state.setVisible(False)
        self._info_conn = QLabel("连接：--")
        self._info_conn.setVisible(False)

        self.setStyleSheet("""
            QMainWindow { background: transparent; }
            QWidget { background: transparent; }
        """)
        self._setup_shortcuts()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_bg"):
            self._bg.setGeometry(self.centralWidget().rect())
            self._bg.lower()

    def _setup_shortcuts(self):
        a = QAction(self)
        a.setShortcut(QKeySequence(Qt.Key_F11))
        a.triggered.connect(lambda: self.showFullScreen() if not self.isFullScreen() else self.showNormal())
        self.addAction(a)

        a2 = QAction(self)
        a2.setShortcut(QKeySequence(Qt.Key_Escape))
        a2.triggered.connect(lambda: self.showNormal() if self.isFullScreen() else None)
        self.addAction(a2)

        a3 = QAction(self)
        a3.setShortcut(QKeySequence("Ctrl+C"))
        a3.triggered.connect(self._toggle_camera)
        self.addAction(a3)

        a4 = QAction(self)
        a4.setShortcut(QKeySequence("Ctrl+V"))
        a4.triggered.connect(self._toggle_voice)
        self.addAction(a4)

    def _open_settings(self):
        """打开设置窗口：人格 / 画像 / 长期记忆"""
        win = settings_window.SettingsWindow(self)
        win.exec()

    def _open_ability(self):
        """打开能力状态面板：插件手脚 / 学习图谱 / 会话日志"""
        try:
            win = ability_panel.AbilityPanel(self)
            win.exec()
        except Exception as e:
            print("[能力] 面板打开失败: " + str(e))

    def _toggle_view_mode(self):
        if self._view_mode == 'full':
            self._view_mode = 'bust'
            if hasattr(self, "_top_state"):
                self._top_state.setText("◈ 玄机系统 · 特写")
            self._avatar._js("window.__xuanji3d&&window.__xuanji3d.setViewMode&&window.__xuanji3d.setViewMode('bust')")
        else:
            self._view_mode = 'full'
            if hasattr(self, "_top_state"):
                self._top_state.setText("◈ 玄机系统")
            self._avatar._js("window.__xuanji3d&&window.__xuanji3d.setViewMode&&window.__xuanji3d.setViewMode('full')")

    def _toggle_camera(self):
        if hasattr(self, "_camera_open") and self._camera_open:
            self._camera.stop_camera()
            self._camera_open = False
            self._chat.append_system("摄像头已关闭")
        else:
            self._camera.start_camera()
            self._camera_open = True
            self._chat.append_system("摄像头已开启")

    def _get_visual_context(self):
        """摄像头开着时取当前帧，直接返回 JPEG base64 —— 交给 DeepSeek 亲眼看，不再经千问转述"""
        try:
            if not (hasattr(self, "_camera_open") and self._camera_open):
                return None
            if not self._camera.is_running():
                return None
            return self._camera.get_frame_jpeg_b64()
        except Exception as e:
            print("[视觉] 获取画面失败: " + str(e))
            return None

    @staticmethod
    def _fix_stream_wav(data):
        """CosyVoice 返回的是流式 wav，头里长度写成 0x7FFFFFFF（约 2GB），
        winsound 会当成长文件一直等 → 无声。这里把 RIFF/data 两处长度改成真实值。"""
        try:
            import struct
            b = bytearray(data)
            if b[:4] != b"RIFF":
                return bytes(b)
            struct.pack_into("<I", b, 4, len(b) - 8)
            i = b.find(b"data")
            if i > 0 and i + 8 <= len(b):
                struct.pack_into("<I", b, i + 4, len(b) - i - 8)
            return bytes(b)
        except Exception as e:
            print("[GUI] wav 头修正失败(忽略): " + str(e))
            return data

    def _auto_start_voice(self):
        """默认开启语音对话：玄机一起来就听得见，无需按 Ctrl+V。"""
        try:
            if not self._engine.is_running():
                self._engine.start()
                self._chat.append_system("语音已开启")
        except Exception as e:
            print("[GUI] 默认开启语音失败(忽略): " + str(e))

    def _toggle_voice(self):
        if self._engine.is_running():
            self._engine.stop()
            self._chat.append_system("语音已关闭")
        else:
            self._engine.start()
            self._chat.append_system("语音已开启")

    def _install_stdout_bridge(self):
        """把黑窗口 print 同时转发到 GUI 左下日志框（信号桥，线程安全）+ 落盘文件
        pythonw 无控制台时 sys.stdout 为 None，需要造替代对象接收所有 print。"""
        try:
            import sys
            _logfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_xuanji_stdout.log")

            def _emit_line(text):
                # 落盘：所有 print 追加写进文件，供外部离线排查（2026-08-31 作者要求）
                try:
                    with open(_logfile, "a", encoding="utf-8") as _f:
                        _f.write(text)
                except Exception:
                    pass
                stripped = text.rstrip("\n")
                if stripped and self._left_hud:
                    self._sig_console.emit(stripped)

            if sys.stdout is None:
                # pythonw 无控制台：造一个替代 stdout，承接所有 print → 落盘 + 转发 GUI
                class _FakeStdout(object):
                    def write(self, text):
                        _emit_line(text)
                    def flush(self):
                        pass
                sys.stdout = _FakeStdout()
                if sys.stderr is None:
                    sys.stderr = _FakeStdout()
                print("[GUI] pythonw无stdout，已造替代输出 → 落盘 + 左下日志框")
            else:
                if getattr(sys.stdout, '_xuanji_bridged', False):
                    return
                orig_write = sys.stdout.write
                def _bridge_write(text):
                    try:
                        orig_write(text)
                        _emit_line(text)
                    except Exception:
                        pass
                sys.stdout.write = _bridge_write
                sys.stdout._xuanji_bridged = True
                print("[GUI] 黑窗口日志已接入左下实时日志框 + 落盘 " + _logfile)
        except Exception as e:
            print("[GUI] stdout桥安装失败(忽略): " + str(e))

    def _on_console_line(self, line):
        """收 stdout 一行 → 显示到左下日志框（主线程槽）"""
        try:
            if self._left_hud:
                self._left_hud.add_log(str(line), "#8be9fd")
        except Exception:
            pass

    def _check_connection(self):
        """启动一次连接自检，并挂 10 秒心跳。
        2026 修：ping() 要联网、最长 5 秒，原来在 UI 线程里直接调，
        卡住时界面冻住、"连接中"永远不刷新；改后台线程 + 信号回主线程。"""
        self._net_busy = False

        def probe():
            try:
                alive = bool(ping())
            except Exception as _e:
                print("[连接] 自检异常(按离线算): " + str(_e))
                alive = False
            try:
                self._sig_conn.emit(alive)
            except Exception as _e:
                print("[连接] 状态回传失败: " + str(_e))

        def check():
            # 上一轮还没回来就别叠加线程
            if getattr(self, "_net_busy", False):
                return
            self._net_busy = True

            def run():
                try:
                    probe()
                finally:
                    self._net_busy = False

            threading.Thread(target=run, daemon=True).start()

        check()
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(check)
        self._conn_timer.start(10000)

    @Slot(bool)
    def _on_conn_result(self, alive):
        """后台 ping 结果回主线程 → 只在这里碰控件（线程安全）"""
        try:
            if hasattr(self, "_hud"):
                self._hud.set_connection(
                    "● 系统在线" if alive else "● 离线", alive)
            if hasattr(self, "_info_conn"):
                self._info_conn.setText("连接：已连接" if alive else "连接：未连接")
            if hasattr(self, "_left_hud"):
                self._left_hud.add_log(
                    "系统在线" if alive else "连接丢失",
                    "#00e5ff" if alive else "#ff6b6b")
        except Exception as e:
            print("[连接] 刷新界面失败: " + str(e))

    def _on_chat_send(self, text):
        self._chat.append_user(text)
        self._chat.append_system("思考中...")
        if hasattr(self, "_left_hud"):
            self._left_hud.add_log("收到指令→ " + (text[:20] + "…" if len(text) > 20 else text), "#ffc107")
        image = self._get_visual_context()
        # 关键：这里不再直挺挺地等网络回话，扔到独立线程去跑，回话再贴上来
        if not hasattr(self, "_send_workers"):
            self._send_workers = []
        worker = _ChatSendWorker(text, image=image, parent=self)
        self._send_workers.append(worker)
        worker.done.connect(self._on_chat_reply)
        worker.finished.connect(
            lambda w=worker: self._send_workers.remove(w) if w in self._send_workers else None
        )
        worker.start()

    def _on_chat_reply(self, reply):
        if reply:
            self._chat.append_bot(reply)
            emotion = analyze_sentiment(reply)
            self._avatar.set_emotion(emotion)
            if hasattr(self, "_left_hud"):
                self._left_hud.add_log("玄机回复 · 情感→" + emotion, "#00e5ff")
        else:
            self._chat.append_system("连接异常")
            if hasattr(self, "_left_hud"):
                self._left_hud.add_log("[[异常]] 回复失败", "#ff6b6b")

    def _on_state(self, text):
        self._status_label.setText(text)
        self._info_state.setText(text)

    def _on_user_text(self, text):
        self._chat.append_user(text)

    def _on_bot_text(self, text):
        self._chat.append_bot(text)

    def _on_error(self, text):
        self._status_label.setText(text)
        self._chat.append_system(text)

    def _on_speaking(self, speaking):
        self._avatar.set_speaking(speaking)

    def _on_emotion(self, emotion):
        self._avatar.set_emotion(emotion)

    def closeEvent(self, event):
        self._engine.stop()
        if hasattr(self, "_camera"):
            self._camera.stop_camera()
        super().closeEvent(event)
