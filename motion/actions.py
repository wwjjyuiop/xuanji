"""
玄机 · 3D动作引擎 · 动作定义层 motion/actions.py（方案二拆分第1刀）
============================================================
把"动作名白名单 + 动作映射"从 window.py 抽出来成独立数据层。
纯常量，零逻辑，改动不影响任何运行。window.py 引用本模块即可。

作用：
  - 集中维护玄机所有 3D 动作（跳舞/挥手/站立/受击/召唤等）
  - 提供 is_valid_action() 统一校验，避免 window.py 里散落硬编码白名单
  - 为后续"动作播放引擎独立化"打地基（心脏/四肢分离）
"""

# 所有合法 3D 动作名（白名单）
VALID_ACTIONS = frozenset([
    "wave",          # 挥手
    "dance",         # 随机跳一支舞
    "nature",        # nature 舞
    "resonant",      # resonant 舞
    "chip",          # chip 小舞
    "behit",         # 受击
    "standup",       # 站起
    "standctrl",     # 站立控制
    "summon",        # 召唤
    "sayso",         # 动作
    "chenxian",      # 沦陷舞
    "stop",          # 停止所有动作
    "idle",          # 待机
])

# 动作 → 中文描述（供日志/展示用）
ACTION_LABELS = {
    "wave": "挥手",
    "dance": "随机舞蹈",
    "nature": "nature舞",
    "resonant": "resonant舞",
    "chip": "chip小舞",
    "behit": "受击",
    "standup": "站起",
    "standctrl": "站立控制",
    "summon": "召唤",
    "sayso": "动作",
    "chenxian": "沦陷舞",
    "stop": "停止",
    "idle": "待机",
}

# 动作 → VMD 文件名映射（2026-08-30 盘点确认，全命中磁盘）
ACTION_VMD = {
    "wave": "wavefile_v2.vmd",
    "nature": "Ui_Nature_by_奶油桃子.vmd",
    "resonant": "Ui_Resonant_by_奶油桃子.vmd",
    "chip": "琳奈Ui_Chip_by_奶油桃子.vmd",
    "behit": "AM_Behit_B_L.vmd",
    "standup": "AM_StandUp.vmd",
    "standctrl": "standctrl.vmd",  # 修正后的实际文件
    "summon": "AM_Summon.vmd",
    "sayso": "say so motion.vmd",
    "chenxian": "沦陷1.vmd",
}


def is_valid_action(name) -> bool:
    """判断动作名是否合法（统一校验入口）。"""
    return (name or "").strip() in VALID_ACTIONS


def label_of(action) -> str:
    """动作名对应的中文标签，未知返回原名。"""
    return ACTION_LABELS.get(action, action or "")


if __name__ == "__main__":
    # 自检
    print("=== 动作定义层自检 ===")
    print("合法动作数:", len(VALID_ACTIONS))
    assert is_valid_action("wave"), "wave 应合法"
    assert is_valid_action("stop"), "stop 应合法"
    assert not is_valid_action("jump"), "jump 不应合法"
    assert label_of("wave") == "挥手"
    print("is_valid_action('wave')=True  is_valid_action('idle')=True  is_valid_action('jump')=False")
    print("label_of('chenxian')=", label_of("chenxian"))
    # 校验 VMD 映射与动作集一致
    missing = [a for a in VALID_ACTIONS - {"stop", "idle", "dance"} if a not in ACTION_VMD]
    extra = [a for a in ACTION_VMD if a not in VALID_ACTIONS]
    print("VMD映射缺失:", missing or "无")
    print("VMD映射多余:", extra or "无")
    print("=== 自检完成 ===")
