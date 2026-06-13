<div align="center">

# Docker 部署

[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=plastic&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

[← 返回主 README](../README.md) · [安装脚本](../install/README.md)

</div>

---

## 部署形态

| 形态 | Compose | LY-NEXT 进程 | PG/Redis 连接 |
|------|---------|--------------|---------------|
| **仅依赖** | `docker-compose.yml` | 宿主机 `uv run ly` | `DATABASE_HOST=127.0.0.1`（映射端口） |
| **完整 Demo** | `--profile app` | 容器 `ly-next-app` | 容器内 `postgres` / `redis` |
| **pgvector** | 叠加 `compose.pgvector.yml` | 同上 | 使用 `pgvector/pgvector:pg17` 镜像 |

官方文档：[Docker Compose](https://docs.docker.com/compose/) · [PostgreSQL Docker](https://hub.docker.com/_/postgres) · [Redis Docker](https://hub.docker.com/_/redis) · [pgvector Docker](https://github.com/pgvector/pgvector#docker)

---

## 仅依赖（Redis + PostgreSQL）

在仓库根目录：

```bash
docker compose -f docker/docker-compose.yml up -d
```

或进入本目录：

```bash
cd docker
cp .env.example .env   # 可选
docker compose up -d
```

端口映射见 `docker/.env`（默认 `5432`、`6379` 到宿主机）。

**宿主机运行 LY-NEXT：**

```bash
export DATABASE_HOST=127.0.0.1
export REDIS_HOST=127.0.0.1
export LY_NEXT_POSTGRES_PASSWORD=postgres   # 与 .env 中 POSTGRES_PASSWORD 一致
bash install.sh --configure-only
uv run ly
```

也可只改 `data/ly_next/config.yaml` 中的 `database.host` / `redis.host`，不跑安装脚本。

---

## 构建并运行应用

仓库已包含 Web 静态资源（`www/`），直接构建镜像：

```bash
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

容器环境已设置 `DATABASE_HOST=postgres`、`REDIS_HOST=redis`（见 `docker-compose.yml`），**无需**在宿主机执行 `install.ps1`。

---

## 一键 Demo

在仓库根目录：

```bash
# Linux / macOS
bash docker/demo-up.sh

# Windows
powershell -ExecutionPolicy Bypass -File docker/demo-up.ps1
```

或手动：

```bash
cd docker
cp .env.example .env   # 可选，填入 OPENAI_API_KEY
docker compose --profile app up -d --build
```

| 地址 | 说明 |
|------|------|
| `http://127.0.0.1:8000/ly/login` | 工作台登录 |
| `http://127.0.0.1:8000/docs` | OpenAPI |

**API 密钥：** 首次启动写入数据卷 `ly-app-data`：

```bash
docker exec ly-next-app cat /app/data/ly_next/FIRST_RUN.txt
```

**容器内诊断：**

```bash
docker exec ly-next-app ly doctor
```

**仅 Ollama、无云 API Key：** 见 [docs/QUICKSTART.md](../docs/QUICKSTART.md) 路径 ①，在工作台将默认 provider 改为 Ollama。

停止 Demo：`docker compose -f docker/docker-compose.yml --profile app down`

---

## pgvector

使用带 vector 扩展的 PostgreSQL 镜像：

```bash
docker compose -f docker/docker-compose.yml -f docker/compose.pgvector.yml up -d
```

首次在库 `ly_next` 中执行（若未自动创建）：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## 配置说明

| 项 | 说明 |
|----|------|
| `DATABASE_HOST=postgres` | **仅 app 容器**内连接 PG 的服务名 |
| `REDIS_HOST=redis` | **仅 app 容器**内连接 Redis 的服务名 |
| `POSTGRES_PUBLISH` / `REDIS_PUBLISH` | 映射到宿主机的端口（宿主机 `uv run ly` 时用） |
| `ly-app-data` 卷 | 挂载到 `/app/data`（`--profile app`） |

运行时环境变量与 `ly_next/default_config.yaml` 中的 `${DATABASE_HOST:-localhost}`、`${REDIS_HOST:-localhost}` 一致；详见 [install/README.md](../install/README.md)。
