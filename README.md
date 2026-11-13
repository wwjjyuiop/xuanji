# 玄机 GUI（Xuanji）

一个跑在 Windows 上的 **3D 数字人智能体桌面客户端**：PySide6 主界面 + three.js/MMD 实时 3D 角色 + 语音输入输出 + 大模型工具调用。不是聊天壳子，是一个能动手干活的本地智能体前端。

## 特性

- **3D 数字人**：MMD 模型实时渲染（three.js + ammo.js 物理），支持表情、动作、口型驱动
- **语音交互**：语音识别（百度 / 千问）→ 大模型 → 语音合成（CosyVoice 等），可打断
- **工具调用**：文件读写、目录浏览、命令执行、代码生成与自检、子代理并行、定时任务
- **长期记忆**：人格设定、用户画像、对话记忆，落盘可查可改
- **模型可切**：云端 DeepSeek / 云端千问（视觉）/ 本地 Ollama，在设置里切换即时生效
- **自我维护**：心跳守护（核心文件损坏自动恢复）、代码重构规划、评审

## 界面结构

```
主窗口（window.py）
├── 左：3D 数字人视口（QWebEngineView → 3d_viewer/index.html）
├── 右：对话流 + 输入框 + 动作/技能面板
└── 底部：运行日志
```

## 快速开始

```bash
# 1. 依赖（Python 3.10+）
pip install PySide6 numpy pillow requests websocket-client

# 2. 配置密钥
cp .env.example .env
# 编辑 .env，填入自己的 Key

# 3. 准备 3D 模型（仓库不含模型，见下）
#    把 .pmx 模型放到 3d_viewer/models/
#    把动作 .vmd 放到 3d_viewer/actions/

# 4. 启动
python main.py
```

Windows 下想无黑窗口启动：用 `pythonw.exe main.py`。

## 配置说明（.env）

| 键 | 用途 | 必填 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 主推理（文本） | 是（除非用本地模型） |
| `QWEN_API_KEY` | 视觉理解 / 备选推理 | 否 |
| `QWEN_BASE_URL` | 千问兼容端点 | 否 |
| `USE_LOCAL_MODEL` | `1` = 主推理走本地 Ollama | 否 |
| `BAIDU_APP_ID` / `BAIDU_API_KEY` / `BAIDU_SECRET_KEY` | 语音识别 | 否 |
| `QQ_APP_ID` / `QQ_CLIENT_SECRET` | QQ 机器人通道 | 否 |

本地模型：装 [Ollama](https://ollama.com/)，`ollama pull qwen3:8b`，然后 `USE_LOCAL_MODEL=1`。端点默认 `http://127.0.0.1:11434/v1`，可在 `connector.py` 里改。

## 代码地图

| 文件 | 职责 |
|---|---|
| `main.py` | 入口 |
| `window.py` | 主窗口、对话流、3D 视口桥接 |
| `connector.py` | 大模型调用、工具调度、降级链 |
| `memory_service.py` | 人格 / 画像 / 记忆读写 |
| `voice_input.py` / `voice_output.py` | 语音识别 / 合成 |
| `3d_viewer/index.html` | three.js MMD 渲染器（表情、动作、口型） |
| `settings_window.py` | 设置：人格、画像、记忆、API Key、推理后端 |
| `agent_runner.py` / `subagent_engine.py` | 任务执行与子代理 |
| `coding_skill.py` | 代码生成 + 静态自检 + 运行报错回修 |
| `heart_guard.py` | 核心文件心跳校验与自动恢复 |
| `cron_engine.py` | 定时任务 |
| `skills/` | 可扩展技能目录 |

## 模型与素材

仓库**自带一个占位模型**（`3d_viewer/models/placeholder.glb`，RobotExpressive，CC0 公有领域），
clone 下来直接就能看到 3D 角色，不用先找模型。

想换成自己的角色：

```
方法一：把模型放到 3d_viewer/models/model.pmx       （默认就找这个）
方法二：访问时指定 ?model=你的模型.pmx              （记在浏览器里，下次自动用）
```

加载失败或找不到文件时，界面顶部会给出提示，并自动回退到占位模型，不会白屏。

### 为什么仓库不直接带 MMD 模型

MMD 模型（`.pmx`）绝大多数标注「二次配布禁止」——作者只允许自己用，不允许再分发。
把别人的模型放进公开仓库等于替你侵权，所以这里只放**许可明确允许再分发**的素材。

### 去哪找可用的模型

- **VRoid Studio**：捏一个自己的角色，导出 VRM 后再转 PMX
- **模之屋 / Aplaybox 等平台**：筛选「允许二次配布」或 CC 协议的作品，遵守作者条款
- **CC0 素材库**：公有领域角色模型，随便用

商用前务必逐个核对模型作者的授权条款。

## 已知限制

- 只在 Windows 上验证过（依赖 Win32 API、Windows 语音设备）
- 8G 显存级别显卡可跑，但同时跑图像生成会抢显存
- 语音部分依赖第三方云服务，需要联网

## 许可

MIT，见 [LICENSE](LICENSE)。

## 免责

仅供学习与个人使用。使用第三方模型、动作素材、云服务时请遵守各自条款；生成内容请遵守所在地法律法规。
