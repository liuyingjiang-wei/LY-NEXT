<div align="center">

# CLAUDE.md

**Claude Code 在 LY-NEXT 仓库中的协作说明**

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=plastic&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-6366f1?style=plastic)](https://github.com/langchain-ai/langgraph)

[← 返回 README](./README.md) · [AGENTS.md](./AGENTS.md)

</div>

---

本仓库为 **LY-NEXT**：基于 FastAPI + LangGraph 的 Agent 服务，可选 PostgreSQL / pgvector / Redis，并内置 Web 工作台（`/` · `/ly/`）。

---

## 目标与边界

| 原则 | 说明 |
|------|------|
| 小而聚焦 | 避免把不相关重构混入功能 / 修复 |
| 沿用现有架构 | 仅在可读性 / 一致性 / 可维护性 / 可测试性有明确收益时调整 |
| 行为变更要可验证 | 同步更新文档 / 配置说明，提供复现步骤 |

---

## 项目结构速览

| 路径 | 职责 |
|------|------|
| `ly_next/main.py` | FastAPI 应用、生命周期、路由、工作台静态资源、鉴权中间件 |
| `www/` | Web 首页、工作台、登录页与静态资源 |
| `ly_next/api/` | HTTP / WS / MCP 等接口 |
| `ly_next/agent/` | Agent 图与模式（react / plan / chat）、依赖注入 |
| `ly_next/models/` | LLM provider 适配 |
| `ly_next/tools/` | 工具注册、调用与 MCP 适配 |
| `ly_next/rag/` | 示例检索、文档检索、embedding |
| `ly_next/core/` | 配置、日志、DB / Redis、任务等基础设施 |

---

## 常用命令

```bash
# Python 依赖
uv sync
uv sync --extra dev

# 启动
uv run ly
uv run ly --reload
uv run ly --port 9000

# Web 工作台 UI（需 pnpm）
pnpm run build:workbench

# 代码质量
uv run ruff format .
uv run ruff check .
uv run mypy ly_next
```

---

## 代码风格与约定

- Python 以 **`ruff`** 为准；避免裸 `except:`；二次抛出保留链（`raise ... from e`）
- 注释说明**意图、约束、边界、兼容性**，而非复述代码
- Redis / DB 不可用时尽量**降级运行**并输出清晰日志

---

## 变更验收

- **文档**：示例命令可在仓库根目录直接执行（勿写死本机绝对路径）
- **Python**：至少通过 `uv run ruff check .`；核心行为变更补充最小验证步骤或测试
