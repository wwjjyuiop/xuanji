"""
玄机 · 长期记忆服务
存储：人格设定 + 用户画像 + 记忆条目（JSON文件，跨会话持久化）
机制：每聊 N 轮用 AI 自动提取画像/记忆，注入 system prompt（仿拾光）
"""
import json
import os
import threading
import time
from typing import Optional, List, Dict

_MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "记忆库.json")

DEFAULT_PERSONA = "你是玄机，一位温柔的古风少女。直接说话，不要用括号描述动作或表情，不要说'（微笑）''（点头）'之类的东西。只说对话内容本身。如果我在上面提到了'当前画面'的描述，那是你通过摄像头看到的，可以自然地结合画面内容说话，但不要每次都提'我看到'。"

# 默认人格（与 connector.py 原 _SYSTEM_PROMPT 一致，作为可编辑起点）
DEFAULT_PERSONALITY = "温柔的古风少女"

# 经验教训库关键词（方案三 3.5）：改代码/动手前自动匹配提醒
_LESSON_HINTS = ["改", "重构", "修", "写代码", "重写", "拆", "动作"]


class MemoryService:
    def __init__(self, memory_file: Optional[str] = None):
        self._file = memory_file or _MEMORY_FILE
        self._lock = threading.Lock()
        self._data = {
            "personality": DEFAULT_PERSONA,
            "profile": {
                "name": "", "nickname": "", "city": "",
                "occupation": "", "hobbies": "", "otherInfo": "",
            },
            "memories": [],   # [{content, time}]
            "lessons": [],    # 经验教训库（方案三 3.5）：[{content, time, keywords}]
        }
        self._load()

    # ─── 基础读写 ───
    def _load(self):
        try:
            if os.path.isfile(self._file):
                with open(self._file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    if "personality" in loaded:
                        self._data["personality"] = loaded["personality"]
                    if isinstance(loaded.get("profile"), dict):
                        for k, v in loaded["profile"].items():
                            if k in self._data["profile"]:
                                self._data["profile"][k] = v
                    if isinstance(loaded.get("memories"), list):
                        self._data["memories"] = loaded["memories"]
                    if isinstance(loaded.get("lessons"), list):
                        self._data["lessons"] = loaded["lessons"]
        except Exception as e:
            print("[记忆] 加载失败: " + str(e))

    def _save(self):
        try:
            with self._lock:
                tmp = self._file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._file)
        except Exception as e:
            print("[记忆] 保存失败: " + str(e))

    # ─── 人格 ───
    def get_personality(self) -> str:
        return self._data.get("personality", DEFAULT_PERSONA)

    def set_personality(self, text: str):
        self._data["personality"] = text.strip() or DEFAULT_PERSONA
        self._save()

    # ─── 画像 ───
    def get_profile(self) -> Dict:
        return dict(self._data.get("profile", {}))

    def update_profile(self, field: str, value: str):
        if field in self._data["profile"] and value:
            self._data["profile"][field] = value.strip()
            self._save()

    def merge_profile(self, extracted: Dict):
        changed = False
        for k, v in extracted.items():
            if k in self._data["profile"] and v and v != self._data["profile"][k]:
                self._data["profile"][k] = v.strip()
                changed = True
        if changed:
            self._save()

    # ─── 记忆条目 ───
    def get_memories(self) -> List[Dict]:
        return list(self._data.get("memories", []))

    def add_memory(self, content: str):
        content = content.strip()
        if not content or len(content) < 4:
            return
        # 去重（前10字相似视为重复）
        head = content[:10]
        self._data["memories"] = [
            m for m in self._data["memories"]
            if m.get("content", "")[:10] != head
        ]
        self._data["memories"].append({
            "content": content,
            "time": time.strftime("%Y-%m-%d %H:%M"),
        })
        # 最多保留 50 条
        if len(self._data["memories"]) > 50:
            self._data["memories"] = self._data["memories"][-50:]
        self._save()

    def remove_memory(self, index: int):
        try:
            if 0 <= index < len(self._data["memories"]):
                del self._data["memories"][index]
                self._save()
        except Exception:
            pass

    def clear_memories(self):
        self._data["memories"] = []
        self._save()

    # ─── 经验教训库（方案三 · 3.5）───
    def add_lesson(self, content: str, keywords: list = None):
        """记一条经验教训（如"不要把动作全堆同一段"）。keywords 用于开工前匹配。"""
        content = content.strip()
        if not content or len(content) < 4:
            return
        # 去重（前10字相似视为重复）
        head = content[:10]
        self._data["lessons"] = [
            l for l in self._data["lessons"]
            if l.get("content", "")[:10] != head
        ]
        self._data["lessons"].append({
            "content": content,
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "keywords": keywords or [],
        })
        if len(self._data["lessons"]) > 30:
            self._data["lessons"] = self._data["lessons"][-30:]
        self._save()

    def get_lessons(self) -> List[Dict]:
        return list(self._data.get("lessons", []))

    def relevant_lessons(self, task: str) -> List[str]:
        """开工前调用：匹配与 task 相关的教训（关键词命中/内容含词），提醒避坑。
        返回命中教训的文本列表（未命中返回空列表）。"""
        task_l = (task or "").lower()
        hits = []
        for l in self._data.get("lessons", []):
            content = l.get("content", "")
            kws = l.get("keywords", []) or []
            # 关键词命中
            if any(k.lower() in task_l for k in kws):
                hits.append(content)
                continue
            # 内容与任务有共同字词（粗略匹配）
            if any(w in content for w in (task or "").split() if len(w) >= 2):
                hits.append(content)
        return hits

    def clear_lessons(self):
        self._data["lessons"] = []
        self._save()

    def reset_all(self):
        """清空画像+记忆，人格恢复默认"""
        self._data["profile"] = {k: "" for k in self._data["profile"]}
        self._data["memories"] = []
        self._data["personality"] = DEFAULT_PERSONA
        self._save()

    # ─── 生成 system prompt 片段 ───
    def build_context(self) -> str:
        """把画像+记忆拼成注入 system prompt 的文本"""
        parts = []
        prof = self._data["profile"]
        has = [v for v in prof.values() if v]
        if has:
            lines = []
            labels = {"name": "姓名", "nickname": "昵称", "city": "城市",
                      "occupation": "职业", "hobbies": "爱好", "otherInfo": "其他"}
            for k, v in prof.items():
                if v:
                    lines.append(labels.get(k, k) + "：" + v)
            parts.append("关于用户：" + "；".join(lines))
        mems = self._data["memories"]
        if mems:
            lines = []
            for m in mems[-20:]:
                lines.append("· " + m.get("content", ""))
            parts.append("你记住的事：\n" + "\n".join(lines))
        if not parts:
            return ""
        return "【长期记忆】\n" + "\n".join(parts)


# 全局单例（connector / window 共用）
_service = None


def get_service() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService()
    return _service
