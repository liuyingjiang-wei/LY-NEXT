# CLAUDE.md

本仓库为 **LY-NEXT**：一个基于 FastAPI + LangGraph 的 Agent 服务，包含可选的 PostgreSQL/pgvector 与 Redis，并提供 Web 工作台（静态资源由 `www/` 提供）。

## 目标与边界

- 保持改动 **小而聚焦**，避免把不相关的重构混入功能/修复。
- 优先沿用现有架构与命名；只有在带来明确收益（可读性/一致性/可维护性/可测试性）时才调整。
- 任何影响行为的改动，都需要同步更新文档/配置说明，并尽量提供可复现的验证步骤。

## 项目结构速览

- `ly_next/main.py`：FastAPI 应用创建、生命周期、路由挂载、工作台静态资源挂载与鉴权中间件
- `ly_next/api/`：HTTP/WS/MCP 等接口
- `ly_next/agent/`：Agent 图与模式（react/plan/chat）、依赖注入与运行参数
- `ly_next/models/`：LLM provider 适配（OpenAI/Anthropic/Ollama/OpenAI 兼容）
- `ly_next/tools/`：工具注册、调用与 MCP 适配
- `ly_next/rag/`：示例检索/文档检索/embedding/相似度
- `ly_next/core/`：配置、日志、服务管理、DB/Redis、任务等基础设施

## 常用命令（优先使用）

```bash
# Python 依赖
uv sync
uv sync --extra dev

# 启动
uv run ly
uv run ly --reload

# 代码质量（Python）
uv run ruff format .
uv run ruff check .
uv run mypy ly_next


## 代码风格与约定

- Python 代码以 `ruff` 为准：优先修复可自动修复项；避免裸 `except:`；在 `except` 内二次抛出时保留异常链（`raise ... from e`）。
- 避免“解释代码在做什么”的注释；保留注释只用于说明 **意图、约束、边界条件、兼容性原因**。
- 资源/依赖是可选的：服务在数据库/Redis 不可用时应尽量降级运行并给出清晰日志。

## 变更验收

- 文档变更：确保示例命令可在仓库根目录直接执行（不要写死本机绝对路径）。
- Python 变更：至少通过 `uv run ruff check .`；如改动影响核心行为，尽量补充最小可验证步骤（或测试用例）。
