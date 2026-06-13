# Quick Start — 四条上手路径

每条路径控制在 **5 步以内**。概览见 [README](../README.md)，排障见 [USER.md](./USER.md)。

> **成熟度：** LY-NEXT 当前为 **Alpha**（打包版本 1.0.1）。适合自托管与实验，**不建议公网裸奔**。部署前请运行 `uv run ly doctor` 并阅读 [SECURITY.md](../SECURITY.md)。

---

## 路径 ① 只聊天（Ollama / OpenAI 兼容网关）

适合：本机试 Agent、不接 QQ、可不装 PostgreSQL。

1. **安装并启动**

   ```bash
   git clone https://github.com/liuyingjiang-wei/LY-NEXT.git
   cd LY-NEXT
   uv sync
   uv run ly --no-prompt
   ```

2. **准备 LLM**
   - **Ollama：** 本机运行 `ollama serve`，拉取模型（如 `qwen2.5`）；工作台「模型配置」注册 Ollama 条目并设为默认。
   - **兼容网关：** 填 `openai_compat_llm.base_url`（勿与 LY-NEXT 自己的 8000 端口混淆）。

3. **登录工作台**  
   打开 `http://127.0.0.1:8000/ly/login`，API 密钥见 `data/ly_next/FIRST_RUN.txt` 或启动日志（默认脱敏）。

4. **自检**

   ```bash
   uv run ly doctor
   ```

   确认 `LLM: ✓` 与 `可对话: 是`。

5. **发第一条消息**  
   进入「智能对话」，发送「你好」。顶部横幅会提示 PG/Redis 是否缺失（可选）。

---

## 路径 ② 完整栈（PostgreSQL + Redis + RAG）

适合：会话持久化、Run 追踪、知识库检索。基础设施可 **Docker**、**安装脚本（同机）** 或 **远程/托管库**。

1. **启动依赖（任选一种）**

   **Docker（推荐，不污染系统）：**

   ```bash
   docker compose -f docker/docker-compose.yml up -d
   ```

   **系统包（与 `uv run ly` 同机）：**

   ```bash
   # Windows 管理员: .\install.ps1 -Yes
   # Linux: sudo bash install.sh -y
   # macOS: bash install.sh -y
   ```

   **远程 PostgreSQL / Redis：** 在 `data/ly_next/config.yaml` 填写 host/port，或启动前设置环境变量：

   ```bash
   export DATABASE_HOST=your-db-host
   export REDIS_HOST=your-redis-host
   export LY_NEXT_POSTGRES_PASSWORD='your-password'
   ```

   托管库需支持 pgvector（RAG）；见 [pgvector 托管列表](https://github.com/pgvector/pgvector#hosted-postgres)。

2. **（可选 RAG）启用 pgvector**

   Docker：

   ```bash
   docker compose -f docker/docker-compose.yml -f docker/compose.pgvector.yml up -d
   ```

   在库 `ly_next` 中执行：`CREATE EXTENSION IF NOT EXISTS vector;`（安装脚本与 pgvector 镜像通常会代为执行）。

   宿主机跑 LY-NEXT、Docker 跑依赖时：

   ```bash
   export DATABASE_HOST=127.0.0.1 REDIS_HOST=127.0.0.1
   bash install.sh --configure-only
   ```

3. **配置 LLM 与 Embedding**  
   工作台「模型配置」填对话模型；RAG 嵌入模型使用 `rag_embedding_llm`（可与对话模型相同 provider）。

4. **启用 RAG 并试检索**  
   「RAG 配置」→ 开启 `agent.rag` → 文档放入 `data/ly_next/knowledge/` → 保存 → 使用「试检索」验证命中。

5. **开启对话同步**  
   「智能对话」打开 **同步：开**，会话写入 PostgreSQL `thread_id`；Run 历史见「Run 追踪」Tab。

---

## 路径 ③ QQ 桥接（NapCat + OneBot v11）

适合：QQ 私聊/群 @ 自动回复。

1. **启动 LY-NEXT**

   ```bash
   uv run ly --no-prompt
   ```

   配置 LLM（路径 ① 第 2 步）。

2. **确认桥接已启用**  
   工作台「QQ / NapCat」→ `bridge.onebot11.enabled` 为开；记下 **NapCat URL**（诊断页可一键复制）。

3. **配置 NapCat**  
   NapCat WebUI → 网络配置 → **WebSocket 客户端**（非服务端）→ URL 填 `ws://127.0.0.1:8000/OneBotv11`（端口与 `server.port` 一致）。

4. **Token 对齐**  
   `bridge.onebot11.access_token` 与 NapCat Token **完全一致**；两边都留空则都留空。

5. **验证**  
   重启 LY-NEXT 后查看启动日志 `[onebot11] NapCat connected`；工作台「连接诊断」全部通过。群聊需 **@ 本号** 才会回复（默认 `group_at_only`）。

---

## 路径 ④ Telegram 桥接（Bot + 配对码）

适合：Telegram 私聊自动回复。

1. **启动 LY-NEXT** 并配置 LLM（同路径 ①）。
2. **安装插件** — 将 `telegram-bot` 放入 `plugins/local/telegram_bot`。
3. **配置 Token** — 环境变量 `TELEGRAM_BOT_TOKEN` 或工作台「Telegram」页；`bridge.telegram.enabled: true`。
4. **用户配对** — 用户向 Bot 发送 `/start` 获取配对码；管理员在工作台批准。
5. **验证** — `GET /api/system/extensions` 中 `telegram-bot` 为 loaded；私聊收到 Agent 回复。

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `uv run ly doctor` | 依赖、端口、安全体检（可复制 `--json` 报告） |
| `uv run ly doctor -o report.txt` | 写入诊断报告 |
| `uv run ly --no-prompt` | 非交互启动（脚本/CI/Docker） |

## Docker 一键 Demo

见 [docker/README.md](../docker/README.md#一键-demo)：

```bash
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

浏览器访问 `http://127.0.0.1:8000/ly/`，API 密钥见容器卷 `ly-app-data` 内 `FIRST_RUN.txt` 或 `docker logs ly-next-app`。
