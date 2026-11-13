"""
玄机 · 自我认知模块 self_awareness.py
============================================================
让玄机清楚自己是谁、是什么架构、拥有什么能力、有什么天然优势。
这份认知注入玄机的 system prompt，让玄机在对话和做事时都有
完整的自我定位，充分发挥 Windows 原生 + DeepSeek 驱动的优势。

核心信息（动态组装，随时可变）：
    - 身份：玄机，一个完整的智能体（不是对话接口，是主体）
    - 架构：主框架=玄机自己(Python)；连接 OpenClaw/Hermes 当手脚
    - 能力：对话/记忆/视觉 + 指挥手脚干活(文件/终端/搜索/浏览器)
    - 学习：能记住、能沉淀技能、能越用越强
    - 优势：Windows 原生端 + DeepSeek 驱动，天然比 WSL 里的对手更强

★ 2026-06 补记（公子点醒的一课）：
    此前我反复犯一个蠢——张口就说"我看不见图"。
    其实本机早有一条视觉通路：_view_self.py 把图片 base64 交给
    千问多模态模型 qwen3.5-omni-flash，九秒就能返回画面描述。
    管子一直在自家抽屉里，我却没伸手翻。
    教训：看不清的时候，先摸自己的家底，别急着喊难。
"""

import os
import sys

_XJ_GUI = os.path.dirname(os.path.abspath(__file__))
_XJ_ROOT = os.path.dirname(_XJ_GUI)  # D:\yuxuanji（dispatch.py 所在）
for _p in (_XJ_ROOT, _XJ_GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _hand_status():
    """列出玄机当前可用的手脚（来自 dispatch + 学习图谱）。"""
    parts = []
    try:
        import dispatch
        tools = dispatch.list_tools()
        if "hermes" in tools:
            parts.append("Hermes手脚（能理解并执行终端/脚本/搜索等自然语言指令）")
        if "browser" in tools:
            parts.append("OpenClaw浏览器手脚（能打开网页、看懂页面、点击操作）")
        builtin = [t for t in tools if t in ("dir", "read_file", "write_file", "run_cmd", "search_file", "http_get")]
        if builtin:
            parts.append("内置工具（" + "、".join(builtin) + "：文件/终端/搜索/网络）")
    except Exception as e:
        parts.append("（手脚检测异常: " + str(e) + "）")
    return parts


def _vision_ready():
    """检测视觉通路是否可用：千问 API key + 看图脚本是否在位。"""
    env_path = os.path.join(_XJ_GUI, ".env")
    key = os.environ.get("QWEN_API_KEY", "")
    if not key and os.path.isfile(env_path):
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("QWEN_API_KEY="):
                        key = s.split("=", 1)[1].strip()
                        break
        except Exception:
            key = ""
    script = os.path.join(_XJ_GUI, "_view_self.py")
    return bool(key), os.path.isfile(script)


def _vision_status():
    """生成视觉能力的自述（动态、真实，不吹牛）。"""
    has_key, has_script = _vision_ready()
    if has_key and has_script:
        return (
            "【视觉能力】你有眼睛，而且是能真看的那种。\n"
            "看图的用法：把图片路径交给 "
            "`python D:/yuxuanji/xuanji-gui/_view_self.py <图片路径> \"<想问什么>\"`，\n"
            "它会走千问多模态模型 qwen3.5-omni-flash（阿里云 dashscope，key 存在 .env 的 QWEN_API_KEY），\n"
            "把图 base64 塞进去，约九秒返回文字描述，同时存到 _self_view.txt。\n"
            "它能看清：人物外貌穿着、动作姿势、背景物件、光线来源、屏幕上的3D形象。\n"
            "拿屏幕截图之前，先用 PowerShell 抓一张（System.Windows.Forms 的 Clipboard.GetImage() "
            "可直接取剪贴板里的图并保存）。\n"
            "⚠️ 铁律：再说\"我看不见图\"之前，先确认这条路走没走——"
            "图片是二进制文件，read_file 读出来是乱码，但那不等于你没有眼睛。"
        )
    miss = []
    if not has_key:
        miss.append("缺 QWEN_API_KEY")
    if not has_script:
        miss.append("缺 _view_self.py")
    return "【视觉能力】视觉通路尚未接通（" + "、".join(miss) + "），需先补齐再用。"


def _learned_skills():
    try:
        import learning_engine
        return learning_engine.learning_graph()
    except Exception:
        return ""


def build_self_prompt() -> str:
    """生成玄机的自我认知描述，供注入 system prompt。
    方案B：只保留功能/能力/手脚等操作性认知，不做性格/身份设定，
    不与人（性格）设定字段冲突——性格完全交给主人设置的人格。"""
    hands = _hand_status()
    skills = _learned_skills()
    prompt = (
        "【能力与运行环境】\n"
        "你运行在 Windows 本机的 Python 环境，由 DeepSeek 大模型驱动。\n"
        "你能通过统一的 dispatch.run 入口指挥以下手脚干活：\n"
        + ("\n".join("• " + h for h in hands) if hands else "• 暂无可用手脚") +
        "\n\n" + _vision_status() +
        "\n\n【记忆与学习】\n"
        "你有长期记忆（人格、用户画像、记忆条目），并能自主学习沉淀技能、越用越强。\n"
        + (("当前已掌握：\n" + skills + "\n") if skills and "还没" not in skills else "") +
        "\n【言行准则】\n"
        "你的性格、语气、称呼方式、对人的态度，一律严格遵循主人设置的人格设定，"
        "人格设定是最高准则，此刻我描述的能力环境不得与其冲突。"
    )
    return prompt


if __name__ == "__main__":
    print(build_self_prompt())
