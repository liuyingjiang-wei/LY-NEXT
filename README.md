<div align="center">

# LY-NEXT

**自托管 AI 智能体服务 — 自带 Web 工作台，一条命令本地跑起来**

<br />

[![License: MIT](https://img.shields.io/badge/License-MIT-2563eb?style=flat)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-1.0.1--alpha-orange?style=flat)](./pyproject.toml)
[![Status](https://img.shields.io/badge/status-Alpha-yellow?style=flat)](#当前状态)

<br />

[GitHub](https://github.com/liuyingjiang-wei/LY-NEXT) · [Gitee](https://gitee.com/wei2335/LY-NEXT) · [文档导航](#文档导航)

</div>

---

## 这是什么

LY-NEXT 把 **对话、工具调用、模型管理、可选 QQ/Telegram 桥接** 收进一个 Python 服务。启动后打开浏览器里的 **工作台**，配置大模型、选对话场景、管理插件和桥接，无需再单独部署前端。

底层使用 FastAPI + LangGraph 风格 Agent 运行时；PostgreSQL / Redis 为**可选**依赖，不装也能在本机聊天，只是会话不会持久化到数据库。

---

## 当前状态

| 项目 | 说明 |
|------|------|
| 版本 | **1.0.1**（Alpha，见 `pyproject.toml`） |
| 适用 | 自托管、功能验证、个人/小团队实验 |
| 公网部署 | 先跑 `uv run ly doctor`，阅读 [SECURITY.md](./SECURITY.md)，在工作台「访问控制」完成体检 |

---

## 30 秒上手

**环境：** Python ≥ 3.10，推荐安装 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/liuyingjiang-wei/LY-NEXT.git
cd LY-NEXT
uv sync
uv run ly --no-prompt
```

然后在浏览器打开：

| 地址 | 用途 |
|------|------|
| [http://127.0.0.1:8000/ly/login](http://127.0.0.1:8000/ly/login) | 登录工作台 |
| [http://127.0.0.1:8000/ly/](http://127.0.0.1:8000/ly/) | 主控制台（登录后） |
| [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | OpenAPI 接口文档 |

**登录密钥：** 首次启动写在 `data/ly_next/FIRST_RUN.txt`（与 `config.yaml` 里 `auth.api_key` 一致）。工作台「访问控制」可一键同步。

**还没配模型？** 默认已指向本机 **Ollama**（`qwen2.5`）。先运行 `ollama serve` 并拉取模型即可聊天；或使用 OpenAI 等云端模型 — 见「模型配置」或 [docs/QUICKSTART.md](./docs/QUICKSTART.md) 路径 ①。

```bash
uv run ly doctor          # 检查 LLM / PG / Redis / 安全项
uv run ly config migrate  # 合并 legacy LLM 块、修正错误的 compat URL
uv run ly --reload        # 开发时热重载
uv run ly --port 9000     # 指定端口
```

---

## 工作台能做什么

首次进入会引导 **配置向导**；侧栏 **入门引导** 在检查清单全部完成前可见。

| 你想… | 去这里 |
|--------|--------|
| 和 Agent 聊天、换场景、一键应用 Agent 预设 | **智能对话** |
| 注册模型、设默认 LLM、测连通性 | **模型配置** |
| 看依赖是否就绪、同步登录密钥 | 顶部 **状态横幅** |
| 接 QQ（NapCat）或 Telegram | **桥接总览** → 对应桥接页 |
| 安装/查看插件目录与 doctor 提示 | **基础设施 → 插件** |
| 本机危险操作审批、安全策略 | **访问控制** |
| 长期记忆、工具溢出、协调器 | **智能体进阶** |
| 对话一直转圈、插件不加载 | [docs/USER.md](./docs/USER.md) 排障表 |

对话支持 WebSocket 流式输出；未连上 PostgreSQL 时，记录主要保存在浏览器本地，可导出 JSON 备份。

---

## 按场景上手

详细分步见 **[docs/QUICKSTART.md](./docs/QUICKSTART.md)**（每条路径约 4–5 步）：

| 路径 | 适合谁 |
|------|--------|
| ① 只聊天 | 本机试 Agent，Ollama / 兼容网关即可 |
| ② 完整栈 | 要持久化会话、RAG、Run 历史 → Docker 起 PG + Redis |
| ③ QQ 桥接 | NapCat + `qq-onebot` 插件 |
| ④ Telegram | Bot + 配对码批准 |

桥接与能力插件安装在 `plugins/local/` 或通过 pip，**不随 core 仓库提交** — 见 [plugins/README.md](./plugins/README.md)。

---

## Docker 与本机依赖（可选）

PostgreSQL / Redis 可与 LY-NEXT **同机、Docker、或远程托管**；不装也能聊天（会话主要留在浏览器）。详见 [install/README.md](./install/README.md)。

```bash
# 方式 B：Docker 只跑依赖（应用在宿主机 uv run ly）
docker compose -f docker/docker-compose.yml up -d

# 一键 Demo（依赖 + 应用容器）
bash docker/demo-up.sh
```

```bash
# 方式 A：系统包安装 PG + Redis（同机）
# Windows 管理员: .\install.ps1 -Yes
# Linux: sudo bash install.sh -y
```

宿主机连 Docker 依赖时，可设置 `DATABASE_HOST` / `REDIS_HOST`（通常 `127.0.0.1`）后 `bash install.sh --configure-only`。  
应用容器化见 [docker/README.md](./docker/README.md)。

---

## 文档导航

读哪份、什么时候读：

| 文档 | 给谁看 | 内容 |
|------|--------|------|
| **README**（本文） | 新用户 | 是什么、怎么启动、工作台入口 |
| [docs/QUICKSTART.md](./docs/QUICKSTART.md) | 新用户 | 四条场景化上手路径 |
| [docs/USER.md](./docs/USER.md) | 使用者 | 症状 → 原因 → 处理排障 |
| [TECHNICAL.md](./TECHNICAL.md) | 开发者 | 架构、代码路径、API、插件与配置细节 |
| [SECURITY.md](./SECURITY.md) | 部署者 | 威胁模型与安全检查 |
| [plugins/README.md](./plugins/README.md) | 插件用户 | 桥接/能力插件安装 |
| [CHANGELOG.md](./CHANGELOG.md) | 所有人 | 版本变更记录 |

改 Python 后端、读 Pipeline、接插件 API → 直接看 **TECHNICAL.md**，不必在 README 里翻长表。

---

## 安全提示

- 默认配置偏向本地开发（如 CORS 较宽）。**公网或多人环境**请收紧 `auth`，并在工作台将 `security_profile` 设为 `production`（需重启进程）。
- `data/` 含配置与密钥，已在 `.gitignore` 中，勿提交到 Git。
- QQ / Telegram Token 建议用环境变量（见 `.env.example`）。

---

## 参与与许可

```bash
uv run ruff format . && uv run ruff check .
uv run pytest -q
```

贡献约定与模块索引见 [AGENTS.md](./AGENTS.md)。

**MIT License** · [LICENSE](./LICENSE)

<div align="center">

若 README 与行为不一致，以代码与 `docs/USER.md` 为准；架构与接口细节以 [TECHNICAL.md](./TECHNICAL.md) 为准。

</div>
