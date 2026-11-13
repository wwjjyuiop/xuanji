# 任务：把玄机的 3D 形象从"播录像"改成"活的数字人"（第一阶段）

## 背景（必读，别重复踩坑）

项目目录：`D:\yuxuanji\xuanji-gui\3d_viewer\`（WSL 路径 `/mnt/d/yuxuanji/xuanji-gui/3d_viewer/`）
主页面：`index.html`（单文件，内联 JS，用 Three.js + MMDLoader 加载 `models/琳奈.pmx`）

**已经查清的事实（不要再推翻重查）**：

1. 模型 `models/琳奈.pmx`（9.2MB）**腿骨齐全**：`左足`/`左ひざ`/`左足首`/`左足ＩＫ`/`左つま先`/右同套，另有 `上半身`/`下半身`/`センター`/`左腕`/`左ひじ`/`左手首`/`左肩`/`左目`/`右目`/`両目` 等。**模型没问题，是代码没用它。**
2. **腿不动的真根因**：`index.html` 里 `_BONE_ALIASES`（约 407 行）只定义了 3 个：`head`、`spine`、`center`。**腿、脚、腰、手指、眼睛全部没有别名**，所以任何驱动都作用不到腿。**第一件事就是把这张表补全。**
3. 现有框架（可直接扩，不要重造）：
   - `_BONE_ACTIONS`（约 423 行）：骨骼动作库，`name -> function(t)`，每帧被调用，把旋转叠加到骨骼上。目前只有 `idle`（只动头）。
   - `setMorph(name, value)` / `setMorphList(list, value)`（约 771/778 行）：表情/口型。
   - 眨眼逻辑（约 819 行 `setMorphList(morphMap.blink, blinkVal)`）与元音口型（约 837 行 `morphTargetInfluences[m.idx] = (vowelIdx === state.mouthVowel) ? state.mouthOpen : 0`）**已经在跑**。
   - `stopAction()`：停止动作并复位全身骨骼（`_resetAllBones()`）—— **已修好，别破坏**。
   - `getState()`：可回读 `playingVmd` / `curVmdAction` / `helperReady` / `mixerDiag` 等。
4. 触发入口：Python 侧（`window.py` / `connector.py` / `coach_channel.py`）**已经修好**（跨线程信号投递），会把动作名发到页面 `window.__xuanji3d.playAction(name)`。**本阶段不要动任何 Python 文件。**

## 目标（本阶段只做这些）

让形象**活起来**：待机时自己走动；被叫时走到镜头前；说话时有口型与自然微动；听指令做动作且腿参与。

## 验收标准（逐条可测，必须给出实测数字）

**A. 待机自由走动**
- 无人对话时，角色在场景里**自由漫游**：位置真的改变（水平位移 > 0.5 单位）、有走路动作（**腿部骨骼摆动**，左右大腿交替，峰值 > 0.15 rad）、会转向、会随机停顿。
- 30 秒内至少发生 **2 次以上的走动段 + 2 次以上朝向改变**；不重复循环（有随机性）。
- 走动范围有边界，不走出场景（不穿模、不掉下去）。

**B. 走近镜头（用户开始说话）**
- 提供接口 `setAttention(mode)`：`wander`（漫游）/ `approach`（凑近）/ `listen`（倾听）/ `speak`（说话）。
- 切到 `approach` 后，角色**走向相机**，相机到角色距离收敛到设定值内（比 wander 状态明显更近），并**面朝相机**（朝向误差 < 15°）。
- 到位后有自然的"站定"过渡（不是瞬移、不是硬切）。

**C. 说话姿态（她说话时）**
- 切到 `speak` 后：停在镜头前、**口型 blend shape 随音频/驱动值变化**（非全 0）、**上身与头部有非零的周期性微动**（幅度小但可见，不是僵住）。
- 停止说话后回到正常站姿。

**D. 倾听姿态（用户说话时）**
- 切到 `listen`：头/眼朝向相机，身体微微前倾或歪头，偶尔点头（周期性的小幅度俯仰）。
- **不要**一直不动。

**E. 指令动作（腿必须参与）**
- 支持至少这些动作名：`walk`（走）、`sit`（坐下）、`stand`（站起来）、`wave`（打招呼/挥手）、`bow`（鞠躬）、`dance`（跳舞）、`stop`（停下回待机）。
- 每个动作**骨骼角度变化超过阈值**（手臂 > 0.3 rad；`sit` 必须**膝盖弯曲 > 0.5 rad**；`dance`/`walk` 必须**腿部摆动**）。
- 每个动作都可以**随时被 `stop` 打断**，打断后**全身骨骼回到初始姿态**（与初始值误差 < 0.01 rad），且**不残留**。
- `sit` 保持坐姿直到 `stand` 或 `stop`。

## 技术约束（硬规矩）

1. **只改 `3d_viewer/` 目录内的文件**。不要动 `window.py` / `connector.py` / `coach_channel.py` / `main.py` / `avatar/`。
2. 改任何既有文件**先备份**（`xxx.bak-<时间戳>`），不许直接覆盖。
3. **不用 VMD 动作文件**。全部动作必须**程序化生成**（代码驱动骨骼旋转/位移），不要新增 `.vmd`。
4. 复用现有框架（`_BONE_ACTIONS` 扩展、`setMorph`、现有 idle/口型/眨眼），不要推翻重写 `index.html` 的加载与渲染骨架。
5. **不许破坏已修好的东西**：`stopAction()` 的全身复位、`_actionEpoch` 守卫、`getState()` 回读、`playAction()` 的现有语义。
6. 所有新动作必须**可打断**：任何时刻调用 `stop`（或切到别的动作）都要干净归位，不能卡在半路。
7. 性能：帧率不能明显下降（本机在软件渲染下本来就吃紧）。不要引入每帧 O(n²) 的操作（例如在骨骼循环里对每根骨骼调用 `updateMatrixWorld(true)`）。
8. 保持与滑鼠/窗口尺寸变化、模型尚在加载时的健壮性（模型没就绪时调用接口不能抛异常）。

## 你要交付的

1. 改完的 `3d_viewer/index.html`（及必要的新文件）。
2. **一个自查脚本**（可以放 `3d_viewer/scripts/`），用 headless Chrome（本机已有可用方案，参考 `scripts/verify_control_chain.js` 的做法）或读日志的方式，对 A–E **逐条输出 PASS/FAIL 和实测数字**。
3. `3d_viewer/PROGRESS.md`：每完成一步追加一行（时间 + 做了什么 + 实测结果）。
4. 最后一段话用中文收口：改了什么、哪些通过、哪些没通过、还剩什么。

## 环境提示

- 页面本地提供在 `http://127.0.0.1:18796`（玄机客户端内嵌浏览器用），Actions 在 `/actions/`。
- 运行时诊断通道：`POST http://127.0.0.1:18798/eval`，body `{"js":"<一段JS>"}`，结果会打印到 `D:\yuxuanji\xuanji-gui\_xuanji_stdout.log` 的 `[EVAL] 结果` 行。**注意**：此通道需要玄机客户端在运行。
- headless 验证时若 Chrome 首次启动慢/卡，先 `pkill -9 -f "[g]oogle-chrome"` 清干净再来。
- 软件渲染下帧率抖动大，**测量要用"多次采样取中位数"或按帧计数判断**，不要用单次时间差下结论（历史上被这个假象坑过）。
