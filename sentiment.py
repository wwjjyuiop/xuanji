"""
玄机 · 情感分析模块 sentiment.py（方案二拆分第4刀辅助）
============================================================
把情感分析（正向/负向/疑问词表 + analyze_sentiment）从 window.py
拆出成独立模块，供 window.py 与 voice_engine 共用。逻辑零改动。
"""

_POSITIVE_WORDS = {
    "开心", "高兴", "好", "棒", "喜欢", "太棒了", "不错",
    "谢谢", "哈哈", "嘻嘻", "真好", "厉害", "优秀", "完美",
    "漂亮", "爱", "美", "好看", "妙", "棒极了",
}

_SAD_WORDS = {
    "难过", "伤心", "哭", "唉", "烦", "不好", "不行", "难受",
    "讨厌", "可惜", "遗憾", "痛", "苦", "悲", "失望", "抱歉",
    "对不起", "坏", "累", "困",
}

_QUESTION_WORDS = {
    "？", "吗", "呢", "吧", "什么", "怎么", "为什么",
    "谁", "哪", "啥", "怎样", "如何",
}


def analyze_sentiment(text):
    if not text:
        return "calm"
    for q in _QUESTION_WORDS:
        if q in text:
            return "question"
    pos = sum(1 for w in _POSITIVE_WORDS if w in text)
    sad = sum(1 for w in _SAD_WORDS if w in text)
    if "😊" in text or "😄" in text or "😍" in text:
        pos += 2
    if "😢" in text or "😭" in text:
        sad += 2
    if pos > sad and pos >= 1:
        return "happy"
    if sad > pos and sad >= 1:
        return "sad"
    return "calm"
