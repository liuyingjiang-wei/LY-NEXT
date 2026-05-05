# AGENTS.md

本文件给编码智能体在 **LY-NEXT** 仓库中工作的统一约定。

## 仓库级规则与记录

- `rules/`：仓库级规则块（回复结构、质量门槛、安全边界）
- `MEMORY.md`：长期记忆（提炼后的要点与经验）
- `TOOLS.md`：本机工具与常用操作（避免记录明文密钥）

## 会话启动（顺序）

每次会话开始，按顺序快速浏览（只读，目的是拿到上下文与约束）：

1. `rules/`（尤其是 `rules/ly-next-project.mdc`、`rules/response-safety.mdc`）
2. `AGENTS.md`（本文件：协作约定与质量门槛）
3. `CLAUDE.md`（仓库结构、常用命令、风格约定）
4. `README.md` + `TECHNICAL.md`（运行方式、入口、调用链）
5. 如任务涉及配置/运行：`config/default_config.yaml`（默认配置模板）与 `ly_next/core/config.py`（配置加载逻辑）
6. 如任务涉及工具/能力：`ly_next/tools/`、`ly_next/api/mcp_api.py`、`ly_next/mcp/`
7. 如任务涉及 Web 工作台：`.workbench-src/`（源码）与 `www/`（构建产物）
8. 仅在需要本机环境细节时：`TOOLS.md`
9. 仅在需要长期上下文时：`MEMORY.md`

## 什么时候写回 `MEMORY.md`

只在信息 **跨会话仍然成立** 且对后续有价值时写回，建议在会话末尾集中写一次：

- **应该写回**：
  - 稳定的约束/偏好（例如固定端口、部署形态、必须遵守的安全边界）
  - 重要决策与原因（例如为何选择某种 Provider/配置策略）
  - 已验证的排障结论（包含“如何复现/如何验证已修复”）
- **不应该写回**：
  - 临时试错过程、一次性日志
  - 明文密钥、敏感路径、私人信息
  - 未验证的猜测

写入格式保持短条目：`- 结论：... / 依据：... / 影响：...`

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
