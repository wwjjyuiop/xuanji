"""
玄机 · 能力可视化面板 ability_panel.py
============================================================
让玄机 GUI 里能直观看到自己的完整"家底"：
  - 能力总览：手脚插件、内置工具、元能力
  - 插件状态：每个插件/手脚加载状况(来自 dispatch._LOADED_PLUGINS + _TOOL_OWNER)
  - 学习图谱：已沉淀的技能
  - 会话日志：结构化事件统计
入口：主窗口可以加一个按钮打开。

纯 Windows 端读取玄机自己的状态，不依赖任何外部。
"""

import os
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QTextEdit, QGroupBox,
)
from PySide6.QtCore import Qt

_GUI = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_GUI)


def _collect():
    """收集玄机能力状态。返回 dict。"""
    info = {"plugins": [], "tools": [], "tools_owner": {}, "skills": "", "log_stats": {}}
    # 插件与工具
    try:
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        import dispatch
        info["tools"] = dispatch.list_tools()
        info["tools_owner"] = getattr(dispatch, "_TOOL_OWNER", {})
        plugins = sorted(getattr(dispatch, "_LOADED_PLUGINS", {}).keys())
        info["plugins"] = plugins
    except Exception as e:
        info["plugins_err"] = str(e)
    # 学习图谱
    try:
        if _GUI not in sys.path:
            sys.path.insert(0, _GUI)
        import learning_engine
        info["skills"] = learning_engine.learning_graph()
    except Exception as e:
        info["skills_err"] = str(e)
    # 会话日志统计
    try:
        import session_log
        info["log_stats"] = session_log.stats()
    except Exception as e:
        info["log_stats_err"] = str(e)
    return info


class AbilityPanel(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("玄机 · 能力状态")
        self.resize(620, 480)
        self.setStyleSheet("""
            QDialog { background-color: #0d0a1a; }
            QTabWidget::pane { border: 1px solid #2a2040; background: #12101e; }
            QTabBar::tab { background: #1a1830; color: #8888aa; padding: 8px 16px;
                           border: 1px solid #2a2040; border-bottom: none;
                           border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background: #2a2040; color: #e8d8ff; }
            QLabel { color: #d8d0f0; font-size: 13px; }
            QGroupBox { color: #a898e0; border: 1px solid #2a2040; border-radius: 8px;
                        margin-top: 8px; font-size: 13px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTextEdit { background-color: #1a1830; color: #d8d0f0;
                        border: 1px solid #3a3060; border-radius: 6px;
                        font-size: 13px; padding: 6px; }
            QPushButton { background-color: #4a30a0; color: white;
                          border: none; border-radius: 6px; font-size: 13px; padding: 8px 16px; }
            QPushButton:hover { background-color: #5a40b0; }
        """)
        self._info = _collect()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)
        self._tabs.addTab(self._build_overview(), "能力总览")
        self._tabs.addTab(self._build_plugins(), "插件手脚")
        self._tabs.addTab(self._build_learn(), "学习图谱")
        self._tabs.addTab(self._build_log(), "会话日志")
        # 底部关闭
        btn = QPushButton("关闭")
        btn.clicked.connect(self.close)
        hr = QHBoxLayout(); hr.addStretch(); hr.addWidget(btn)
        root.addLayout(hr)

    def _mk_text(self, text):
        te = QTextEdit(); te.setReadOnly(True); te.setPlainText(text)
        return te

    def _build_overview(self):
        w = QWidget(); lay = QVBoxLayout(w)
        tools = self._info.get("tools", [])
        builtin = [t for t in tools if t in ("dir","read_file","write_file","run_cmd","search_file","http_get")]
        hands = [t for t in tools if t not in builtin]
        txt = "你是玄机 —— Windows 端的完整智能体。\n\n"
        txt += "【内置能力】\n" + ", ".join(builtin) + "\n\n"
        txt += "【插件手脚】\n" + ", ".join(hands) if hands else "（无）"
        txt += "\n\n【工具-来源映射】\n"
        for t, o in self._info.get("tools_owner", {}).items():
            txt += f"  {t} <- {o}\n"
        lay.addWidget(self._mk_text(txt))
        return w

    def _build_plugins(self):
        w = QWidget(); lay = QVBoxLayout(w)
        pl = self._info.get("plugins", [])
        txt = "已加载插件(" + str(len(pl)) + ")：\n" + ("\n".join("• " + p for p in pl) if pl else "无")
        if self._info.get("plugins_err"):
            txt += "\n\n[错误] " + self._info["plugins_err"]
        lay.addWidget(self._mk_text(txt))
        return w

    def _build_learn(self):
        w = QWidget(); lay = QVBoxLayout(w)
        skills = self._info.get("skills", "") or "尚无技能"
        lay.addWidget(self._mk_text(str(skills)))
        return w

    def _build_log(self):
        w = QWidget(); lay = QVBoxLayout(w)
        st = self._info.get("log_stats", {})
        txt = "结构化事件日志统计：\n" + ("\n".join(f"  {k}: {v}" for k, v in st.items()) if st else "（空）")
        lay.addWidget(self._mk_text(txt))
        return w
