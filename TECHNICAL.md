# LY-NEXT 代码阅读路径

## 推荐阅读顺序

1. `ly_next/main.py`：应用启动、路由挂载、生命周期。
2. `ly_next/api/`：`ly_api.py`、`ws_api.py`（对话入口）；`runs_api.py`（运行追踪）；`threads_api.py`（会话持久化）；`loader.py`（目录 API 加载，见 SECURITY.md）；`mcp_api.py`（MCP 协议）。
3. `ly_next/agent/factory.py`：Agent 模式选择（react / plan / chat / coordinator）。
4. `ly_next/agent/react.py`、`plan.py`、`chat.py`、`coordinator.py`：ReAct（compat / native / legacy）、Plan 图、Chat 直连、Coordinator 分解—委派—汇总。
5. `ly_next/agent/prompt_augment.py`、`prompt_templates.py`：运行时上下文增强（示例检索、知识库 RAG、启动记忆）与提示词片段；包内默认 `ly_next/agent/prompt_builtin/*.md`；`data/ly_next/prompts/`（`agent.prompts.prompts_dir`）同名文件优先。`agent.prompts.enabled: false` 时**只**读 data 目录。
6. `ly_next/agent/deps.py`：LLM 调用、工具注入、运行参数汇总。
7. `ly_next/agent/model_router.py`、`vision_precaption.py`：多模型路由与识图预描述（在 augment 之前执行）。
8. `ly_next/models/factory.py`、`openai_compat.py`：模型工厂与网关请求实现。
9. `ly_next/tools/`、`ly_next/mcp/`：工具注册、调用、MCP Server 与远程 MCP 桥接。
10. `ly_next/rag/`：示例检索、文档检索、embedding 调用链。
11. `ly_next/core/`：配置、日志、任务、数据库、缓存、`thread_persistence.py`（会话消息）、`checkpointer.py`（LangGraph 状态）、`run_lifecycle.py` / `run_store.py`（可观测性）。

## 一条对话在代码中的路径

### HTTP（非流式）

```
POST /api/chat
→ ly_next/api/ly_api.py
→ prepare_messages_for_agent（thread 历史）
→ apply_vision_precaption_if_needed
→ resolve_model_routing
→ start_observed_run（task_id = run_id）
→ persist_chat_turn
→ augment_messages_async
→ create_agent_deps → AgentFactory.create_agent → agent.run
→ finish_observed_run
```

### WebSocket（流式）

```
/api/ws + type=chat
→ ly_next/api/ws_api.py:handle_chat()
→ 同上预处理链
→ agent.run_stream()
→ chat_chunk / chat_status / chat_tool_* / chat_node / chat_complete
```

## Agent 层阅读重点

- **react**：`_react_loop_kind` 在 **compat**（JSON 工具协议）、**native**（`chat_with_tools`）、**legacy**（LangGraph `plan→act→check`）间选择；仅 **legacy** 与 **plan** 使用 LangGraph checkpoint。
- **plan**：先生成步骤再逐步执行，适合多步任务拆解。
- **chat**：最小路径，无工具、无图像。
- **coordinator**：LLM 分解子任务 → 多个 `ReactAgent` 委托 → 汇总。

## 会话与追踪

- **`thread_id`**：跨轮会话标识，持久化于 `sessions` / `messages`（需 PostgreSQL）；LangGraph checkpoint 亦按 `thread_id` 恢复。
- **`task_id` / `run_id`**：单次请求标识；可观测性写入 `agent_runs` / `agent_run_events`。
- 查询：`GET /api/runs` 等（`runs_api.py`）；`agent.observability.enabled: false` 时返回 404。鉴权为 `auth.api_key`（`X-API-Key`），非模型密钥。

## LLM 层阅读重点

- `models/factory.py`：provider 解析与客户端缓存（openai / openai_compat / anthropic / ollama）。
- `models/openai_compat.py`：请求头、请求体、流式解析、错误处理。
- `models/openai_chat_body.py`：`max_tokens` / `max_completion_tokens` 组装策略。

## 配置与运行时关系

- 主配置文件：`data/ly_next/config.yaml`。
- 设置接口：`GET/PATCH /api/system/settings`；控制台 `/ly/` 拆为 **「应用配置」**（日志、鉴权、Agent 与工具策略、扩展 API、内置工具、网络搜索、`agent.rag.enabled` 等）与 **「模型配置」**（`llm`、各 provider、`model_router`、`vision_precaption`、`rag.embedding`、`agent.observability`、`agent.prompts` 等），PATCH 为深度合并。
- 关键运行参数：
  - `llm.default_provider`
  - `agent.reasoning_mode`（react / plan / chat / coordinator）
  - `agent.stream_output`

## 运行追踪（P0 可观测）

- 配置：`agent.observability`（`enabled`、`persist`、`ws_run_summary`、`max_events_per_run`、`store_prompts`）。
- 入口/出口：`run_lifecycle.start_observed_run` / `finish_observed_run`；过程事件：`run_telemetry`；`loop_kind` 在 agent 入口设置。

## 调试建议（按层定位）

1. 入口层：`ly_api.py` / `ws_api.py` 的请求与响应。
2. Agent 层：`agent.*` 是否进入预期模式，工具是否可用。
3. Model 层：`openai_compat.py` 组包与返回码；`model_router` / `vision_precaption` 是否改写 provider 与消息。
4. RAG 层：`rag/*` 是否回退 lexical，embedding 是否可用。
5. 基础设施层：`core/logger.py`、数据库/Redis 状态、任务与 run 记录。
