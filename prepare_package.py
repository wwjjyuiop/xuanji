# -*- coding: utf-8 -*-
"""玄机 · 打包准备脚本

用途：把当前已配好 Key 的开发版，清理成一份可以发给他人使用的版本。
做法：
  1. 备份当前 .env（保留你自己的工作 Key，绝不丢失）
  2. 把主推理(DeepSeek) / 多模态(千问) 两个 Key 清空为空
  3. 打印提示：对方拿到后，在设置 > API 配置 里填自己的 Key 即可用

运行：python3 prepare_package.py
"""
import os
import shutil
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENV = os.path.join(_HERE, ".env")


def main():
    if not os.path.isfile(_ENV):
        print("[打包] 未找到 .env，跳过。")
        return

    # 1) 备份
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(_HERE, ".env.bak-%s" % ts)
    shutil.copy2(_ENV, bak)
    print("[打包] 已备份 .env -> %s" % bak)

    # 2) 清空两个 Key（保留其它配置如 QQ/Baidu）
    lines = []
    with open(_ENV, encoding="utf-8") as f:
        lines = f.readlines()
    keys = {"DEEPSEEK_API_KEY", "QWEN_API_KEY"}
    changed = []
    for i in range(len(lines)):
        s = lines[i].strip()
        if "=" in s and not s.startswith("#"):
            k = s.partition("=")[0].strip()
            if k in keys and s.partition("=")[2].strip():
                lines[i] = k + "=\n"
                changed.append(k)
    with open(_ENV, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # 3) 同步清空运行中模块内存（如果程序在跑）
    try:
        import api_config
        api_config.clear_all_keys()
        print("[打包] 已清空运行中的 Key 缓存。")
    except Exception as e:
        print("[打包] 运行时缓存未清（程序未运行或已不缓存）: %s" % e)

    print("[打包] 已清空 Key: %s" % (", ".join(changed) if changed else "（原本就为空）"))
    print()
    print("打包完成。此 .env 可直接随程序分发。")
    print("接收方打开程序后：设置 > API 配置 > 填入自己的主推理Key/多模态Key > 保存，即可使用。")


if __name__ == "__main__":
    main()
