# 玄机 3D 动作控制链 · 进度
## 2026-09-20 第三轮
- 23:17 已确认(复用上轮结论)：headless 下 playAction 真动(上臂Z偏离1.185rad PASS)、中途 stopAction 真停(0.000 PASS)；C项(自然播完自动回待机)卡死 watchdog90s EXIT=9。
- 23:21 diag_stack.js 抓栈：wave 播完 9s 后 1+1=2 正常返回，Debugger.pause 抓到的是正常渲染帧(animate→WebGLRenderer.render，index.html:933)，**不是 JS 死循环**。推翻“页面卡死”假设 → 之前 vcc C 项 12s×6 超时是 SwiftShader 软件渲染下渲染进程瞬时 stall，属测量假象。
- 23:22 改 index.html（已备份 index.html.bak-20260920_231559）：①stopAction/playAction 加 _actionEpoch 纪元守卫，喊停后 in-flight 的 loadAnimation 回调作废（防“停之后舞又起”）；②一次性动作设 LoopOnce 后注册 mixer 'finished' → 自动 stopAction 回待机（补上缺失的“播完自动回待机”）；③暴露 getState()/__xjDiag_mmdReady/__xjDiag_lastResult 供 Python 回读；④VMD 加载失败也回待机，不再把 _playingVmd 卡 true。模块语法 node --check 通过。
