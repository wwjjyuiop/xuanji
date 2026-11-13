# 任务书：让玄机 3D 形象的动作真正播出来

> 这份文件是交给 Claude Code 的指令。目标、边界、验收标准都写在这里。
> 项目：玄机 GUI 的 3D 形象页（/mnt/d/yuxuanji/xuanji-gui/3d_viewer/）

## 一、现状（不是空白项目，请先看懂再动手）

- 页面：`index.html`，用 Three.js r163 + MMDLoader 加载 MMD 模型 `琳奈.pmx`，跑在 PySide6 的 QWebEngineView 里（也有本地 http.server 方式，页面端口 18796）。
- 动作文件已经在仓库里，共 10 个（`actions/` 目录），格式是 MMD 的 `.vmd`：
  - `wavefile_v2.vmd`（挥手）
  - `沦陷_by_哈基鹿鹿鹿_.../沦陷1.vmd`（一支舞）
  - 还有 standup / standctrl / summon / behit / chip / nature / resonant / sayso
- **问题：这些 VMD 动作播不出来。** 从 2026-08-27 到 09-01 前后改过二十多个版本（同目录下二十多个 `index.html.bak-*`），最后没解决就搁置了。
- 历史遗留的疑点（都在 `lib/` 和代码里）：
  - Three.js 的 MMD 三个官方库 `MMDAnimationHelper.js` / `MMDPhysics.js` / `CCDIKSolver.js` 都被**手动改过**（每个都有 `.bak-orig` 和 `.bak-r163fix-*`）。
  - `ammo.wasm.js` 旁边有一个 `ammo.wasm.js.bak-broken-*`（曾弄坏过的版本）。
  - 代码里同时存在两套方案：A = 播外部 VMD（`MMDAnimationHelper`，当前 `physics:false`、IK 已关）；B = 用代码直接驱动骨骼（手搓）。
  - 目标动作是"外部 VMD 动作"，方案 B 不是本次要修的。

## 二、目标（唯一，别的都别做）

让**挥手（wavefile_v2.vmd）**和**一支舞（沦陷1.vmd）**这两个 VMD 动作在 3d_viewer 页面里正常播放：

1. 姿态正确（挥手像挥手，舞蹈动作完整，不是抽搐、穿模、原地乱抖）；
2. 能明显看出动作从开始到结束播了一遍；
3. 播完能停下并回到待机（现在待机是静态下垂，那是既有验收结果，别改）。

## 三、硬要求（违反任何一条就算没做完）

1. **先诊断，不要盲改。** 必须说清"卡在哪一环"，并给出证据（具体代码行、运行时日志、加载返回值）：
   - 是依赖缺失（MMDLoader 的 import 链）？库版本不匹配（r163 vs 手改的 addon）？ammo 加载失败？VMD 与模型骨骼名不匹配？mixer/helper 更新顺序？还是 QWebEngineView 的环境限制？
2. **必须自带可自动判定的验收脚本**，不许用"我觉得应该行了"来交差。脚本要给出明确的 PASS/FAIL，判据可以是（任选或组合）：
   - 骨骼世界坐标/rotation 在播放期间的变化量；
   - 同一机位在不同时刻截图的像素差；
   - 与"静止基线"对比的差异面积。
   跑一次要能看到实测数字。
3. **只许改 `/mnt/d/yuxuanji/xuanji-gui/3d_viewer/` 里的文件。** 改任何文件前先备份成 `.bak-<时间戳>`。不许改 xuanji-gui 根目录的 Python 主程序，不许装新包，不许访问外网。
4. **优先走"恢复官方库 + 版本对齐"的路子**（Three.js 官方 examples 对应版本的 MMDAnimationHelper/MMDPhysics/CCDIKSolver + 配套 ammo.js），而不是继续手改官方库——手改正是这两年没修好的原因之一。
5. 不要动待机动作、表情、口型、眨眼、相机取景这些已经验收过的部分。

## 四、交付物（三样，缺一不可）

1. 改了/加了哪些文件（列表 + 一句话说明每个的作用）；
2. 验收脚本的**实测输出**（贴原始输出，含 PASS/FAIL 和数字）；
3. 一句人话结论：成了 / 没成 / 卡在哪一环、下一步需要什么。

## 五、参考（可读，不要照抄）

- `~/.hermes/skills/software-development/3d-avatar-pipeline/SKILL.md`（历史坑全在这，尤其"3D 加载不出来的真根因：MMDLoader 依赖缺失"和"骨骼动画看不见动的验证方法论"）
- `~/.hermes/skills/software-development/3d-avatar-pipeline/references/3d-mmd-loader-fix.md`
- `~/.hermes/skills/software-development/3d-avatar-pipeline/scripts/verify_anim_pose.py`（历史上验证动作姿态用的脚本模板）
