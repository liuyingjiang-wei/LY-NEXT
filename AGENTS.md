# AGENTS.md

本文件给编码智能体在 **LY-NEXT** 仓库中工作的统一约定。

## 仓库级规则与记录

- `rules/`：仓库级规则块（回复结构、质量门槛、安全边界）
- `MEMORY.md`：长期记忆（提炼后的要点与经验）
- `TOOLS.md`：本机工具与常用操作（避免记录明文密钥）

## 工作方式

- **先理解再改**：先定位入口/调用链/配置来源，再做最小变更。
- **保持聚焦**：一条任务只做一类事情（文档、忽略文件、修复、重构等），避免顺手大改。
- **小步提交质量**：优先选择低风险的局部重构（删除死代码/冗余注释/重复逻辑、统一异常处理、简化控制流）。
- **不破坏行为**：重构以“行为等价”为原则；若必须改变行为，明确写在变更说明里并给出验证方式。

## 关键规则

- **配置优先**：运行参数优先来自 `data/ly_next/config.yaml`（或 `LY_NEXT_CONFIG_DIR` 指向目录）；代码里避免硬编码环境差异。
- **鉴权保持一致**：API Key 鉴权逻辑集中在 `ly_next/main.py` 的中间件与 `/ly/login` 流程，新增接口时不要绕开既有鉴权约定。
- **工具与 MCP**：工具的对外形态以 `ly_next/tools/` 注册与 MCP 适配为准；新增工具要同时考虑 LLM 调用与 MCP 暴露的一致性。
- **可选依赖可降级**：Redis/DB/pgvector 不可用时尽量提供降级路径与可读错误信息。

## 修改前的定位建议

- HTTP/WS 对话入口：`ly_next/api/wei_api.py`、`ly_next/api/ws_api.py`
- Agent 选择与 deps：`ly_next/agent/factory.py`、`ly_next/agent/deps.py`
- OpenAI 兼容请求与流式：`ly_next/models/openai_compat.py`
- RAG：`ly_next/rag/document_retriever.py`、`ly_next/rag/example_selector.py`

## 质量门槛（改完必须过）

```bash
uv run ruff format .
uv run ruff check .
```

如仓库包含测试用例，再运行：

```bash
uv run pytest -q
```
