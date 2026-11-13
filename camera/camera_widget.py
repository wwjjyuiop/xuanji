"""
玄机 · 摄像头模块 camera/camera_widget.py（方案二拆分第2刀）
============================================================
把摄像头实时画面组件 CameraWidget 从 window.py 拆出成独立模块。
逻辑零改动，仅移动位置。window.py 改为 `from camera.camera_widget import CameraWidget`。

作用：摄像头属于"四肢"（感知外设），拆出后改摄像头代码不影响心脏/主窗口。
"""

import time

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QImage, QPixmap,
)

# 摄像头依赖 cv2，缺失时允许降级（不阻塞窗口）
try:
    import cv2
    _CV2_OK = True
except ImportError:
    cv2 = None
    _CV2_OK = False


class CameraWidget(QWidget):
    """显示摄像头实时画面"""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background-color: #1a1a2e; border-radius: 10px;")
        self._frame = None
        self._camera = None
        self._running = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)

    def start_camera(self):
        if self._running:
            return
        if cv2 is None:
            print("[摄像头] cv2 未安装，无法开启摄像头")
            return
        try:
            self._camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not self._camera.isOpened():
                print("[摄像头] 无法打开摄像头")
                return
            self._running = True
            self._timer.start(30)
            print("[摄像头] 已开启")
        except Exception as e:
            print("[摄像头] 打开失败: " + str(e))

    def stop_camera(self):
        self._running = False
        self._timer.stop()
        if self._camera:
            self._camera.release()
            self._camera = None
        self._frame = None
        self.update()

    def _update_frame(self):
        if not self._camera or not self._running:
            return
        ret, frame = self._camera.read()
        if not ret or frame is None:
            return
        frame = cv2.flip(frame, 1)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._frame = frame
        self.update()

    def get_frame_jpeg_b64(self):
        """返回当前帧的JPEG base64（摄像头开着且读到帧时），否则None"""
        if self._frame is None or cv2 is None:
            return None
        try:
            import base64 as _b64
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(self._frame, cv2.COLOR_RGB2BGR),
                                   [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                return None
            return _b64.b64encode(buf.tobytes()).decode("utf-8")
        except Exception:
            return None

    def is_running(self):
        return self._running

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 透明 HUD 底，青黑
        painter.setBrush(QBrush(QColor(4, 12, 16, 200)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)

        if self._frame is not None:
            h, w, ch = self._frame.shape
            bytes_per_line = w * ch
            qimg = QImage(self._frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg).scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            x = (self.width() - pix.width()) // 2
            y = (self.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
        else:
            painter.setPen(QColor(0, 229, 255, 160))
            font = QFont("Microsoft YaHei", 12)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "LIVE 摄像头\n按 Ctrl+C 开启")

        # ─── HUD 战术取景框：四角扫描线 + 呼吸青光框 ───
        _w, _h = self.width(), self.height()
        _L = 24
        _p = 10  # 角线离边距离
        t = (time.time() * 1.2) % 4.0
        glow = 120 + int(90 * abs(1 - (t / 2)))  # 呼吸强度
        painter.setPen(QPen(QColor(0, 229, 255, glow), 2))
        # 四角横线-竖线
        painter.drawLine(_p, _p, _p + _L, _p)          # 左上横
        painter.drawLine(_p, _p, _p, _p + _L)          # 左上竖
        painter.drawLine(_w - _p - _L, _p, _w - _p, _p)  # 右上横
        painter.drawLine(_w - _p, _p, _w - _p, _p + _L)  # 右上竖
        painter.drawLine(_p, _h - _p, _p + _L, _h - _p)  # 左下横
        painter.drawLine(_p, _h - _p, _p, _h - _p - _L)  # 左下竖
        painter.drawLine(_w - _p - _L, _h - _p, _w - _p, _h - _p)  # 右下横
        painter.drawLine(_w - _p, _h - _p, _w - _p, _h - _p - _L)  # 右下竖
        # 顶部标签条(横线贯穿 REC 左右两侧，刻度尺感)
        painter.setPen(QPen(QColor(0, 229, 255, 220), 1))
        painter.drawLine(_p + _L, _p + 2, _p + _L + 70, _p + 2)
        painter.setPen(QColor(0, 229, 255, 240))
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(_p + _L + 78, _p + 7, "REC")
        # REC 右侧横杠(原缺失)：与左侧横线同高、同风格，形成对称刻度条
        painter.setPen(QPen(QColor(0, 229, 255, 220), 1))
        painter.drawLine(_p + _L + 108, _p + 2, _p + _L + 178, _p + 2)

    def closeEvent(self, event):
        self.stop_camera()
        super().closeEvent(event)
