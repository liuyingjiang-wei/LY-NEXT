# LY-NEXT

基于 FastAPI 与 LangGraph 的 Agent 服务，内置 Web 工作台，可选安装 PostgreSQL/pgvector 与 Redis。

## 仓库布局

| 路径 | 说明 |
|------|------|
| `ly_next/` | Python 应用包 |
| `config/` | 默认配置模板（首次运行会参与生成用户配置） |
| `www/` | 工作台与登录页的**构建产物**（HTML/JS/CSS），供 `/ly/` 挂载 |
| `docker/` | Compose、Dockerfile、pgvector 叠加配置 |
| `install/` | 本机数据库安装脚本 |
| `data/` | 运行时数据与用户 `config.yaml`（默认已 `.gitignore`） |


## 文档入口

- [技术说明](TECHNICAL.md)
- [安装脚本说明](install/README.md)
- [智能体协作约定](AGENTS.md)
- [Docker 说明](docker/README.md)

## 特性

- **多种 Agent 模式**：ReAct / Plan-then-Act / Chat
- **多 LLM Provider**：OpenAI / Anthropic / Ollama / OpenAI 兼容网关
- **MCP**：作为 MCP Server 暴露工具；可选 `langchain-mcp-adapters` 接入远端 MCP
- **可选外部依赖**：PostgreSQL + pgvector、Redis
- **Web 工作台**：`/ly/` 液态玻璃风格控制台；登录页 `/ly/login`

## 快速开始

```bash
uv sync
uv run ly
```


## Docker

见 [docker/README.md](docker/README.md)。

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

## 环境要求

- **Python**：>= 3.10（推荐 3.11/3.12）
- **包管理**：`uv`

## 常用命令

```bash
uv run ly --reload
uv run ly --host 127.0.0.1 --port 8000
```

## 安装（可选：Redis / PostgreSQL / pgvector）

```bash
bash install/install-auto.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File ".\install\install-auto.ps1"
```

pgvector 说明见 [install/pgvector.md](install/pgvector.md)；Windows 脚本：`install/pgvector-windows.ps1`。

## 配置

首次启动会创建 **`data/ly_next/config.yaml`**（由仓库默认模板与包内缺省合并）。可选环境变量：

- **`LY_NEXT_CONFIG_DIR`**：用户配置目录（可写）
- **`LY_NEXT_PROJECT_ROOT`**：项目根（模板、`data/` 等）
- **`DATABASE_HOST`** / **`REDIS_HOST`**：容器或远程服务主机名（默认配置支持 `${DATABASE_HOST:-localhost}` 等形式，见 `ly_next/core/config.py`）

常用配置项：`openai_llm.api_key`、`llm.default_provider`、`database.*`、`redis.*`、`auth.*`。开发模式下若由本进程自动启动了本机 Redis/PostgreSQL，退出时可按 `services.stop_managed_on_exit` 尝试停止（系统服务或手动启动的不受影响）。

**识图 + 强文本模型**：若多模态模型只适合做「看图说明」，主对话想用更强的纯文本模型，可开启 `agent.vision_precaption.enabled`，并配置 `provider` / `model`（或留空 `model` 以使用 `model_router.routes.vision` 的模型）。流程为：仅对**最后一条**含图用户消息调用识图模型生成描述，拼进正文后**再**做模型路由与对话，主模型不再收到图片块（OpenAI 兼容 `image_url` 格式）。

与 **多模型路由**：预描述在路由**之前**执行，主轮**不再含图**，因此不会命中 `routes.vision`。「视觉」行只服务**未开预描述**时的含图主对话。若希望识图调用与路由里「视觉」行共用同一 `provider/model`，在配置里设 `agent.vision_precaption.use_router_vision_model: true` 且 `vision_precaption.model` 留空、并填好多路由的 `vision` 行。合并正文会做清洗与 `max_caption_chars` / `max_merged_chars` 上限。

## Web 工作台与认证

| 路径 | 说明 |
|------|------|
| `/ly/` | 控制台（`www/index.html`） |
| `/ly/login` | 登录页；`POST /ly/login` 提交 `api_key`，写入 Cookie 后跳转 `/ly/` |
| `/ly/static/*` | 静态资源，`base` 为 `/ly/static/` |

默认启用 API Key（请求头 `X-API-Key` 或登录 Cookie）。工作台「配置」通过 `GET/PATCH /api/system/settings`（可编辑段落以接口为准；密钥只显示 `***`）。自检：`GET /api/system/extensions`。

## 常用接口

- `GET /api/health`
- `POST /api/chat`
- `GET /api/tasks`
- `GET /api/tools`
- `GET /api/system/extensions`
- `GET/POST /mcp`

## 常见问题
- **未生成用户配置**：检查 `data/` 或 `LY_NEXT_CONFIG_DIR` 是否可写。
