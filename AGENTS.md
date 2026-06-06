<div align="center">

# AGENTS.md

**编码智能体在 LY-NEXT 仓库中的统一约定**

[![Docs](https://img.shields.io/badge/Docs-Agent_Guide-6366f1?style=for-the-badge)](./AGENTS.md)
[![Security](https://img.shields.io/badge/Security-SECURITY.md-2563eb?style=flat-square)](./SECURITY.md)

[← 返回 README](./README.md)

</div>

---

## 目录

- [仓库级规则与记录](#仓库级规则与记录)
- [工作方式](#工作方式)
- [关键规则](#关键规则)
- [修改前定位](#修改前的定位建议)
- [质量门槛](#质量门槛改完必须过)

---

## 仓库级规则与记录

| 路径 | 用途 |
|------|------|
| [`rules/`](./rules/README.md) | 仓库级规则块（`ly-next-project.mdc`、`response-safety.mdc`、`api-trust-and-tools.mdc`） |
| [`SECURITY.md`](./SECURITY.md) | 威胁模型、动态 API 加载策略、生产检查项与漏洞报告 |
| [`MEMORY.md`](./MEMORY.md) | 长期记忆（提炼后的要点与经验） |
| [`TOOLS.md`](./TOOLS.md) | 本机工具与常用操作（**勿**记录明文密钥） |
| [`docker/`](./docker/README.md) | Compose、`Dockerfile`、pgvector 叠加与部署说明 |

> **前端源码不入库**：`.workbench-src/` 在 `.gitignore` 中；静态页以 `www/` 为准。策略见 [README — 版本控制与工作台前端](./README.md#版本控制与工作台前端)。

---

## 工作方式

| 原则 | 说明 |
|------|------|
| **先理解再改** | 先定位入口 / 调用链 / 配置来源，再做最小变更 |
| **保持聚焦** | 一条任务只做一类事（文档、修复、重构等），避免顺手大改 |
| **小步提交质量** | 优先低风险局部重构：删死代码、统一异常处理、简化控制流 |
| **不破坏行为** | 重构以行为等价为原则；若必须改变行为，写清验证方式 |

---

## 关键规则

- **配置优先**：运行参数来自 `data/ly_next/config.yaml`（或 `LY_NEXT_CONFIG_DIR`）；避免硬编码环境差异
- **鉴权一致**：API Key 逻辑在 `ly_next/main.py` 中间件与 `/ly/login`；新接口勿绕开既有约定
- **工具与 MCP**：对外形态以 `ly_next/tools/` 注册与 MCP 适配为准；新增工具需兼顾 LLM 与 MCP
- **可选依赖可降级**：Redis / DB / pgvector 不可用时提供降级路径与可读错误

---

## 修改前的定位建议

| 关注点 | 路径 |
|--------|------|
| 内置 HTTP 路由 | `ly_next/api/`（`ly_api.py`、`ws_api.py`、`runs_api.py`、`threads_api.py` 等） |
| 工作台静态页 | `www/home.html`、`www/app.html`、`www/login.html`；轨道图 `www/orbit/`（源 `.workbench-src/public/orbit/`） |
| 会话持久化 | `ly_next/core/thread_persistence.py`（`sessions` / `messages`）；checkpoint：`checkpointer.py` |
| 插件 API 目录 | `ly_next/apis/` · `APILoader` · 模块名 `ly_next_plugin_<stem>` → [apis/README.md](./ly_next/apis/README.md) |
| 对话入口 | `ly_api.py`、`ws_api.py`；提示词：`prompt_templates.py`（`data/ly_next/prompts/` 优先于 `prompt_builtin/`） |
| Agent 图 | `react.py`、`plan.py`；`json_extract.py`、`tool_streak.py`（勿再引入已删的 prebuilt 包装层） |
| 选择与依赖 | `factory.py`、`deps.py` |
| OpenAI 兼容 | `models/openai_compat.py` |
| RAG / 记忆 | `rag/document_retriever.py`、`example_selector.py`；`tools/memory_note.py`（`remember_fact`） |

**标识符**：`thread_id`（跨轮会话）≠ `task_id` / `run_id`（单次请求）

---

## 质量门槛（改完必须过）

```bash
uv run ruff format .
uv run ruff check .
```

如仓库包含测试用例：

```bash
uv run pytest -q
```
