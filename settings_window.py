"""
玄机 · 设置窗口
功能：人格设定编辑 / 用户画像查看编辑 / 长期记忆列表管理
入口：主窗口左下信息面板"设置"按钮
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QTabWidget, QWidget, QScrollArea,
    QMessageBox, QGroupBox, QFormLayout,
)
from PySide6.QtCore import Qt

import memory_service
import api_config


class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._svc = memory_service.get_service()
        self.setWindowTitle("玄机 · 设置")
        self.resize(560, 620)
        self.setStyleSheet("""
            QDialog { background-color: #0d0a1a; }
            QTabWidget::pane { border: 1px solid #2a2040; background: #12101e; }
            QTabBar::tab { background: #1a1830; color: #8888aa; padding: 8px 18px;
                           border: 1px solid #2a2040; border-bottom: none;
                           border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background: #2a2040; color: #e8d8ff; }
            QLabel { color: #d8d0f0; font-size: 13px; }
            QGroupBox { color: #a898e0; border: 1px solid #2a2040; border-radius: 8px;
                        margin-top: 10px; font-size: 13px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTextEdit, QLineEdit {
                background-color: #1a1830; color: #d8d0f0;
                border: 1px solid #3a3060; border-radius: 6px;
                font-size: 13px; padding: 6px;
            }
            QPushButton {
                background-color: #4a30a0; color: white;
                border: none; border-radius: 6px; font-size: 13px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #5a40b0; }
            QPushButton#danger { background-color: #8a2040; }
            QPushButton#danger:hover { background-color: #a03050; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_persona_tab(), "人格设定")
        self._tabs.addTab(self._build_profile_tab(), "用户画像")
        self._tabs.addTab(self._build_memory_tab(), "长期记忆")
        self._tabs.addTab(self._build_apikey_tab(), "API 配置")

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        root.addLayout(btn_row)

        self._refresh_all()

    # ─── Tab1 人格设定 ───
    def _build_persona_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        tip = QLabel("在这里编辑玄机的人格设定，保存后立即生效（下一轮对话起）")
        tip.setStyleSheet("color: #8888aa; font-size: 12px;")
        lay.addWidget(tip)

        self._persona_edit = QTextEdit()
        self._persona_edit.setPlaceholderText("输入人格设定...")
        lay.addWidget(self._persona_edit, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        self._save_persona_btn = QPushButton("保存人格")
        self._save_persona_btn.clicked.connect(self._save_persona)
        row.addWidget(self._save_persona_btn)
        lay.addLayout(row)
        return w

    def _save_persona(self):
        text = self._persona_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "人格设定不能为空")
            return
        self._svc.set_personality(text)
        QMessageBox.information(self, "已保存", "人格设定已保存，下一轮对话生效。")

    # ─── Tab2 用户画像 ───
    def _build_profile_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        tip = QLabel("玄机记住的关于你的信息（对话中自动提取，也可手动修改）")
        tip.setStyleSheet("color: #8888aa; font-size: 12px;")
        lay.addWidget(tip)

        box = QGroupBox("用户画像")
        form = QFormLayout(box)
        form.setSpacing(8)
        self._profile_edits = {}
        labels = [("name", "姓名"), ("nickname", "昵称"), ("city", "城市"),
                  ("occupation", "职业"), ("hobbies", "爱好"), ("otherInfo", "其他")]
        for key, label in labels:
            edit = QLineEdit()
            form.addRow(label, edit)
            self._profile_edits[key] = edit
        lay.addWidget(box)

        row = QHBoxLayout()
        row.addStretch()
        self._save_profile_btn = QPushButton("保存画像")
        self._save_profile_btn.clicked.connect(self._save_profile)
        row.addWidget(self._save_profile_btn)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _save_profile(self):
        for key, edit in self._profile_edits.items():
            val = edit.text().strip()
            if val:
                self._svc.update_profile(key, val)
        QMessageBox.information(self, "已保存", "用户画像已更新。")

    # ─── Tab3 长期记忆 ───
    def _build_memory_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        tip = QLabel("玄机记住的重要事情（对话中自动提取，最多50条）")
        tip.setStyleSheet("color: #8888aa; font-size: 12px;")
        lay.addWidget(tip)

        self._mem_list = QTextEdit()
        self._mem_list.setReadOnly(True)
        lay.addWidget(self._mem_list, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        self._clear_mem_btn = QPushButton("清空记忆")
        self._clear_mem_btn.setObjectName("danger")
        self._clear_mem_btn.clicked.connect(self._clear_memories)
        row.addWidget(self._clear_mem_btn)
        lay.addLayout(row)
        return w

    def _clear_memories(self):
        ret = QMessageBox.question(
            self, "确认清空", "确定要清空所有长期记忆吗？（用户画像也会清空）")
        if ret == QMessageBox.Yes:
            self._svc.clear_memories()
            for edit in self._profile_edits.values():
                edit.clear()
            self._refresh_memory_tab()
            QMessageBox.information(self, "已清空", "长期记忆已清空。")

    # ─── Tab4 API 配置（主推理 + 辅助多模态 Key） ───
    def _build_apikey_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        tip = QLabel("配置模型 API Key。保存后立即生效，无需重启。")
        tip.setStyleSheet("color: #8888aa; font-size: 12px;")
        lay.addWidget(tip)

        box = QGroupBox("模型 API")
        form = QFormLayout(box)
        form.setSpacing(10)

        # 主推理模型(DeepSeek)
        self._deepseek_key_edit = QLineEdit()
        self._deepseek_key_edit.setEchoMode(QLineEdit.Password)  # 隐藏显示
        self._deepseek_key_edit.setPlaceholderText("sk-...")
        form.addRow("主推理 Key (DeepSeek)", self._deepseek_key_edit)

        # 辅助多模态(千问)
        self._qwen_key_edit = QLineEdit()
        self._qwen_key_edit.setEchoMode(QLineEdit.Password)
        self._qwen_key_edit.setPlaceholderText("sk-...")
        form.addRow("多模态 Key (千问)", self._qwen_key_edit)

        lay.addWidget(box)

        # 打包提示
        pack_tip = QLabel(
            "打包给他人使用：请清空上方两个 Key 再分发，\n"
            "让对方填自己的 Key 即可运行（无需改代码）。\n"
            "可用目录下 prepare_package.py 一键清空。")
        pack_tip.setStyleSheet("color: #9a88c8; font-size: 12px;")
        pack_tip.setWordWrap(True)
        lay.addWidget(pack_tip)

        row = QHBoxLayout()
        # 显示/隐藏明文
        self._show_key_btn = QPushButton("显示")
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.clicked.connect(self._toggle_key_visibility)
        row.addWidget(self._show_key_btn)
        row.addStretch()
        self._save_apikey_btn = QPushButton("保存 Key")
        self._save_apikey_btn.clicked.connect(self._save_apikey)
        row.addWidget(self._save_apikey_btn)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _toggle_key_visibility(self):
        mode = QLineEdit.Normal if self._show_key_btn.isChecked() else QLineEdit.Password
        self._deepseek_key_edit.setEchoMode(mode)
        self._qwen_key_edit.setEchoMode(mode)
        self._show_key_btn.setText("隐藏" if self._show_key_btn.isChecked() else "显示")

    def _save_apikey(self):
        ds = self._deepseek_key_edit.text().strip()
        qw = self._qwen_key_edit.text().strip()
        # 允许保存任意内容；留空表示清除对应 Key
        api_config.save_deepseek_key(ds)
        api_config.save_qwen_key(qw)
        msg = "API Key 已保存并生效。"
        if not ds and not qw:
            msg += "\n两个 Key 均为空（适合打包给他人）。"
        QMessageBox.information(self, "已保存", msg)

    # ─── 刷新 ───
    def _refresh_all(self):
        self._persona_edit.setPlainText(self._svc.get_personality())
        prof = self._svc.get_profile()
        for key, edit in self._profile_edits.items():
            edit.setText(prof.get(key, ""))
        # 预填 API Key（主推理 + 多模态）
        ds, qw = api_config.load()
        self._deepseek_key_edit.setText(ds)
        self._qwen_key_edit.setText(qw)
        self._refresh_memory_tab()

    def _refresh_memory_tab(self):
        mems = self._svc.get_memories()
        if not mems:
            self._mem_list.setPlainText("（还没有记忆，多聊聊天就会有了）")
            return
        lines = []
        for i, m in enumerate(mems, 1):
            lines.append("%d. %s\n   （%s）" % (i, m.get("content", ""), m.get("time", "")))
        self._mem_list.setPlainText("\n".join(lines))
