# 任务：把腿部动作接到 D 变形骨骼上，让 sit 在画面上真的蹲下去

## 唯一目标
`3d_viewer/index.html` 里，让 `window.__xuanji3d.playAction('sit')` 之后 3 秒，**画面上她的膝盖明显弯曲、身体高度明显下降**。

## 根因已经查明（不要再自己勘探，直接照做）
运行时从 `geometry.attributes.skinIndex/skinWeight` 统计出：**腿部的蒙皮全部绑在带 `D` 后缀的变形骨骼上**，不是 `左足/右ひざ` 那些。

实测（342 根参与蒙皮的骨骼里权重最高的几根，格式 `index|骨骼名|权重和`）：
```
23|頭|13615
21|上半身2|3913
17|下半身|3608
404|右足D|1923
410|左足首D|1882
406|右足首D|1881
407|右足先EX|1681
411|左足先EX|1680
405|右ひざD|1295
409|左ひざD|1121
408|左足D|1104
```
所以：
- **右腿**：`右足D`(404) / `右ひざD`(405) / `右足首D`(406) / `右足先EX`(407)
- **左腿**：`左足D`(408) / `左ひざD`(409) / `左足首D`(410) / `左足先EX`(411)

现在 `_BONE_ALIASES` 里的 `thighL/thighR/kneeL/kneeR/ankleL/ankleR` 接的是不带 D 的骨骼，**皮根本不听它们的** —— 这就是"读数全对、画面不动"的原因。

另外：这些 D 骨骼在 MMD 里本该由"付与(grant)"求解器每帧从 `左足/ひざ` 算出来，但本页的 `_mmdHelper` **从未被初始化**（实测 `helperExists:false`），所以 D 骨骼一直卡在初始姿态。

## 你要做的事（二选一，推荐第一种）
**方案一（推荐，最小改动）**：在 `_BONE_ALIASES` 里把腿的别名直接指向 D 骨骼：
- `thighL` → `左足D`，`thighR` → `右足D`
- `kneeL` → `左ひざD`，`kneeR` → `右ひざD`
- `ankleL` → `左足首D`，`ankleR` → `右足首D`

如果 `_BONE_ALIASES` 的值是候选名数组（`_findBoneWithAlias` 逐个试），就把 D 名字放在**数组最前面**。

**方案二**：在 `_cacheBones()` 之后追加一段，把 `_B[thighL/kneeL/ankleL/thighR/kneeR/ankleR]` 重新用 `findBone('左足D')` 之类覆盖一次。

**注意**：D 骨骼是叶子/变形骨骼，直接给它设 `rotation` 应该就能带动蒙皮（这正是它存在的意义）。如果发现单纯设 `rotation` 不够，可以同时设非 D 的原骨骼，但**优先只动 D**。

## 硬性约束（违反即失败）
1. **禁止运行任何浏览器 / headless 测试**。不执行 `node scripts/*.js`、不启动 chrome/chromium/edge、不用 puppeteer/playwright/CDP、不 pkill 浏览器。
2. **禁止勘探二进制**：不要 `xxd`/`dd`/`grep -aob` 读 `琳奈.pmx`。根因已给出，不需要你考古。
3. **改前必须备份**：`cp -a index.html index.html.bak-dbone-<时间戳>`。
4. **改后必须 `node --check` PASS**：抽出 `<script type="module">` 内容存成 `.mjs` 再 `node --check`。
5. **只许改 `3d_viewer/index.html`**。严禁碰 `window.py` / `connector.py` / `coach_channel.py`。
6. 不要动 `actions/` 目录下的 VMD 文件。

## 验证方式（只能这样验，不许开浏览器）
通过 Windows 侧 PowerShell 发 HTTP 请求到诊断口（**注意：必须从 Windows 侧发，WSL 的 127.0.0.1 不通**）：
```powershell
$body = @{ js = "window.__xuanji3d.playAction('sit')" } | ConvertTo-Json -Compress
Invoke-WebRequest -Uri 'http://127.0.0.1:18798/eval' -Method POST -Body $body -ContentType 'application/json' -UseBasicParsing
```
然后读日志 `D:\yuxuanji\xuanji-gui\_xuanji_stdout.log` 里的 `[EVAL] 结果:` 行。
可用接口：`getBoneAngles('thighL,kneeL,ankleL')`、`getBoneWorld('thighL,kneeL,ankleL')`、`debugEval('<js>')`、`playAction('sit'|'stop')`。

## 交付物
1. `index.html` 的改动 + `diff` 说明（改了哪几行、为什么）。
2. 追加写入 `3d_viewer/PROGRESS.md`：你改了哪里、sit 后的 `getBoneAngles` 读数、以及**你认为画面会不会蹲下去**。
3. 明确结论："sit 在画面上蹲下去了" 或 "仍然没蹲"（不许含糊）。

## 环境
- 页面 3D：`http://127.0.0.1:18796`
- 诊断口：`http://127.0.0.1:18798/eval`（POST `{"js":"..."}`）
- 日志：`D:\yuxuanji\xuanji-gui\_xuanji_stdout.log`
- 工作目录：`/mnt/d/yuxuanji/xuanji-gui/3d_viewer/`
