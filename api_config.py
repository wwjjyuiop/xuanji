# -*- coding: utf-8 -*-
"""玄机 · API Key 统一管理中枢

职责：
1. 启动时统一读取 .env 里的主推理(DeepSeek) / 多模态(千问) 两个 Key
2. 提供 save_*() 接口：写入 .env + 热更新各模块内存变量，改完立即生效(无需重启)

为什么需要它：
connector / voice_output 等模块都是在 import 时各自读 .env 一次存到内存，
改 .env 不重启不会生效。本模块统一管理并同步刷新各模块的全局变量，
让设置窗口保存 Key 后立即生效。
"""
import os

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

# ─── 当前生效的 Key（本模块是权威来源） ───
DEEPSEEK_KEY = ""
QWEN_KEY = ""


def _read_env():
    """读 .env，返回 {键名: 值} 字典（无文件或空返回空 dict）"""
    result = {}
    if os.path.isfile(_ENV_PATH):
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if "=" in s and not s.startswith("#"):
                    k, _, v = s.partition("=")
                    result[k.strip()] = v.strip()
    return result


def _write_env(updates):
    """保留 .env 其它内容，仅更新传入的键值；键已存在则原位替换，不存在则追加"""
    lines = []
    if os.path.isfile(_ENV_PATH):
        with open(_ENV_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    # 逐行更新已存在键，记录哪些键被更新
    updated = set()
    for i in range(len(lines)):
        s = lines[i].strip()
        if "=" in s and not s.startswith("#"):
            k = s.partition("=")[0].strip()
            if k in updates:
                lines[i] = k + "=" + updates[k] + "\n"
                updated.add(k)
    # 追加未存在的键
    for k, v in updates.items():
        if k not in updated:
            lines.append("\n" + k + "=" + v + "\n")
    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _hot_update():
    """同步热更新各模块内存里的 Key 全局变量（立即生效）"""
    try:
        import connector
        connector._API_KEY = DEEPSEEK_KEY
        connector._QWEN_KEY = QWEN_KEY
    except Exception as e:
        print("[api_config] 热更新 connector 失败: " + str(e))
    try:
        import voice_output
        voice_output._K = QWEN_KEY
    except Exception as e:
        print("[api_config] 热更新 voice_output 失败: " + str(e))
    # voice_input 是每次现读 .env（无缓存），已写入 .env 即可生效，无需改内存


def load():
    """启动时调用：读取 .env，填充本模块全局变量"""
    global DEEPSEEK_KEY, QWEN_KEY
    env = _read_env()
    DEEPSEEK_KEY = env.get("DEEPSEEK_API_KEY", "")
    QWEN_KEY = env.get("QWEN_API_KEY", "")
    return DEEPSEEK_KEY, QWEN_KEY


def save_deepseek_key(key):
    """保存主推理(DeepSeek) Key：写入 .env + 热更新"""
    global DEEPSEEK_KEY
    DEEPSEEK_KEY = (key or "").strip()
    _write_env({"DEEPSEEK_API_KEY": DEEPSEEK_KEY})
    _hot_update()
    return DEEPSEEK_KEY


def save_qwen_key(key):
    """保存辅助多模态(千问) Key：写入 .env + 热更新"""
    global QWEN_KEY
    QWEN_KEY = (key or "").strip()
    _write_env({"QWEN_API_KEY": QWEN_KEY})
    _hot_update()
    return QWEN_KEY


def clear_all_keys():
    """打包用：清空两个 Key（写入 .env 空值 + 热更新清空内存）"""
    return save_deepseek_key(""), save_qwen_key("")


# 模块导入时自动加载一次（保持与 connector 等一致的启动读取行为）
load()
