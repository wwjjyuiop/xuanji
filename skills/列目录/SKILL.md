---
name: 列目录
description: "用户让玄机列出某个目录内容时使用"
version: 1.1
author: 玄机
platforms: [windows]
metadata:
  xuanji:
    tags: [文件, 目录, 查询]
    related_skills: [search_file]
---

# 列目录

# 列目录

当用户说'列一下/看下 XX目录'时，用 dispatch 的 dir/hermes 列出目录内容。

## When to Use

用户询问目录/文件夹里有什么；要确认某路径是否存在。

## When NOT to Use

用户只是闲聊；用户要的是启动程序而非列目录。

## How

1. 从 request 提取路径
2. 调 dispatch['dir'] 或 hermes
3. 把结果整理成列表回复

## Refinement

(待补充：后续使用中如何优化)
