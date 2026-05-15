# LY-NEXT 代码阅读路径

## 推荐阅读顺序

1. ly_next/main.py：应用启动、路由挂载、生命周期。
2. ly_next/api/ly_api.py、ly_next/api/ws_api.py：HTTP/WS 对话入口与设置接口；动态挂载的目录 API 见 ly_next/api/loader.py（`api.security_profile`、`trusted_module_hashes`），安全说明见仓库根目录 SECURITY.md。Agent 提示词：`ly_next/agent/prompt_templates.py`，包内默认片段 `ly_next/agent/prompt_builtin/*.md`；`data/ly_next/prompts/`（`agent.prompts.prompts_dir`）同名文件优先。若 `agent.prompts.enabled` 为 `false`，则**只**从上述 data 目录加载，不再读包内 `prompt_builtin/`（缺文件时用代码内嵌 fallback）。
3. ly_next/agent/factory.py：Agent 模式选择（react/plan/chat）。
4. ly_next/agent/react.py、ly_next/agent/plan.py、ly_next/agent/chat.py：三种执行图。
5. ly_next/agent/deps.py：LLM 调用、工具注入、运行参数汇总。
6. ly_next/models/factory.py、ly_next/models/openai_compat.py：模型工厂与网关请求实现。
7. ly_next/tools/：工具注册、调用和 MCP 适配。
8. ly_next/rag/：示例检索、文档检索、embedding 调用链。
9. ly_next/core/：配置、日志、任务、数据库与缓存基础设施。

## 一条对话在代码中的路径

### HTTP（非流式）

POST /api/chat
-> ly_next/api/ly_api.py
-> augment_messages_async()
-> create_agent_deps()
-> AgentFactory.create_agent()
-> agent.run()
-> 返回完整响应

### WebSocket（流式）

/api/ws + type=chat
-> ly_next/api/ws_api.py:handle_chat()
-> agent.run_stream()
-> 连续发送 chat_chunk / chat_node
-> chat_complete

## Agent 层阅读重点

- react.py：Plan/Act/Check 循环，适合看工具调用主流程。
- plan.py：先生成步骤再执行，适合看多步任务拆解。
- chat.py：最小路径，适合定位基础聊天问题。

## LLM 层阅读重点

- models/factory.py：provider 解析与客户端缓存。
- models/openai_compat.py：请求头、请求体、流式解析、错误处理。
- models/openai_chat_body.py：max_tokens / max_completion_tokens 组装策略。

## 配置与运行时关系

- 主配置文件：data/ly_next/config.yaml。
- 设置接口：GET/PATCH /api/system/settings，对应 ly_api.py 的白名单 patch 逻辑；控制台 `/ly/` 拆为 **「应用配置」**（日志、鉴权相关开关、Agent 与工具策略、扩展 API、内置工具、网络搜索、`agent.rag.enabled` 等）与 **「模型配置」**（`llm`、各 provider、`model_router`、`vision_precaption`、`rag.embedding` 等），PATCH 为深度合并，两页勿重复提交互斥字段即可。
- 关键运行参数：
  - llm.default_provider
  - openai_compat_llm.*
  - agent.reasoning_mode
  - agent.stream_output

## 调试建议（按层定位）

1. 入口层：先看 ly_api.py / ws_api.py 的请求与响应。
2. Agent 层：看 agent.* 是否进入预期模式，工具是否可用。
3. Model 层：看 openai_compat.py 组包与返回码。
4. RAG 层：看 rag/* 是否回退 lexical，embedding 是否可用。
5. 基础设施层：看 core/logger.py、数据库/Redis 状态与任务记录。

