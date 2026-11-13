# 任务：找出驱动「腿」的骨骼，让 sit 动作在画面上真的蹲下去

## 背景（一句话）
玄机 GUI 的 3D 页面 `3d_viewer/index.html`（Three.js + 手改过的 MMDLoader/MMDAnimationHelper，模型 `models/琳奈.pmx`）。
已实现程序化动作库（不用 VMD）：idle / walk / sit / stand / wave / bow / dance。
**除 sit 外全部验证通过**（walk 位移、approach 走到镜头前、wave 手臂抬 1.1rad、dance 大腿反向摆 0.5rad、stop 归位误差 0.005）。

## 唯一要解决的问题
**sit 动作：读数 100% 正确，画面上腿纹丝不动。**

实测证据（务必先读懂，别重复劳动）：
- 调 `getBoneAngles('thighL,kneeL,ankleL')` → `thighL.rot=[-1.3,0,0]`、`kneeL.rot=[1.5,0,0]`，重心 `_centerY` 从 10.1634 降到 9.5434（降 0.62）。**数据全对。**
- 但截图里腿是笔直的。
- 绕过动作系统，直接用诊断口把 `左足`（大腿）拧 -1.5rad：
  - `左足` 的世界坐标不变（0.92,11.41,-0.11，因为它在根部）
  - **`左ひざ` 世界坐标从 (1.06,6.42,-0.38) 变成 (1.05,10.77,4.84)**
  - **`左足首` 世界坐标从 (1.13,1.44,-0.85) 变成 (1.13,9.96,9.77)**
  - → **骨架链确实动了，但画面上腿不动。**
- 决定性实验：把 `mesh.skeleton.bones` 里**全部 412 根骨骼**一起 `rotation.x += 1.5708` 并逐根 `updateMatrixWorld(true)` + `mesh.skeleton.update()` → **画面整个塌掉**（人只剩两条腿立着）。
  - → **蒙皮是正常跟随骨骼的**，渲染层没问题。
  - → 结论：**单独拧 `左足` 不动画面，说明驱动她腿的蒙皮骨骼不是 `mesh.skeleton.bones` 里第一个叫 `左足` 的那根**（同名骨骼有多个；也可能腿的蒙皮挂在别的骨骼上）。
- 已排除：IK（`_mmdHelper` 根本不存在、`geometry.userData.MMD.iks` 已被清空为 0）、D 变形骨骼（该模型没有 `足D/ひざD` 这类骨骼）、骨骼矩阵刷新（`_setR` 里已加 `updateMatrixWorld(true)`）。

## 你的目标（就这一件事）
**找出到底哪根（或哪几根）骨骼驱动腿部的蒙皮，并让 `sit` 在画面上真的蹲下去。**
判定标准（硬性）：调用 `window.__xuanji3d.playAction('sit')` 后 3 秒，**截图里她的膝盖明显弯曲、身体高度明显下降**。

## 可用的工具（页面里已经写好的诊断接口，直接调，不要自己再造）
通过 HTTP 往 `http://127.0.0.1:18798/eval` POST `{"js": "<JS 代码>"}`，代码会在页面模块作用域里执行，结果打到 `D:\yuxuanji\xuanji-gui\_xuanji_stdout.log` 的 `[EVAL] 结果:` 行。

- `window.__xuanji3d.debugEval('<code>')` — **万能口**，在模块作用域 eval，能直接摸到 `mesh`、`mesh.skeleton`、`_B`、`_BONE_ALIASES` 等所有变量。返回值会 JSON 化。
- `window.__xuanji3d.getBoneAngles('thighL,kneeL,ankleL,_center')` — 读别名字典里的骨骼角度
- `window.__xuanji3d.getBoneWorld('thighL,kneeL,ankleL')` — 读骨骼世界矩阵平移
- `window.__xuanji3d.getBonesFull()` — 全部骨骼名数组
- `window.__xuanji3d.forceBone('key或MMD骨骼名', x, y, z)` — 直接设某根骨骼旋转并刷新
- `window.__xuanji3d.ikState()` — IK 状态
- `window.__xuanji3d.playAction('sit'|'stop'|'wave'|'dance'|...)`

**注意：JS 里不要写中文字面量**（会因转义变成 `ReferenceError: 左足 is not defined`）。用 `String.fromCharCode(0x5DE6,0x8DB3)` 或按骨骼名长度/索引筛选。

## 建议的排查方向（自由发挥，但别跑偏）
1. 用 `debugEval` 遍历 `mesh.skeleton.bones`，统计**与 `mya` 类骨骼名重复的项**：`左足` 出现几次、index 分别是多少、各自 `parent.name` 是什么。
2. 逐个单独拧（每次只拧一根，其他不动）+ 读世界矩阵 + 观察画面差异，锁定"拧了画面会动"的那一根。
3. 检查 `mesh.geometry.attributes.skinIndex`（哪些骨骼被顶点权重引用），直接看腿的顶点绑定的是哪几根骨骼 index。
4. 找到后，在 `index.html` 的 `_BONE_ALIASES` / `_cacheBones` 里把 `thighL/thighR/kneeL/kneeR/ankleL/ankleR` 重定向到正确的骨骼对象，让 `_setR` 生效。

## 硬性约束（违反即视为失败）
1. **禁止运行任何浏览器 / headless 测试**。不要执行 `node scripts/*.js`、不要启动 chrome/chromium/edge、不要用 puppeteer/playwright/CDP、不要 pkill 浏览器进程。**验证一律走上面的 `/eval` 口 + 读日志 + 截图**。
2. **改文件前必须备份**：`cp -a index.html index.html.bak-<你的标记>-<时间戳>`。
3. **改完必须跑 `node --check`**：把 `<script type="module">` 内容抽出来存成 `.mjs` 再 `node --check`。语法必须 PASS。
4. **只许改 `3d_viewer/index.html`**（以及必要时 `3d_viewer/lib/` 下的库文件，但改库要说明理由）。**严禁碰 `window.py`、`connector.py`、`coach_channel.py` 等主程序**。
5. 不要动 `actions/` 目录下已有的 10 个 VMD 文件。
6. 改代码时不要引入中文注释以外的东西；保持现有代码风格。

## 交付物
1. `index.html` 的改动（附 `diff` 说明改了哪几行、为什么）。
2. 在 `3d_viewer/PROGRESS.md` 追加一段：你找到的骨骼是哪一个（名字 + index + 父级）、你是怎么确认的、sit 后的读数与截图路径。
3. 明确结论：**sit 在画面上到底蹲下去没有**（"是"或"否"，不许含糊）。

## 环境
- 页面：`http://127.0.0.1:18796`（玄机内嵌浏览器）
- `/eval` 口：`http://127.0.0.1:18798/eval`（POST `{"js":"..."}`）
- 日志：`D:\yuxuanji\xuanji-gui\_xuanji_stdout.log`
- 工作目录：`/mnt/d/yuxuanji/xuanji-gui/3d_viewer/`
- 截图目录（参考）：`/mnt/d/openClaw/workspace/xj_shots/`
