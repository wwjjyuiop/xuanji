"""
玄机 · 手脚调度模块 skill_hands.py（第4步）
============================================================
作用：在玄机核心对话时判断用户是要"纯聊天"还是"要动手干活"，
      要干活就调 dispatch.py 指挥手脚（文件/终端/Hermes），
      把执行结果带回对话，让玄机真的能"一句话指挥干活"。

使用简单规则起步：命中动作关键词 → 判定为要干活。
后续可升级为 AI 判断（先问 DeepSeek 是否需调工具）。
"""

import os
import sys
import json

# 把玄机根加入路径，import dispatch
_XJ_ROOT = r"D:\yuxuanji"
if _XJ_ROOT not in sys.path:
    sys.path.insert(0, _XJ_ROOT)

_dispatch = None


def _get_dispatch():
    """惰性加载 dispatch，避免 import 失败就拖垮玄机对话。"""
    global _dispatch
    if _dispatch is None:
        try:
            import dispatch
            _dispatch = dispatch
        except Exception as e:
            print("[手脚] dispatch 加载失败: " + str(e))
            _dispatch = False
    return _dispatch if _dispatch else None


# ─── 干活意图判断（简单规则）────────────────────────
# 命中这些动作词，判定为"要动手干活"
_ACTION_WORDS = [
    "帮我", "请", "麻烦", "拜托",          # 请求
    "打开", "运行", "执行", "创建", "建立",   # 动作
    "删除", "重命名", "复制", "移动",         # 文件操作
    "搜索", "查找", "查一下", "列出", "看下",  # 查询
    "下载", "上传",                         # 网络
    "安装", "启动", "关闭", "停止",          # 进程/服务
    "写文件", "读文件", "改文件", "编辑",     # 文件编辑
    "建个", "做个", "生成", "导出",          # 生成
    "终端", "命令", "命令行", "cmd", "dir",  # 终端
]

# 聊天类词（命中这些一般不是干活，是闲聊/提问）
_CHAT_WORDS = [
    "你是谁", "你好", "在吗", "谢谢", "再见",
    "喜欢", "爱", "心情", "感觉", "觉得",
    "为什么", "什么", "怎么","吗", "呢", "吧",
]


def wants_action(text: str) -> bool:
    """判断这句话是不是要动手干活。简单规则。"""
    if not text:
        return False
    hit_action = any(w in text for w in _ACTION_WORDS)
    if not hit_action:
        return False
    # 若同时命中强聊天词，视为闲聊（保守）
    hit_chat = any(w in text for w in _CHAT_WORDS)
    if hit_chat and not any(w in text for w in ["帮我", "打开", "运行", "创建", "列出", "搜索", "建个", "删除"]):
        return False
    return True


# ─── 把用户的一句话转成调度桥调用 ─────────────────────
def dispatch_request(text: str):
    """尝试让手脚执行一条指令。返回 dict{ok, result, error}。

    学习引擎接入：
      1) 干活前先 search_skill 找玄机已学会的技能，命中则把技能上下文
         带给 Hermes，让它按已沉淀的经验干活（而非每次重新摸索）。
      2) 干完后自动 create_skill 沉淀成 SKILL.md（agent-created skill），
         让玄机 "越用越会"：下次同类活直接命中技能，不用再从头来。
    """
    d = _get_dispatch()
    if d is None:
        return {"ok": False, "error": "手脚调度桥不可用"}

    # ── 1) 干活前：找玄机已学会的技能 ──
    skill_ctx = ""
    try:
        import learning_engine
        hit = learning_engine.search_skill(text)
        if hit:
            skill_ctx = (
                "[你有相关经验，按这个已有技能来做]\n"
                "技能: " + hit["name"] + "\n"
                "描述: " + (hit.get("description") or "") + "\n\n"
            )
            # 使用一次就记一次（学习图谱原料）
            learning_engine.tick_skill(hit["name"])
            print("[学习] 命中已有技能: " + hit["name"])
    except Exception as e:
        print("[学习] 技能检索异常(不影响干活): " + str(e))

    # 优先让 Hermes 理解自然语言并执行（能力最全）
    r = d.run("hermes", {"cmd": (skill_ctx + text), "timeout": 150})
    if r.get("ok"):
        # ── 2) 干完后：有机会就沉淀成技能 ──
        _maybe_learn(text, r.get("result"))
        return {"ok": True, "result": r.get("result")}
    # Hermes 失败时，回退到内置工具（如文件/终端关键词）
    return r


def _maybe_learn(task: str, result):
    """干完一件有套路的活，自动沉淀成玄机技能（agent-created skill）。

    当前轻量版的沉淀策略：
      - 只对 "请求帮助做文件/目录/查询类" 的常见活自动沉淀，避免过度生成。
      - 已存在的技能不重复创建（search_skill 能命中就不新建）。
    """
    try:
        import learning_engine
        # 已有同名/同义技能则不再沉淀（避免堆叠）
        if learning_engine.search_skill(task):
            return
        # 只对确认能干的活沉淀
        if not result:
            return
        # 用任务的前几个字作为技能名（简短、去语气词）
        name = _simple_skill_name(task)
        if not name:
            return
        learning_engine.create_skill(
            name=name,
            description="用户要求：" + task[:40],
            summary="玄机在" + str(result)[:60] + "…（经验沉淀）",
            when_to_use="用户提出类似的要求时。",
            when_not="同类活已通过 Hermes 可靠完成、无需重复沉淀时。",
            how="1. 识别用户意图 2. 调 dispatch(hermes) 3. 返回结果",
            tags=["自动沉淀", "hands"],
        )
        print("[学习] 已自动沉淀新技能: " + name)
    except Exception as e:
        print("[学习] 技能沉淀异常(不影响结果): " + str(e))


def _simple_skill_name(task: str) -> str:
    """从一句话里提取一个简短技能名：去掉语气词/请求词，取核心动作词。"""
    for w in ["帮我", "请", "麻烦", "拜托", "打开", "运行", "列一下", "看一看", "查一下"]:
        task = task.replace(w, "")
    task = task.strip(" ，。？！.！ ")
    # 取前 6 个字做名字
    return task[:6].strip() or None


def result_to_text(r) -> str:
    """把调度结果转成玄机能回复自然给用户的文字。"""
    if r.get("result"):
        res = str(r["result"])
        # 截断过长，避免刷屏
        if len(res) > 800:
            res = res[:800] + "\n…(结果过长已截断)"
        return "好的，我帮你办好了：\n" + res
    if r.get("error"):
        return "这个我试着做了，但遇到点问题：" + str(r["error"])
    return "这个我没能办成，不好意思。"


if __name__ == "__main__":
    # 自测
    for t in ["帮我列出D盘根目录", "你好呀", "请用dir命令", "今天天气怎么样"]:
        print(f"{t!r} -> wants_action={wants_action(t)}")
