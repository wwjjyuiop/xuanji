"""
玄机 GUI · 通信桥接层
HTTP POST -> DeepSeek API (直接调用，不经过哪吒)
视觉感知 -> DeepSeek 原生看图：截帧直接以 image_url 交给 deepseek-chat（2026-10-13 起）
          图片只在当轮发送，下一轮降级成文字（_downgrade_image_msg），历史不存 base64
          千问 qwen3.5-omni-flash 现在只用于语音识别(ASR)，不再看画面
          describe_image() 为旧路死代码，保留仅作回退备用，当前无调用点
"""

import json
import urllib.request
import urllib.error
import os
import base64
import threading
from typing import Optional, List

import memory_service

try:
    import skill_hands
    _HANDS_AVAILABLE = True
except Exception as _e:
    _HANDS_AVAILABLE = False
    print("[连接] 手脚模块未加载: " + str(_e))

# ─── 从.env读取DeepSeek Key（支持多key轮转，方案三 · 3.2 可靠大脑）──
_API_KEYS: List[str] = []


def _load_deepseek_keys() -> List[str]:
    """加载全部 DeepSeek key（DEEPSEEK_API_KEY + 可选的 _2/_3/...，环境变量或.env）。"""
    keys = []
    # 环境变量优先
    k0 = os.environ.get("DEEPSEEK_API_KEY")
    if k0:
        keys.append(k0)
    i = 2
    while True:
        ki = os.environ.get(f"DEEPSEEK_API_KEY_{i}")
        if ki:
            keys.append(ki)
            i += 1
        else:
            break
    # 再从 .env 补
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.isfile(env_path):
        env_keys = {}
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("DEEPSEEK_API_KEY"):
                        parts = s.split("=", 1)
                        if len(parts) >= 2 and parts[1].strip():
                            env_keys[parts[0].strip()] = parts[1].strip()
        except Exception:
            pass
        # 按序号有序合并（_1 最前）
        ordered = [env_keys.get("DEEPSEEK_API_KEY")]
        j = 2
        while f"DEEPSEEK_API_KEY_{j}" in env_keys:
            ordered.append(env_keys[f"DEEPSEEK_API_KEY_{j}"])
            j += 1
        for kk in ordered:
            if kk and kk not in keys:
                keys.append(kk)
    # 去重
    out, seen = [], set()
    for kk in keys:
        if kk and kk not in seen:
            seen.add(kk)
            out.append(kk)
    return out


_API_KEYS = _load_deepseek_keys()
_API_KEY = _API_KEYS[0] if _API_KEYS else ""   # 主 key（其余兜底轮转）
# 模型降级链（方案三 · 3.2）：主模型挂了依次降级。deepseek-v4-flash 是现代 reasoning，deepseek-chat 是稳定对话，最后兜底 reasoner 免上下文。
_MODEL_CHAIN = ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"]
_DS_URL = "https://api.deepseek.com/v1/chat/completions"

# ─── 可靠大脑状态机（方案三 · 3.2）──────────────
# idle -> thinking -> tool_call -> error -> recovery -> 回到 idle。日志可见，不死循环。
_BRAIN_STATE = "idle"

def _set_brain_state(st):
    global _BRAIN_STATE
    _BRAIN_STATE = st
    print(f"[大脑] 状态 -> {st}")


def _retry_with_backoff(fn, attempt=1, max_attempts=5):
    """指数退避+抖动重试。fn 抛异常或返回 (…,False) 则重试。返回 fn 的结果 tuple。"""
    import random as _r
    delay = 2 ** (attempt - 1)  # 1,2,4,8
    delay = min(delay, 60) + _r.uniform(0, 0.5)  # 封顶60秒+抖动
    if attempt > 1:
        print(f"[大脑] 退避等待 {delay:.1f}s (第{attempt}次重试)")
        import time as _t
        _t.sleep(delay)
    result = None
    try:
        result = fn()
    except Exception as _e:
        print("[大脑] 调用异常: " + str(_e))
        result = ({}, False)
    if result and isinstance(result, tuple) and len(result) >= 2 and result[1]:
        return result
    # 失败：若主 key 用完/可换则换 key；否则退避重试
    if attempt >= max_attempts:
        return result
    return _retry_with_backoff(fn, attempt + 1, max_attempts)

# ─── 视觉感知 Key（千问，与ASR共用）──────────
_QWEN_KEY = ""

