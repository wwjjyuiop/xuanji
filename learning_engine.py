"""
玄机 · 学习引擎 learning_engine.py（按 Hermes 理论构建）
============================================================
Hermes 学习理论核心：skill 是可沉淀的 Markdown 技能文件（SKILL.md，
带 frontmatter：name/description/related_skills/tags），agent 干完
有套路的事后能自动创建技能（agent-created skill），并用「相关技能 +
使用计数」构建学习图谱，把「学到的技能」与「记住的事」连起来。

本模块按这套理论给玄机建：
  1. search_skill(task)     干活前先在玄机技能库找现成技能
  2. create_skill(...)      干完有套路的活，自动沉淀成 SKILL.md
  3. learning_graph()       用技能库+使用计数生成"玄机学会了什么"概览
  4. tick_skill(name)       使用一次技能就记一次数（学习图谱原料）

玄机技能库目录：xuanji-gui/skills/（每个技能一个子目录，SKILL.md）
"""

import os
import re
import json
import time
from datetime import datetime

# ─── 机器学习循环（方案三 · 3.6）：开工前调 learning_preflight ──
def learning_preflight(task: str) -> str:
    """开工前哨（3.6 学习循环第1步）：查技能库现成方案 + 查教训库避免重犯。
    返回一段提醒文本（无相关则返回空）。"""
    hints = []
    # 1. 技能库找现成技能
    try:
        hit = search_skill(task)
        if hit:
            hints.append(f"[现成技能] '{hit['name']}' 之前干过类似的事: {hit.get('description','')}")
            tick_skill(hit["name"])  # 用一次计一次数
    except Exception as _e:
        pass
    # 2. 教训库找避坑提醒（复用 memory_service）
    try:
        import memory_service as _ms
        lessons = _ms.get_service().relevant_lessons(task)
        for l in lessons:
            hints.append(f"[前车之鉴] {l}")
    except Exception:
        pass
    return "\n".join(hints)

# 兜底：Windows 控制台默认 GBK，这里强制 UTF-8，避免特殊字符打印崩掉
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 玄机技能库根目录（与 Hermes ~/.hermes/skills 对齐的设计）
SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
# 学习图谱数据（技能使用计数、创建记录）
GRAPH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_learning_graph.json")

_SKILL_TEMPLATE = """---
name: {name}
description: "{desc}"
version: {version}
author: 玄机
platforms: [windows]
metadata:
  xuanji:
    tags: [{tags}]
    related_skills: [{related}]
---

# {title}

{summary_lines}

## When to Use

{whentouse}

## When NOT to Use

{notwhentouse}

## How

{how}

## Refinement

{refine}
"""


# ─── 工具函数 ─────────────────────────────────────────
def _ensure_dirs():
    os.makedirs(SKILLS_DIR, exist_ok=True)


