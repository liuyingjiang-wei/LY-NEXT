# LY-NEXT

基于 FastAPI 与 LangGraph 的 Agent 服务，内置 Web 工作台，支持 PostgreSQL/pgvector 与 Redis。

## 文档入口

- [技术说明](TECHNICAL.md)
- [安装脚本说明](install/README.md)

## 特性

- **多种 Agent 模式**：ReAct / Plan-then-Act / Chat
- **多 LLM Provider**：OpenAI / Anthropic / Ollama / OpenAI 兼容网关
- **MCP**：作为 MCP Server 暴露工具与资源
- **可选外部依赖**：PostgreSQL + pgvector、Redis
- **Web 工作台**：`/ly/`（由 `www/` 静态资源提供）
- **登录页**：`/ly/login`（与控制台同源，构建进 `www/`）

## 快速开始

```bash
uv sync
uv run ly
```

## 环境要求

- **Python**：>= 3.10（推荐 3.11/3.12）
- **包管理**：建议使用 `uv`（见上）
- **前端工作台构建**（可选）：`pnpm`（用于构建 `www/` 下的控制台与登录页）

## 常用命令

```bash
# 开发：热重载（也可通过 config.yaml 设置 server.reload）
uv run ly --reload
```

```bash
# 启动并指定 host/port
uv run ly --host 127.0.0.1 --port 8000
```

## 构建/开发 Web 工作台（可选）

工作台源码在 `.workbench-src/`，构建产物输出到 `www/`，后端通过 `/ly/` 与 `/ly/static/*` 提供静态资源。

```bash
pnpm install
pnpm run build:workbench
```

```bash
# 本地开发预览（Vite）
pnpm run dev:workbench
```

## 安装（可选：Redis / PostgreSQL / pgvector）

脚本位于 `install/`，支持自动检测系统。

```bash
# Linux/macOS
bash install/install-auto.sh
```

```powershell
# Windows（建议管理员终端）
powershell -ExecutionPolicy Bypass -File ".\install\install-auto.ps1"
```

pgvector 安装（按系统/发行版）见 `install/pgvector.md`，Windows 脚本为 `install/pgvector-windows.ps1`。

## 配置

首次启动会自动创建 **`data/ly_next/config.yaml`**（若不存在则从仓库 `config/default_config.yaml` 或包内 `ly_next/default_config.yaml` 复制，再与内置缺省合并）。若安装到只读环境或找不到项目根，可设置：

- **`LY_NEXT_CONFIG_DIR`**：用户配置目录（其下生成 `config.yaml`），需可写。
- **`LY_NEXT_PROJECT_ROOT`**：项目根目录，用于定位默认模板与 `data/`（与 `LY_NEXT_CONFIG_DIR` 可同时使用）。

编辑 `data/ly_next/config.yaml`（或上述目录中的 `config.yaml`），常用项：

- **LLM**：`openai_llm.api_key` / `llm.default_provider`
- **数据库**：`database.*`（Ubuntu 等环境下 TCP 需要密码时，请填写 `database.password` 或设置 `POSTGRES_PASSWORD`；密码为空时会按 `database.try_unix_socket` 尝试本机 Unix socket）
- **Redis**：`redis.*`
- **认证**：`auth.*`
- **托管外部服务**：`services.stop_managed_on_exit`（默认 `true`）— 仅在开发模式且由本进程自动启动了本机 Redis / PostgreSQL 时，在关闭 LY-NEXT 时尝试一并停止它们，减轻后台占用；若 Redis/PG 为你手动或系统服务启动的，不会被停止。

## Web 工作台与认证

| 路径 | 说明 |
|------|------|
| `/ly/` | 控制台，对应 `www/index.html` |
| `/ly/login` | React 登录页，`www/login.html`；`POST /ly/login` 提交 `api_key`，成功写入 Cookie 并跳转 `/ly/` |
| `/ly/static/*` | 构建后的 JS/CSS 等资源（`base` 为 `/ly/static/`） |

- **认证**：默认启用 API Key（请求头 `X-API-Key`，或通过 `/ly/login` 写入的 Cookie）
- **未构建登录页**：若缺少 `www/login.html`，访问 `/ly/login` 将返回 503 
- **工作台「配置」**：读写 `GET/PATCH /api/system/settings`（仅允许 `llm`、`openai_llm`、`anthropic_llm`、`ollama_llm`、`openai_compat_llm`、`agent` 段落；密钥读取为 `***`，未改动请勿填写）
- **自检接口**：`GET /api/system/extensions`（数据库扩展与 Redis 状态）


- **OpenAI 兼容统一配置**：MiMo 等第三方网关统一通过 openai_compat_llm 配置（不再单独维护 mimo_llm）
- **工作台 UI**：主界面与登录页已统一为液态玻璃风格（LiquidGlass）

## 常用接口

- `GET /api/health`
- `POST /api/chat`
- `GET /api/tasks`
- `GET /api/tools`
- `GET /api/system/extensions`
- `GET/POST /mcp`

## 常见问题

- **访问 `/ly/login` 返回 503**：说明缺少 `www/login.html`，请在项目根执行 `pnpm run build:workbench` 生成工作台页面。
- **首次启动没有生成配置**：检查 `LY_NEXT_CONFIG_DIR` 指向目录是否可写；或删除 `data/ly_next/config.yaml` 后重启让其重新生成。
