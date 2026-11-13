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

仓库**不含**任何 3D / Live2D 模型和动作文件——那些素材有各自的作者与二次配布条款，不便随代码分发。

自己准备：

```
3d_viewer/models/你的模型.pmx
3d_viewer/actions/动作.vmd
live2d_viewer/models/...
```

代码里默认的模型文件名在 `3d_viewer/index.html` 与 `window.py` 中，改成你自己的文件名即可。

## 已知限制

- 只在 Windows 上验证过（依赖 Win32 API、Windows 语音设备）
- 8G 显存级别显卡可跑，但同时跑图像生成会抢显存
- 语音部分依赖第三方云服务，需要联网

## 许可

MIT，见 [LICENSE](LICENSE)。

## 免责

仅供学习与个人使用。使用第三方模型、动作素材、云服务时请遵守各自条款；生成内容请遵守所在地法律法规。