def _slug(name: str) -> str:
    """把中文/任意文本转成安全目录名（保留中文，去空格/特殊符）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", name.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "skill"


def _load_graph() -> dict:
    try:
        if os.path.isfile(GRAPH_FILE):
            with open(GRAPH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"skills": {}, "created": []}


def _save_graph(g):
    try:
        with open(GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump(g, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─── 1. 搜索技能：干活前查找现成技能 ─────────────────
def _parse_frontmatter(text: str) -> dict:
    """解析 SKILL.md 的 --- frontmatter ---，返回 dict。"""
    result = {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return result
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            result[k.strip()] = v.strip().strip('"')
    return result


def search_skill(task: str):
    """在玄机技能库里找与 task 相关的技能。返回 skill 信息或 None。

    用 bigram(2字滑动窗口)重合 + 关键词匹配，容忍"看下D盘目录"命中"列目录"。
    """
    _ensure_dirs()
    if not os.path.isdir(SKILLS_DIR):
        return None
    task_lower = (task or "").lower()
    best = None
    best_score = 0
    for root, _, files in os.walk(SKILLS_DIR):
        if "SKILL.md" not in files:
            continue
        try:
            text = open(os.path.join(root, "SKILL.md"), encoding="utf-8").read()
        except Exception:
            continue
        fm = _parse_frontmatter(text)
        name = fm.get("name") or os.path.basename(root)
        desc = fm.get("description") or ""
        body = re.sub(r"^---.*?\n---", "", text, flags=re.S)  # 去 frontmatter
        haystack = name + " " + desc + " " + body

        score = 0
        # 1) 名字完全/包含
        if task_lower == name.lower():
            score += 100
        elif name.lower() in task_lower or task_lower in name.lower():
            score += 60
        # 2) 任务的 2字 bigram 是否出现在技能里（核心召回）
        task_bigrams = {task_lower[i:i+2] for i in range(len(task_lower)-1)
                        if "一" <= task_lower[i] <= "鿿"}
        hit = sum(1 for b in task_bigrams if b in haystack)
        score += hit * 10
        # 3) 技能的 2字 bigram 在任务里出现的锚点词（如"看下""目录"）
        skill_bigram_hit = 0
        for sk in set(haystack[i:i+2] for i in range(len(haystack)-1)
                      if "一" <= haystack[i] <= "鿿"):
            if sk in task_lower and sk not in ("用户", "目录是", "是用", "列出", "时使", "存在"):
                skill_bigram_hit += 1
        score += skill_bigram_hit * 5

        if score > best_score:
            best_score = score
            best = {"name": name, "path": os.path.join(root, "SKILL.md"),
                    "description": desc, "score": score}
    if best and best_score >= 12:
        return best
    return None


# ─── 2. 创建技能：干完有套路的活，自动沉淀 ──────────
def create_skill(name: str, description: str, summary: str = "",
                 when_to_use: str = "", when_not: str = "",
                 how: str = "", tags: list = None, related: list = None):
    """把一件干成的事沉淀成 SKILL.md（agent-created skill）。

    返回技能目录路径。
    """
    _ensure_dirs()
    tags = tags or []
    related = related or []
    slug = _slug(name)
    skill_root = os.path.join(SKILLS_DIR, slug)
    os.makedirs(skill_root, exist_ok=True)

    version = 1.0
    skill_path = os.path.join(skill_root, "SKILL.md")
    if os.path.isfile(skill_path):
        # 已存在则版本+0.1（参考 Hermes version 递增）
        old = _parse_frontmatter(open(skill_path, encoding="utf-8").read())
        try:
            version = round(float(old.get("version", 1.0)) + 0.1, 1)
        except Exception:
            version = 1.1

    title = name
    summary_lines = ("# " + title + "\n\n" + summary.strip()) if summary else ("# " + title)
    content = _SKILL_TEMPLATE.format(
        name=name, desc=description.replace('"', "'"), version=version,
        tags=", ".join(tags), related=", ".join(related),
        title=title,
        summary_lines=summary_lines,
        whentouse=when_to_use or "(待补充：哪些情况用这个技能)",
        notwhentouse=when_not or "(待补充：哪些情况不要用)",
        how=how or "(待补充：具体怎么做)",
        refine="(待补充：后续使用中如何优化)",  # Hermes 的 skill 会随使用优化
    )
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 记入学习图谱
    g = _load_graph()
    g["skills"][slug] = {
        "name": name, "created": datetime.now().isoformat(timespec="seconds"),
        "version": version, "use_count": 0, "description": description,
    }
    g["created"].append({"name": name, "when": datetime.now().isoformat(timespec="seconds"), "slug": slug})
    _save_graph(g)
    print(f"[学习] 已沉淀技能: {name} (v{version}) -> {skill_path}")
    return skill_path


# ─── 3. 使用计数：技能被用一次，graph 记一次 ─────────
def tick_skill(name: str):
    g = _load_graph()
    slug = _slug(name)
    if slug in g["skills"]:
        g["skills"][slug]["use_count"] = g["skills"][slug].get("use_count", 0) + 1
        g["skills"][slug]["last_used"] = datetime.now().isoformat(timespec="seconds")
    else:
        g["skills"][slug] = {"name": name, "use_count": 1,
                             "created": datetime.now().isoformat(timespec="seconds"),
                             "version": 1.0, "description": ""}
    _save_graph(g)


# ─── 技能工坊（方案三 · 3.1 学 OpenClaw skill-workshop）───
# 完整流程：提案 → 审查 → 落地 → 使用计数 → 过期归档

def propose_skill(name: str, description: str, how: str, tags: list = None) -> dict:
    """提案一个技能（先不落地成 SKILL.md，进提案区待审查/落地）。
    返回提案信息。主要给玄机在"干完一件有套路的事"后先提案，再由学环确认真实有效才落地。"""
    _ensure_dirs()
    slug = _slug(name)
    prop_dir = os.path.join(SKILLS_DIR, slug)
    os.makedirs(prop_dir, exist_ok=True)
    prop_file = os.path.join(prop_dir, "PROPOSAL.md")
    content = (
        "---\n"
        f"proposal: {name}\n"
        f"description: \"{description.replace(chr(34), chr(39))}\"\n"
        f"status: pending\n"
        f"proposed: {datetime.now().isoformat(timespec='seconds')}\n"
        "---\n"
        "# 技能提案\n\n"
        f"## 要干的事\n{how}\n\n"
        "## 何时该用\n(待审查填)\n\n"
        "## 落地条件\n(验证有效后由学环落地为 SKILL.md)\n"
    )
    with open(prop_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[学习] 技能提案已建: {name} -> {prop_file}")
    return {"ok": True, "prop_file": prop_file, "name": name}


def archive_stale(days: int = 30) -> int:
    """过期归档：超过 days 天没用过的技能，打 stale 标记（不删文件，只标）。
    返回标记数。"""
    g = _load_graph()
    skills = g.get("skills", {})
    archived = 0
    now = datetime.now()
    for slug, info in list(skills.items()):
        last = info.get("last_used") or info.get("created")
        if not last:
            continue
        try:
            dt = datetime.fromisoformat(last)
        except Exception:
            continue
        if (now - dt).days > days and info.get("stale") is not True:
            info["stale"] = True
            info["note"] = f"{days}天未用，已归档待复习"
            archived += 1
    if archived:
        _save_graph(g)
        print(f"[学习] 归档 {archived} 个过期技能（>={days}天未用）")
    return archived


def confirm_proposal(name: str, summary: str = "", when_to_use: str = "", how: str = "", tags: list = None) -> str:
    """学环确认有效后，把提案落地为正式 SKILL.md（工坊最后一步）。"""
    return create_skill(
        name=name,
        description=summary or name,
        summary=summary,
        when_to_use=when_to_use,
        how=how,
        tags=tags or [],
    )


# ─── 4. 学习图谱：玄机学会了什么 ─────────────────────
def learning_graph() -> str:
    """用技能库+使用计数生成"玄机学会了什么"概览（Hermes learning_graph 简化版）。"""
    _ensure_dirs()
    g = _load_graph()
    skills = g.get("skills", {})
    if not skills and not os.path.isdir(SKILLS_DIR):
        return "玄机还没学会任何技能。"
    lines = ["玄机的技能图谱："]
    # 按使用次数排序
    for slug, info in sorted(skills.items(), key=lambda x: x[1].get("use_count", 0), reverse=True):
        lines.append(f"  •  {info.get('name', slug)}  (用 {info.get('use_count',0)} 次, v{info.get('version',1.0)})")
    if not skills:
        lines.append("  （技能库目录存在，但还没有技能记录）")
    # 记忆关联提示
    lines.append("")
    lines.append("玄机记忆中的画像字段可关联技能，用于回答'我学到的技能跟我记的事有关吗'。")
    return "\n".join(lines)


# ─── 自检 ──────────────────────────────────────────
def self_test():
    print("=== 玄机学习引擎自检（按 Hermes 理论）===")
    # 1. 创建一个示例技能（模拟玄机干完一件有套路的活后沉淀）
    p = create_skill(
        name="列目录",
        description="用户让玄机列出某个目录内容时使用",
        summary="当用户说'列一下/看下 XX目录'时，用 dispatch 的 dir/hermes 列出目录内容。",
        when_to_use="用户询问目录/文件夹里有什么；要确认某路径是否存在。",
        when_not="用户只是闲聊；用户要的是启动程序而非列目录。",
        how="1. 从 request 提取路径\n2. 调 dispatch['dir'] 或 hermes\n3. 把结果整理成列表回复",
        tags=["文件", "目录", "查询"],
        related=["search_file"],
    )
    tick_skill("列目录")
    tick_skill("列目录")
    print()
    print(learning_graph())
    print()
    print("=== 搜索技能测试 ===")
    hit = search_skill("帮我看下 D 盘目录")
    print("搜'帮我看下目录' -> ", hit["name"] if hit else None)
    hit2 = search_skill("今天天气")
    print("搜'今天天气' -> ", hit2["name"] if hit2 else None)
    print("=== 自检完成 ===")


if __name__ == "__main__":
    self_test()
