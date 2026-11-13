# 玄机 3D 页面 · Claude Code 工作规矩

> 这个文件每次会话自动加载。**照它做，不要自己另立一套。**

## 一、这个项目是什么

- 玄机（虚拟数字人）的 3D 展示页，**单文件应用**：`3d_viewer/index.html`
- 技术栈：Three.js + MMDLoader，JS 全部内联在 `index.html` 里
- 模型：`3d_viewer/models/琳奈.pmx`（412 根骨骼，其中 342 根参与蒙皮）
- **运行环境是 Windows，不是 WSL**。页面跑在 Windows 侧的 pythonw 进程里。
- 驱动方式：WSL 侧脚本 → PowerShell → 调 Windows 上的页面调试口

## 二、硬性规矩（违反等于白干）

1. **改任何文件前先备份**
   ```bash
   cp index.html "index.html.bak-$(date +%Y%m%d_%H%M%S)"
   ```
   没有备份不许动文件。这是硬红线。

2. **只改任务指定的文件**，不许顺手"优化"别的地方。

3. **不许自己启动浏览器 / headless 测试。**
   这台机器没有 Chrome，你跑不起来，只会空转到轮次上限然后被掐。
   （历史教训：有两次任务就是在这上面耗光 70 轮、一行代码没改。）

4. **不许用 shell 去解析二进制文件考古**（`xxd` / `dd` / `grep -ab` 挖 `.pmx` 字节偏移那种）。
   模型骨骼信息通过下面的调试口直接读，不要自己去二进制里挖。

5. 改完必须做语法检查：把 `<script type="module">` 段提取出来跑 `node --check`。

## 三、你的验证手段（别自己另建一套）

页面暴露了调试口，**你可以自己调它来自验证**——这是官方最佳实践第一条（给自己一个能验证的办法）。

```bash
# 从 WSL 侧发（注意：WSL 的 127.0.0.1 不通 Windows，要打 Windows 侧）
curl -X POST http://<Windows_HOST_IP>:18798/eval \
  -H "Content-Type: application/json" \
  -d '{"js":"<你的JS>"}'
```

- 这段 JS 在**页面模块作用域内**执行，能直接访问 `mesh`、`mesh.skeleton.bones`、以及所有内部函数
- 返回值会写进 `D:\yuxuanji\xuanji-gui\_xuanji_stdout.log` 的 `[EVAL] 结果` 行
- 页面必须已经在跑（18796 是页面，18797/18798 是调试通道）

**常用的现成接口**（不要自己重新实现）：

```js
window.__xuanji3d.getBoneAngles('thighL,kneeL,ankleL,_center')  // 读关节角度
window.__xuanji3d.playAction('sit')                              // 触发动作
window.__xuanji3d.getBoneWorld(...)                              // 读世界坐标
window.__xuanji3d.debugEval('<内联JS>')                          // 在模块作用域里跑任意 JS
```

## 四、已经查明的事实（别重复挖）

- **腿的蒙皮绑定在带 `D` 后缀的变形骨骼上**：`右足D`(404) / `左足D`(408) / `右ひざD`(405) / `左ひざD`(409) / `右足首D`(406) / `左足首D`(410) / `右足先EX`(407) / `左足先EX`(411)
  —— **不是**不带 D 的 `左足`/`左ひざ`/`左足首`。改错那几根会出现"读数是动的、画面纹丝不动"。
- MMD 的「付与」(grant) 求解器在这套代码里**从未初始化过**，所以 D 骨骼不会被自动驱动，谁要动腿就得直接驱动 D 骨骼。
- 全部骨骼 412 根；单独拧一根不动画面 ⇒ 大概率抓错了同名骨骼，不是蒙皮坏了。
- **VMD 录像播放路径已整体拆除**（2026-09-21，用户指令）。动作只走 `_BONE_ACTIONS` 里的程序化骨骼动作。

## 五、收工怎么报

- 报「改了哪几行、为什么、怎么验证的」，**不要贴大段日志**
- 语法检查结果必须贴一行（PASS/FAIL）
- 没做完就说没做完，卡在哪说清卡在哪，**不许说"应该没问题"**