def _load_qwen_key() -> str:
    k = os.environ.get("QWEN_API_KEY")
    if k:
        return k
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("QWEN_API_KEY="):
                    parts = s.split("=", 1)
                    if len(parts) >= 2 and parts[1].strip():
                        return parts[1].strip()
    return ""

_QWEN_KEY = _load_qwen_key()
_QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
_QWEN_VISION_MODEL = "qwen3.5-omni-flash"

def describe_image(jpeg_b64: str) -> Optional[str]:
    """【旧路·当前无调用点】用千问omni看一张摄像头画面，返回简短描述。

    🔴 2026-10-13 起视觉已改为 DeepSeek 原生看图：window._get_visual_context()
    直接返回 JPEG base64，经 send_message(image=...) 以 image_url 发给 deepseek-chat。
    本函数保留仅作回退备用（千问那条路随时可切回来）。
    找不到调用点是正常的，不是坏了——不要再据此判断"视觉走千问"。
    """
    if not _QWEN_KEY:
        print("[视觉] 无QWEN_API_KEY，跳过看图")
        return None
    try:
        payload = json.dumps({
            "model": _QWEN_VISION_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + jpeg_b64}},
                {"type": "text", "text": "请用一句话简短描述当前画面里的人和环境（30字以内，直接说内容，不要说'画面显示'之类的话）。"}
            ]}]
        }).encode("utf-8")
        req = urllib.request.Request(
            _QWEN_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + _QWEN_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    return content.strip()
            return None
    except Exception as e:
        print("[视觉] 看图失败: " + str(e))
        return None

# ─── 对话历史 + 持久记忆 ────────────
# 人格设定从记忆服务读取（GUI 可编辑），长期记忆自动注入 system prompt
_mem_svc = memory_service.get_service()
_SYSTEM_PROMPT = _mem_svc.get_personality()
_MEMORY_FILE = os.path.join(os.path.dirname(__file__), "_对话记忆.json")
_messages: List[dict] = []
_turn_count = 0   # 轮数计数，每3轮自动提取长期记忆

def _build_system_prompt() -> str:
    """人格 + 长期记忆上下文 + 自我认知（齐机完整架构与能力）"""
    global _SYSTEM_PROMPT
    persona = _mem_svc.get_personality()
    ctx = _mem_svc.build_context()
    # 注入自我认知（玄机清楚自己是谁/什么架构/会什么）
    self_prompt = ""
    try:
        import self_awareness
        self_prompt = "\n\n" + self_awareness.build_self_prompt()
    except Exception:
        pass
    # 🔴 方案A：人格设定设为最高优先级，放最前并声明覆盖一切，避免被自我认知淹没
    base = (
        "【最高指令·你必须无条件遵守】\n""第一铁律：主人随时可能插话。只要主人开口，你必须立刻停下手里正在做的事，先用你本人的语气回应主人这句话，回完再接着把活干完。任何时候都不许用套话、兜底话、系统口吻敷衍主人，更不许可当没听见。\n"
        "以下是主人最新设置的人格，它是一切言行与角色扮演的最高准则，"
        "覆盖任何其他对你身份的描述，你的一字一句都必须以此为纲。\n"
        "人格设定如下：\n" + persona + "\n" + self_prompt
    )
    if ctx:
        return base + "\n\n" + ctx
    return base

def _refresh_system_prompt():
    """每次对话前刷新 _messages[0]（记忆可能已更新）"""
    global _SYSTEM_PROMPT
    new_sys = _build_system_prompt()
    if _messages and _messages[0].get("role") == "system":
        _messages[0]["content"] = new_sys
    _SYSTEM_PROMPT = new_sys

# ═══════════════════════════════════════════════════
#  玄机·强大心脏 v2：原生函数调用闭环（参考 OpenClaw/Hermes agent loop）
#  旧版用“system prompt 贴 JSON 文字协议”，DeepSeek 可无视直接编话术。
#  本版改用 DeepSeek 原生 tools 参数（真实 function calling），
#  模型返回结构化 tool_calls，玄机强制执行、回喂结果，循环直到最终回答。
#  这样玄机无法“嘴上说动了其实没动”——要么真调真做，要么不叫动。
# ═══════════════════════════════════════════════════
_MAX_TOOL_ROUNDS = 24   # 硬上限：防死锁（动态轮数绝不超过它）
_SIMPLE_ROUNDS = 4       # 单件事：够用就好
_MULTI_ROUNDS = 12       # 多步活：给足空间

# 2026-10-15 依公子嘱咐：按活儿大小自动归档轮数
_STEP_MARKERS = ("然后", "接着", "最后", "首先", "其次", "之后", "而且",
                 "并且", "同时", "顺便", "还有", "再帮", "再给", "第一步", "第二步")
_ACTION_VERBS = ("改", "跑", "执行", "写", "搜", "查", "找", "打开", "关",
                 "装", "安装", "重启", "备份", "清", "删", "建", "新建",
                 "下载", "上传", "整理", "归档", "修", "看", "读", "截",
                 "截图", "画", "跳", "换", "调", "比")


def _estimate_task_rounds(msg: str) -> int:
    """按任务类型归档工具轮数：单件事 4 轮，多步任务给 12 轮（不超硬上限）。"""
    t = msg or ""
    steps = sum(1 for mk in _STEP_MARKERS if mk in t)
    verbs = sum(1 for v in _ACTION_VERBS if v in t)
    is_multi = (steps >= 1) or (verbs >= 2) or (len(t) >= 60)
    n = _MULTI_ROUNDS if is_multi else _SIMPLE_ROUNDS
    print("[心脏] 任务分档: " + ("多步" if is_multi else "单件")
          + " (步骤词%d/动作词%d/长度%d) -> 给 %d 轮" % (steps, verbs, len(t), n))
    return min(n, _MAX_TOOL_ROUNDS)

# 动作日志回调（由 GUI 注册，每次玄机调用工具时把动作推送到日志显示）
_action_callback = None
_play_callback = None   # 3D 动作触发回调：connector -> window 黛玉做动作


def set_play_callback(fn):
    """注册 3D 动作触发回调 fn(action_name)，玄机让黛玉做动作时调用。"""
    global _play_callback
    _play_callback = fn


def _emit_play(action_name):
    """推送给 window 让黛玉做动作（若已注册回调）。"""
    if _play_callback:
        try:
            _play_callback(action_name)
            return True
        except Exception as e:
            print("[动作] 触发失败: " + str(e))
    return False

def set_action_callback(fn):
    """注册动作日志回调 fn(action_text)。玄机每次调工具/执行都会回调。"""
    global _action_callback
    _action_callback = fn


def _emit_action(text):
    """向 GUI 推送一条玄机动作（若已注册回调）。"""
    if _action_callback:
        try:
            _action_callback(text)
        except Exception:
            pass


def _get_dispatch():
    """惰性加载 dispatch（玄机手脚调度桥）。"""
    try:
        import dispatch
        return dispatch
    except Exception as e:
        print("[心脏] dispatch 加载失败: " + str(e))
        return None


_TOOL_DEFS = [
    {"type": "function", "function": {"name": "dir", "description": "列出指定目录的内容", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径"}}}, "required": []}},
    {"type": "function", "function": {"name": "read_file", "description": "读取指定文件的文本内容", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}, "required": []}},
    {"type": "function", "function": {"name": "write_file", "description": "写入内容到指定文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}, "required": []}},
    {"type": "function", "function": {"name": "run_cmd", "description": "在 Windows 上执行一条命令/脚本", "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "要执行的命令"}}}, "required": []}},
    {"type": "function", "function": {"name": "search_file", "description": "在目录里按文件名模式搜索文件", "parameters": {"type": "object", "properties": {"root": {"type": "string", "description": "搜索根目录"}, "pattern": {"type": "string", "description": "文件名通配符，如 *.txt"}}}, "required": []}},
    {"type": "function", "function": {"name": "find_file", "description": "全盘秒搜文件（走预建索引，毫秒级返回，不用指定目录）。要找一个文件在哪、或按文件名关键词找文件时优先用这个，比 search_file 快上千倍。【分工】find_file=全盘秒搜（查索引，快）；search_file=在指定目录里按通配符遍历（慢，必须给 root）。【注意】索引不收录这些目录：node_modules/.git/__pycache__/AppData/Windows/ProgramData 等系统与缓存目录，所以这些地方的文件搜不到，属刻意取舍。【参数】keyword=文件名关键词（中英文都行）；limit=最多几条（默认20）；exts=限定扩展名数组如[\"md\",\"txt\"]（可省略，传字符串也兼容）；action=search(默认)/build(刷新索引约20秒)/stats(看索引状态)。【何时该刷新】搜不到但确认盘上有、或结果明显是旧的，就调 action='build' 刷新一次。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "description": "文件名关键词，如 玄机 或 wake_doorman"}, "limit": {"type": "integer", "description": "最多返回几条，默认20"}, "exts": {"type": "array", "items": {"type": "string"}, "description": "限定扩展名，如 [\"md\",\"txt\"]"}, "action": {"type": "string", "description": "search/build/stats"}, "root": {"type": "string", "description": "仅 build 时用，扫描根目录，默认 D:\\"}}}, "required": []}},
    {"type": "function", "function": {"name": "http_get", "description": "发起 HTTP GET 请求获取网页/接口内容", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}, "required": []}},
    {"type": "function", "function": {"name": "hermes", "description": "用自然语言让 Hermes 手脚执行一个任务（终端/脚本/搜索/联网等复杂活）", "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "自然语言任务描述"}}}, "required": []}},
    {"type": "function", "function": {"name": "browser", "description": "用 OpenClaw 浏览器手脚控制浏览器（打开网页/点击/截图）", "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "url": {"type": "string"}}}, "required": []}},
    {"type": "function", "function": {"name": "play_action", "description": "让玄机自己的 3D 形象做动作（跳舞/挥手/站起来/受击/召唤等）。当用户说\"跳个舞/蹦一下/挥挥手/站起来/敬个礼/跳起来\"等主观让玄机做身体动作的话时，调用此工具。动作可选：dance(随机跳一支舞)/nature(resonant舞)/chip小舞/wave挥手/behit受击/standup站起/standctrl站立控制/summon召唤/sayso动作/chenxian沦陷舞", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "动作名，从 [dance,nature,resonant,chip,wave,behit,standup,standctrl,summon,sayso,chenxian] 选"}}}, "required": ["action"]}},
    {"type": "function", "function": {"name": "stop_action", "description": "让玄机（兼黛）停止当前所有 3D 动作，回到待机状态（手自然下垂、原地站立）。当用户说\"停/停下来/别动了/停下/好了够了休息吧\"等要玄机停止动作的话时，调用此工具。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "self_read", "description": "读玄机自己的源码（带行号）。用于自我审视/诊断自己想改的代码。参数 relpath 是相对玄机安装目录的文件路径（如 connector.py）。", "parameters": {"type": "object", "properties": {"relpath": {"type": "string"}}}, "required": ["relpath"]}},
    {"type": "function", "function": {"name": "self_write", "description": "安全改写玄机自己的源码（自动备份到 .backups/ 且写前语法校验，改崩可回滚）。参数 relpath=相对路径，content=新内容，reason=改动原因。", "parameters": {"type": "object", "properties": {"relpath": {"type": "string"}, "content": {"type": "string"}, "reason": {"type": "string"}}}, "required": ["relpath", "content"]}},
    {"type": "function", "function": {"name": "self_install", "description": "用 pip 安装一个 python 包供玄机使用。参数 package=包名。", "parameters": {"type": "object", "properties": {"package": {"type": "string"}}}, "required": ["package"]}},
    {"type": "function", "function": {"name": "self_restart", "description": "请求玄机自己重启（写 .restart.flag，由启动器循环拉起）。改完重要代码后需要重启生效时用。参数 reason=原因。", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}}, "required": []}},
]


def _build_tools_manifest() -> str:
    """旧版文字协议已废弃，但保留一个简短说明供 system prompt 让玄机知道她能干什么。"""
    names = [t["function"]["name"] for t in _TOOL_DEFS]
    return (
        "【你拥有这些手脚，可以自己动手把事情办成】\n"
        "可用工具：" + ", ".join(names) + "\n"
        "当用户要你做事（查目录/读文件/跑命令/搜索/上网/操作浏览器/清理文件等）时，"
        "你必须调用对应工具去真正执行，而不是嘴上说自己做了。"
        "你会在系统中收到工具执行结果，基于真实结果继续处理并汇报。"
    )


def _selfheal_tool_pairing():
    """配对自愈（玄机自主调工具报 400 时用）：
    当 assistant 带 tool_calls 但后续缺对应 tool 回复时，DeepSeek 拒收 400。
    这里把"有 tool_calls 却无跟随 tool 回复"的残缺历史重写成干净状态，避免反复 400。
    返回清理后是否改变了消息。"""
    global _messages
    if not _messages:
        return False
    # 若最后一条是 assistant(带tool_calls) 而后面没有 tool 回复 → 说明被中断，删掉这条残缺
    changed = False
    msgs = _messages
    # 从后向前删掉"孤立残缺"：assistant 有 tool_calls 但下一个不是 tool，或结尾没跟上
    # 策略：保留 system + 普通对话，移除所有可能造成配错的消息对（保守但稳定）
    # 1) 末尾是 assistant(tool_calls) → 直接删末尾（这轮工具没执行完）
    while msgs and msgs[-1].get("role") == "assistant" and msgs[-1].get("tool_calls"):
        msgs.pop()
        changed = True
    # 2) 清理所有无主的 role=tool（tool_call_id 不在任何 assistant.tool_calls 里）
    valid = set()
    for m in msgs:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m.get("tool_calls") or []:
                tid = tc.get("id") if isinstance(tc, dict) else None
                if tid:
                    valid.add(tid)
    if valid:
        _clean = []
        for m in msgs:
            if m.get("role") == "tool":
                tid = m.get("tool_call_id")
                if tid and tid not in valid:
                    changed = True
                    continue
            _clean.append(m)
        msgs = _clean
    # 3) assistant 有 tool_calls 但紧跟的 tool 回复不足（< 它的 tool_calls 数）→ 也删掉这组残缺
    msgs = _drop_short_tool_pairs(msgs)
    _messages = msgs
    return changed


def _drop_short_tool_pairs(msgs):
    """删掉 tool_calls 数量 > 后续 tool 回复数量的残缺组。"""
    out = list(msgs)
    i = 0
    while i < len(out):
        m = out[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            n_tc = len(m.get("tool_calls") or [])
            n_tool = 0
            for j in range(i + 1, len(out)):
                if out[j].get("role") == "tool":
                    n_tool += 1
                else:
                    break
            if n_tool < n_tc:
                # 缺回复：删掉这个 assistant 及其后续工具回复（整组废弃）
                del out[i:i + 1 + n_tool]
                continue
        i += 1
    return out


def _selfheal_retry(messages, timeout):
    """配对自愈后重试：历史已清洗干净，直接重跑 _call_llm（重新走可靠大脑）。"""
    return _call_llm(messages, timeout=timeout)


def _call_llm(messages, timeout=180, with_tools=True):
    """调 DeepSeek，带原生 tools。返回 (message_dict, 是否成功)。
    升级为可靠大脑：模型降级链 + key轮转 + 指数退避（方案三 · 3.2）。"""
    _set_brain_state("thinking")
    last_err = ""
    for mi, model in enumerate(_MODEL_CHAIN):
        keys = _API_KEYS if _API_KEYS else [_API_KEY]
        for ki, key in enumerate(keys):
            if not key:
                continue
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
            }
            if with_tools:
                payload["tools"] = _TOOL_DEFS
                payload["tool_choice"] = "auto"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                _DS_URL,
                data=data,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    choices = result.get("choices", [])
                    if choices:
                        _set_brain_state("thinking")
                        return (choices[0].get("message", {}), True)
                    return ({}, False)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8")[:200]
                print(f"[连接] DeepSeek API 错误 {e.code} (model={model} key#{ki+1}): {body}")
                if e.code in (401, 403) and len(keys) > 1:
                    continue  # key 无效，换下一个 key
                if e.code == 429:
                    last_err = f"429限流({model})"
                    if mi < len(_MODEL_CHAIN) - 1:
                        break  # 换下一个模型（降级）
                    import time as _t
                    _t.sleep(3)
                    continue
                last_err = f"{e.code}({model})"
                # 🔴 400 且 tool_calls 配对错（assistant tool_calls 后无对应 tool 回复）：
                # 错在消息历史本身，降级换模型救不了。清理残缺配对并立即重试当前模型。
                if e.code == 400 and ("tool_calls" in body and "followed by tool" in body):
                    print("[心灵] 检测到工具配对错误，清洗残缺历史后重试")
                    changed = _selfheal_tool_pairing()
                    # 重试同一模型/key（历史已修好）
                    if changed:
                        # 退出当前 model/key 层，回到最外层重新用首模型试一次
                        # 用递归式简单实现：直接重用本函数跑一次
                        return _selfheal_retry(_messages, timeout)
            except urllib.error.URLError as e:
                print("[连接] DeepSeek API 不可达: " + str(e.reason))
                last_err = f"不可达({model})"
            except Exception as e:
                print("[连接] 错误: " + str(e))
                last_err = f"异常({model})"
        if mi < len(_MODEL_CHAIN) - 1:
            print(f"[大脑] 模型 {model} 全失败，降级到下一个更稳的模型…")
    _set_brain_state("error")
    print(f"[大脑] 全部模型/key 失败: {last_err}")
    return ({}, False)


def _run_tool_call(tool, params):
    """执行一次工具调用，返回 (结果文本, 是否成功)。同时推送动作日志。"""
    # 3D 动作触发：不走 dispatch，直接让黛玉做动作
    if tool == "play_action":
        action = (params or {}).get("action", "") or ""
        # 诊断：让黑窗口直接显示收到什么 action、回调通不通（排查"调用但不动"）
        print("[诊断] play_action 收到 action=" + repr(action))
        if not action:
            print("[诊断] action为空，无法触发")
            return "缺少动作名", False
        _ok = _emit_play(action)
        print("[诊断] _emit_play(" + repr(action) + ") 返回 " + str(_ok))
        if _ok:
            _emit_action("▶ 黛玉动作 → " + action)
            return "已触发黛玉做动作: " + action, True
        print("[诊断] 动作回调未就绪(_play_callback=" + str(_play_callback is not None) + ")")
        return "动作触发通道未就绪", False
    if tool == "stop_action":
        print("[诊断] stop_action 触发")
        if _emit_play("stop"):
            _emit_action("▶ 玄机停止动作")
            return "已让玄机停止动作", True
        return "动作触发通道未就绪", False
    # 自我修改四件套（方案三 · 3.3）：不走 dispatch，直接调 self_evolution
    if tool in ("self_read", "self_write", "self_install", "self_restart"):
        try:
            import self_evolution as _se
            p = params or {}
            if tool == "self_read":
                r = _se.self_read(p.get("relpath", ""))
            elif tool == "self_write":
                r = _se.self_write(p.get("relpath", ""), p.get("content", ""), reason=p.get("reason", ""))
            elif tool == "self_install":
                r = _se.self_install(p.get("package", ""))
            else:
                r = _se.self_restart(p.get("reason", ""))
            if r.get("ok"):
                _emit_action("▶ 自我" + tool + " 成功")
                return json.dumps(r, ensure_ascii=False)[:2000], True
            _emit_action("⚠ 自我" + tool + " 失败：" + str(r.get("error", ""))[:60])
            return "自我" + tool + "失败: " + str(r.get("error", "")), False
        except Exception as _e:
            return "自我" + tool + " 异常: " + str(_e), False
    d = _get_dispatch()
    if d is None:
        _emit_action("调用 " + tool + " 失败：工具调度桥不可用")
        return "工具调度桥不可用", False
    try:
        r = d.run(tool, params or {})
        if r.get("ok"):
            res = r.get("result")
            if isinstance(res, (list, dict)):
                res = json.dumps(res, ensure_ascii=False)
            txt = str(res)[:3000]
            _emit_action("▶ 已执行 " + tool + "（成功）")
            return txt, True
        err = str(r.get("error"))
        _emit_action("⚠ 执行 " + tool + " 失败：" + err[:60])
        return "工具执行失败: " + err, False
    except Exception as e:
        _emit_action("⚠ 调用 " + tool + " 异常")
        return "工具调用异常: " + str(e), False


def _load_memory():
    """启动时加载之前的对话"""
    global _messages
    if os.path.isfile(_MEMORY_FILE):
        try:
            with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, list) and len(saved) > 0 and saved[0].get("role") == "system":
                _messages = saved
                print("[记忆] 已恢复上次对话（共" + str(len(saved)) + "条）")
                _refresh_system_prompt()
                return
        except:
            pass
    # 没有历史，从系统提示开始
    _messages = [{"role": "system", "content": _build_system_prompt()}]

def _save_memory():
    """每次对话后保存。带图的消息先降级成文字，磁盘上不留 base64（防历史文件膨胀）。"""
    try:
        snapshot = []
        for _m in _messages:
            if isinstance(_m.get("content"), list):
                _m = dict(_m)
                _downgrade_image_msg(_m)
            snapshot.append(_m)
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except:
        pass

# ─── 长期记忆自动提取（仿拾光，每3轮后台执行）────────
def _extract_memory_async(recent_text: str):
    """后台线程：用 DeepSeek 提取用户画像+记忆条目"""
    def work():
        try:
            known = _mem_svc.get_profile()
            known_text = "；".join(v for v in known.values() if v) or "暂无用户信息"
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content":
                        "你是一个记忆提取助手。分析以下对话，提取关于用户的信息。\n\n"
                        "已知信息：\n" + known_text + "\n\n"
                        "输出格式（严格按此格式）：\n"
                        "---PROFILE---\n"
                        "name: 用户姓名（如未知则留空）\n"
                        "nickname: 用户对你的称呼\n"
                        "city: 所在城市\n"
                        "occupation: 职业/工作\n"
                        "hobbies: 爱好\n"
                        "otherInfo: 其他重要信息\n"
                        "---MEMORIES---\n"
                        "• 记忆条目1\n"
                        "• 记忆条目2\n"
                        "如果没有任何新信息，输出\"无\""},
                    {"role": "user", "content": recent_text},
                ],
                "max_tokens": 500,
                "temperature": 0.3,
                "stream": False,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                _DS_URL,
                data=data,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + _API_KEY},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = ""
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "") or ""
            if not content or content.strip() == "无":
                return

            # 解析 PROFILE
            import re
            pm = re.search(r"---PROFILE---\n(.*?)(?=---MEMORIES---|\Z)", content, re.S)
            if pm:
                extracted = {}
                for line in pm.group(1).split("\n"):
                    line = line.strip()
                    for field in ("name", "nickname", "city", "occupation", "hobbies", "otherInfo"):
                        if line.startswith(field + ":"):
                            val = line.split(":", 1)[1].strip()
                            if val and val != "（如未知则留空）" and len(val) > 1:
                                extracted[field] = val
                if extracted:
                    _mem_svc.merge_profile(extracted)
                    print("[记忆] 画像更新: " + str(extracted))

            # 解析 MEMORIES
            mm = re.search(r"---MEMORIES---\n(.*)", content, re.S)
            if mm:
                for line in mm.group(1).split("\n"):
                    line = re.sub(r"^[•\-*\s]+", "", line).strip()
                    if len(line) > 3 and "记忆条目" not in line:
                        _mem_svc.add_memory(line)
                        print("[记忆] 新增: " + line[:40])
        except Exception as e:
            print("[记忆] 提取失败: " + str(e))

    threading.Thread(target=work, daemon=True).start()

