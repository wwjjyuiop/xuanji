---
name: coding
description: "玄机自主完成编码闭环：写代码、执行测试、出错修改、直到通过。写代码用 DeepSeek v4-pro 最强编码模型，平时用便宜的 flash/chat。"
version: 1.0
author: 玄机
platforms: [windows]
metadata:
  xuanji:
    tags: [编码, 写代码, 重构, 测试, coding]
    related_skills: [hermes, web, subagent]
---

# 编码闭环

让玄机自主完成"写代码 → 执行测试 → 发现问题 → 修改 → 再测 → 通过"的完整闭环。

## When to Use

- 用户要求写一个脚本/程序/函数
- 用户要求修改、重构、修复现有代码
- 用户要求生成并验证一段可运行代码
- 复杂逻辑需要深度思考时（编码任务）

## When NOT to Use

- 只是闲聊或问概念（用便宜模型即可）
- 简单问答不需要写可运行代码

## Key

- 写/改代码用 `deepseek-v4-pro`（最强编码模型，思考深）
- 平时对话用 `deepseek-chat` / `flash`（便宜）
- 入口函数：`coding_skill.code(需求文字)`（coding_skill.py）
- 闭环：生成→写文件→hermes 执行测试→有错带错误信息让模型改→再测→直到通过或达上限(8轮)
- 依赖玄机手脚：write_file / hermes(执行) / subagent(可后台)

## Refinement

待后续使用中优化：可接入更多测试框架、支持多文件项目、加入 lint 检查。
