<div align="center">

# LY-NEXT

**FastAPI + LangGraph 智能体服务 · 内置 Web 工作台 · 可选 PostgreSQL / pgvector / Redis**

<br />

[![License: MIT](https://img.shields.io/badge/License-MIT-2563eb?style=plastic)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=plastic&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=plastic&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-6366f1?style=plastic)](https://github.com/langchain-ai/langgraph)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=plastic&logo=docker&logoColor=white)](./docker/README.md)

<br />

[![GitHub](https://img.shields.io/badge/GitHub-liuyingjiang--wei%2FLY--NEXT-181717?style=social&logo=github)](https://github.com/liuyingjiang-wei/LY-NEXT)
[![Gitee](https://img.shields.io/badge/Gitee-wei2335%2FLY--NEXT-C71D23?style=social&logo=gitee)](https://gitee.com/wei2335/LY-NEXT)
[![GitCode](https://img.shields.io/badge/GitCode-liuyingjiang%2Fly--next-FF6A00?style=social)](https://gitcode.com/liuyingjiang/ly-next)
[![Version](https://img.shields.io/badge/version-1.0.1--alpha-orange?style=flat)](./pyproject.toml)
[![Status](https://img.shields.io/badge/status-Alpha-yellow?style=flat)](#概览)

</div>

> **成熟度：** 打包版本 **1.0.1**，项目阶段为 **Alpha**（见 `pyproject.toml` classifiers）。适合自托管与实验，**不推荐公网裸奔**；部署前请运行 `uv run ly doctor` 并阅读 [SECURITY.md](./SECURITY.md)。

---

## 目录

- [概览](#概览)
- [特性](#特性)
- [架构](#架构)
- [快速开始](#快速开始)
- [Quick Start 三条路径](#quick-start-三条路径)
- [Web 工作台](#web-工作台)
- [NapCat / OneBot](#napcat--onebot-v11)
- [Docker](#docker)
- [安装依赖](#安装可选-redis--postgresql--pgvector)
- [配置](#配置)
- [常用接口](#常用接口)
- [文档](#文档)
- [开发](#开发)
- [常见问题](#常见问题)

---

## 概览

LY-NEXT 是一套可自托管的 Agent 运行时：HTTP / WebSocket 对话、MCP 工具暴露、多模型路由、Run 链路追踪与会话持久化，并通过 `/ly/` Web 工作台完成配置与运维。

**Alpha 说明：** 功能迭代较快，默认配置偏开发友好（如宽 CORS）。生产或公网暴露前务必完成安全体检与工作台「安全」页检查。

| 路径 | 说明 |
|------|------|
| `ly_next/` | Python 应用包 |
| `config/` | 默认配置模板（首次运行参与生成用户配置） |
| `install/` | 本机 Redis / PostgreSQL 安装脚本 |
| `data/` | 运行时数据、`config.yaml`、提示词与日志 |
| `www/` | Web 首页、工作台与登录页 |

---

## 特性

| 能力 | 说明 |
|------|------|
| **Agent 模式** | ReAct · Plan-then-Act · Coordinator · Chat |
| **LLM** | OpenAI / Anthropic / Ollama / OpenAI 兼容网关 |
| **MCP** | 内置 MCP Server；可选远端 MCP（`langchain-mcp-adapters`） |
| **存储** | 可选 PostgreSQL + pgvector、Redis |
| **Web** | `/` 首页 · `/ly/` 工作台 · `/ly/login` 登录 |
| **桥接** | NapCat 反向 OneBot v11 WebSocket |

---

## 架构

```mermaid
flowchart LR
  subgraph client["Client"]
    WB[Web 工作台]
    API[HTTP / WS 客户端]
    QQ[NapCat]
  end

  subgraph core["LY-NEXT"]
    FA[FastAPI]
    AG[Agent 层]
    TL[Tools / MCP]
  end

  subgraph optional["Optional"]
    PG[(PostgreSQL)]
    RD[(Redis)]
  end

  WB --> FA
  API --> FA
  QQ --> FA
  FA --> AG
  AG --> TL
  FA --> PG
  FA --> RD
```

---

## 快速开始

```bash
git clone https://github.com/liuyingjiang-wei/LY-NEXT.git
cd LY-NEXT
uv sync
uv run ly
```

浏览器访问：

| 地址 | 说明 |
|------|------|
| `http://127.0.0.1:8000/` | 首页 |
| `http://127.0.0.1:8000/ly/` | 工作台（需登录） |
| `http://127.0.0.1:8000/docs` | OpenAPI 文档 |

> `uv sync` 默认安装 **dev** 依赖（pytest、ruff 等）。最小镜像可用 `uv sync --no-default-groups`。

**环境要求：** Python ≥ 3.10（推荐 3.11/3.12）· [uv](https://docs.astral.sh/uv/) 包管理

```bash
uv run ly --reload
uv run ly                          # TTY 下交互选择端口
uv run ly --port 9000              # 指定端口
uv run ly --no-prompt              # 使用 config / 环境变量，不询问
LY_NEXT_PORT=9000 uv run ly --no-prompt
uv run ly --host 127.0.0.1 --port 8000   # 仅本机
uv run ly doctor                          # 环境诊断（LLM/PG/Redis/安全）
```

### Quick Start 三条路径

详细分步说明见 **[docs/QUICKSTART.md](./docs/QUICKSTART.md)**（每路径 ≤5 步）：

| 路径 | 适合 | 要点 |
|------|------|------|
| **① 只聊天** | Ollama / 兼容网关试玩 | 可不装 PG；工作台填模型密钥 → `ly doctor` → 对话 |
| **② 完整栈** | 持久化 + RAG + Run | Docker/install 启 PG+Redis → RAG 试检索 → 对话同步 |
| **③ QQ 桥接** | NapCat 自动回复 | 配 LLM → NapCat WS 客户端 → 诊断页验连接 |

---

## Web 工作台

内置 Web 控制台，用于配置模型、管理会话、调试 API、查看 Run 追踪与 NapCat 状态，无需单独部署前端服务。

| 路径 | 说明 |
|------|------|
| `/` | 产品首页 |
| `/ly/` | 工作台（需登录） |
| `/ly/login` | 登录页；提交 `api_key` 后写入 Cookie |
| `/ly/static/*` | 样式、脚本与图片等静态资源 |

**鉴权：** 默认开启。请求需携带 `X-API-Key` 请求头，或通过 `/ly/login` 登录后使用 Cookie。密钥对应 `auth.api_key`，与 LLM 提供商密钥无关。首次启动会写入 `data/ly_next/FIRST_RUN.txt`；控制台默认**脱敏**显示密钥。

**就绪检测：** 工作台顶部横幅与首次引导会调用 `GET /api/system/readiness`，检查 LLM 密钥、PostgreSQL、Redis 并提示降级影响。

**对话持久化：** 启用 PostgreSQL 后，工作台「智能对话」在**同步：开**模式下会为会话创建 `thread_id` 并写入服务端；可导出/导入 JSON 备份本地 trace 与用量。配置保存会返回 `settings_effects`（热更新 / 需重启 / 注意事项）。

**场景预设与调试：** 「应用配置」提供 Agent 场景预设（日常聊天 / 工具助手 / QQ 轻量 / 多任务协调）；「模型配置」可试算路由 `POST /api/system/router/preview`；「RAG 配置」可试检索 `POST /api/system/rag/try`；「QQ / NapCat」页提供连接诊断 `GET /api/onebot11/diagnostics`。

**可观测与安全：** 「Run 历史」在开启 `agent.observability.store_prompts` 后可查看 LLM 请求全文；「安全」页提供 `GET /api/system/security/health` 体检；智能对话气泡内展示工具调用时间线。

**配置：** 工作台 **「应用配置」** / **「模型配置」** 通过 `GET/PATCH /api/system/settings` 读写 `data/ly_next/config.yaml`。扩展与插件状态见 `GET /api/system/extensions`。

---

## NapCat / OneBot v11

<details>
<summary><strong>展开：连接配置与排错</strong></summary>

NapCat 使用 **反向 WebSocket（客户端）**。在 NapCat WebUI → **网络配置** → 新建 **WebSocket 客户端**：

| 项 | 值 |
|----|-----|
| URL | `ws://127.0.0.1:8000/OneBotv11`（端口与 `server.port` 一致） |
| Token | 与 `bridge.onebot11.access_token` 一致；**两边都留空则都留空** |

兼容路径：`ws://127.0.0.1:8000/onebot/v11/ws`。

上述路径**不经过**工作台 `X-API-Key`；仅当配置了 `access_token` 时才校验 Bearer / `?access_token=`。

**403 Forbidden 排查：**

1. **完全退出**旧进程后重新启动（改代码后必须重启 uvicorn）
2. 启动日志应出现 `[onebot11] NapCat connected`
3. 确认 NapCat 为 **WebSocket 客户端**，URL 无多余斜杠

`bridge.onebot11.enabled` 须为 `true`（`data/ly_next/config.yaml` 或工作台 **QQ / NapCat** 页）。

**自动回复范围**（`bridge.onebot11.triggers`）：默认仅私聊与群聊 @ 本号。会话键 `onebot:private:{qq}` / `onebot:group:{群号}` 映射到数据库 thread。

</details>

---

## Docker

详见 [docker/README.md](./docker/README.md)。

```bash
# 仅 Redis + PostgreSQL
docker compose -f docker/docker-compose.yml up -d

# 一键 Demo（依赖 + 应用）
bash docker/demo-up.sh
# Windows: powershell -ExecutionPolicy Bypass -File docker/demo-up.ps1

# 或手动构建并运行应用
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

容器内诊断：`docker exec ly-next-app ly doctor`

---

## 安装（可选：Redis / PostgreSQL / pgvector）

```bash
# Linux / macOS
bash install.sh

# Windows
powershell -ExecutionPolicy Bypass -File ".\install.ps1"
```

详细说明见 [install/README.md](./install/README.md)。

---

## 配置

首次启动创建 **`data/ly_next/config.yaml`**（模板合并 + 自动补齐 `prompts/`、`knowledge/`；不覆盖已有文件）。

| 环境变量 | 用途 |
|----------|------|
| `LY_NEXT_CONFIG_DIR` | 用户配置目录（可写） |
| `LY_NEXT_PROJECT_ROOT` | 项目根 |
| `LY_NEXT_PORT` | 启动监听端口（配合 `--no-prompt`） |
| `DATABASE_HOST` / `REDIS_HOST` | 容器或远程主机名 |

常用项：`openai_llm.api_key`、`llm.default_provider`、`database.*`、`redis.*`、`auth.*`

<details>
<summary><strong>展开：识图预描述 + 多模型路由</strong></summary>

若多模态模型仅适合「看图说明」，主对话想用更强纯文本模型：

1. 开启 `agent.vision_precaption.enabled`
2. 配置 `provider` / `model`（或留空以使用 `model_router.routes.vision`）
3. 仅对**最后一条**含图消息做预描述，主模型不再收到图片块

预描述在路由**之前**执行，主轮不含图时不会命中 `routes.vision`。共用路由视觉模型：设 `agent.vision_precaption.use_router_vision_model: true` 且 `vision_precaption.model` 留空。

</details>

---

## 常用接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/runs`、`/api/runs/{id}/events` | Run 追踪 |
| POST | `/api/threads` | 会话（需 PostgreSQL） |
| POST | `/api/chat` | 对话（可选 `thread_id`） |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tools` | 工具列表 |
| GET/POST | `/mcp` | MCP 协议 |

完整列表见 `/docs` 或工作台 **API 调试** 页。

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/QUICKSTART.md](./docs/QUICKSTART.md) | 三条上手路径（聊天 / 完整栈 / QQ） |
| [TECHNICAL.md](./TECHNICAL.md) | 代码阅读路径与请求链路 |
| [SECURITY.md](./SECURITY.md) | 威胁模型与安全检查项 |
| [AGENTS.md](./AGENTS.md) | 智能体协作约定 |
| [install/README.md](./install/README.md) | 依赖安装 |
| [docker/README.md](./docker/README.md) | 容器部署 |

---

## 开发

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest -q
```

**启动与端口**

```bash
uv run ly                    # 交互选择端口
uv run ly --port 9000        # 指定端口
uv run ly --reload           # 热重载（开发）
uv run ly --no-prompt        # 使用配置或 LY_NEXT_PORT，不询问
uv run ly --show-full-api-key  # 启动快照中显示完整 API 密钥（默认脱敏）
uv run ly doctor             # 依赖与安全诊断（退出码 1 表示存在阻塞项）
uv run ly doctor --json      # JSON 报告，便于复制
```

**修改 Web 工作台 UI**（需 [Node.js](https://nodejs.org/) 与 pnpm）：

```bash
pnpm install
pnpm run dev:workbench       # 本地预览
pnpm run build:workbench     # 构建到 www/
```

构建完成后重启 `uv run ly` 即可在浏览器看到更新。

---

## 常见问题

<details>
<summary><strong>未生成用户配置</strong></summary>

检查 `data/` 或 `LY_NEXT_CONFIG_DIR` 目录是否可写。

</details>

<details>
<summary><strong>NapCat 连接 403</strong></summary>

见上文 [NapCat 排错](#napcat--onebot-v11)，确保进程已重启且路由已挂载。

</details>

---

<div align="center">

**MIT License** · [LICENSE](./LICENSE)

</div>