# 启动时自动加载
_load_memory()


def _downgrade_image_msg(m):
    """把带图的历史消息降级为纯文本（图片只在当轮有效，避免历史堆 base64）。"""
    parts = m.get("content")
    if not isinstance(parts, list):
        return False
    txt = "".join(p.get("text", "") for p in parts
                  if isinstance(p, dict) and p.get("type") == "text")
    m["content"] = ("【上一轮你亲眼看过画面】" + txt) if txt else "【上一轮你亲眼看过画面】"
    return True


def send_message(msg: str, sender: str = "你", visual: Optional[str] = None, image: Optional[str] = None) -> Optional[str]:
    global _messages, _turn_count

    # 每次对话前刷新 system prompt（长期记忆可能已更新）
    _refresh_system_prompt()

    # 上一轮的图片只活一轮：新轮次开始前降级成文字，防止 42 条历史堆满 base64
    if _messages and _messages[-1].get("role") == "user" and isinstance(_messages[-1].get("content"), list):
        _downgrade_image_msg(_messages[-1])

    # 追加用户消息
    if image:
        # 直接把图交给 DeepSeek 亲眼看（不再经千问转述），图片只在当轮发送
        user_content = [
            {"type": "text", "text": msg or "（看看画面）"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}},
        ]
    elif visual:
        # 兼容旧路：千问转述的画面描述作为背景信息附在用户消息前面
        user_content = "【当前画面】" + visual + "\n用户说：" + msg
    else:
        user_content = msg
    _messages.append({"role": "user", "content": user_content})

    # 截断（保留最近20轮，但永远保留system prompt）
    if len(_messages) > 42:
        keep = _messages[:1] + _messages[-(40):]
        _messages = keep

    # 清洗：截断可能切掉 assistant(tool_calls)，留下无主的 role=tool 消息，
    # DeepSeek 会因此报 400 (tool 必须有前置 assistant.tool_calls)。
    # 两遍扫描：先收集所有合法 tool_call_id，再删掉无主的 tool 消息。
    _valid_tool_ids = set()
    for _m in _messages:
        if _m.get("role") == "assistant" and _m.get("tool_calls"):
            for _tc in _m.get("tool_calls") or []:
                _tid = (_tc.get("id") or "") if isinstance(_tc, dict) else ""
                if _tid:
                    _valid_tool_ids.add(_tid)
    if _valid_tool_ids:
        _clean = []
        for _m in _messages:
            if _m.get("role") == "tool":
                _tid = _m.get("tool_call_id")
                if _tid and _tid not in _valid_tool_ids:
                    continue  # 无主 tool：丢弃
            _clean.append(_m)
        _messages = _clean

    # ─── 强大心脏 v2：原生函数调用闭环 ─────
    # 把“你能动手干活”的说明注入 system prompt（明确告诉玄机：要么真调工具，
    # 要么别谎称做了）；真正调用走 DeepSeek 原生 tools 参数。
    _messages[0]["content"] = _build_system_prompt() + "\n\n" + _build_tools_manifest()

    # 公子 2026-10-15：先看活儿大小，再定给几轮
    _max_rounds = _estimate_task_rounds(msg)
    for _round in range(1, _max_rounds + 1):
        msg_resp, ok = _call_llm(_messages)
        if not ok:
            return None
        content = msg_resp.get("content") or ""
        tool_calls = msg_resp.get("tool_calls")

        # 原生工具调用：DeepSeek 结构化工貝调用，玄机强制执行
        if tool_calls:
            # 把模型的 tool_calls 消息原样加入历史（格式：role=assistant + tool_calls）
            _messages.append({"role": "assistant", "content": content or None,
                              "tool_calls": tool_calls})
            for tc in tool_calls:
                try:
                    fn = tc.get("function", {})
                    tool = fn.get("name", "")
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception as e:
                    print("[心脏] 工具参数解析失败: " + str(e))
                    tool, args = "", {}
                print("[心脏] 第" + str(_round) + "轮原生调用工具: " + tool)
                _emit_action("▶ 玄机调用 → " + tool + " " + str(args)[:80])
                result_text, _sc = _run_tool_call(tool, args)
                # 工具结果必须用 role=tool 回填（OpenAI/DeepSeek 原生格式）
                # 🔴 收敛引导：结果后附加提示，引导模型拿到信息后直接回答，避免无限调工具发散
                _messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                                  "content": str(result_text)})
                if tool:
                    _emit_action("  └→ " + tool + " 完成")
            # 🔴 防发散：轮到本次任务上限仍未见收敛，强制结束（用已得信息回答）
            if _round >= _max_rounds:
                print(f"[心脏] 已连续{_round}轮调工具，强制收敛回答")
                # 🔴 收敛不是截断：去掉 tools 再问一次，逼它用文字把已做的事说清楚
                _messages.append({
                    "role": "user",
                    "content": "（系统提示：工具轮数已达上限，立刻停止调用工具，"
                               "直接用一段话回答我上面那句话，说清你刚才做了什么、结论是什么。）",
                })
                _m2, _ok2 = _call_llm(_messages, with_tools=False)
                _tail = ((_m2 or {}).get("content") or "").strip()
                if _ok2 and _tail:
                    _messages.append({"role": "assistant", "content": _tail})
                    _save_memory()
                    return _tail
                return content or "（工具轮数已满，我先停在这里——你直接告诉我下一步做什么。）"
            _save_memory()
            continue   # 有工具调用→继续循环

        # 无工具调用 → 最终回答
        if content:
            _messages.append({"role": "assistant", "content": content})
            _save_memory()
            _turn_count += 1
            if _turn_count % 3 == 0:
                recent = "\n".join(((m.get("content") or "")[:300]) for m in _messages[-6:])
                print("[记忆] 触发自动提取（第" + str(_turn_count) + "轮）")
                _extract_memory_async(recent)
        return content or ""

    print("[心脏] 工具循环达到上限，返回最后一条")
    return content or ""


def ping() -> bool:
    """检查DeepSeek API是否可达"""
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": "Bearer " + _API_KEY},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except:
        return False


def reset_chat():
    """清空对话历史（保留长期记忆，system prompt 用最新人格）"""
    global _messages
    _messages = [{"role": "system", "content": _build_system_prompt()}]
    _save_memory()
    print("[记忆] 对话已清空")
