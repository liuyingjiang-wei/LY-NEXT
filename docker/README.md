<div align="center">

# Docker 部署

[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=plastic&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

[← 返回主 README](../README.md)

</div>

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

---

## 构建并运行应用

仓库已包含 Web 静态资源（`www/`），直接构建镜像即可：

```bash
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

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

建库后执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## 配置说明

| 项 | 说明 |
|----|------|
| `DATABASE_HOST=postgres` | 容器内连接 PG |
| `REDIS_HOST=redis` | 容器内连接 Redis |
| `ly-app-data` 卷 | 挂载到 `/app/data`（`--profile app`） |

本地 `uv run ly` 仍默认 `localhost`（见配置中的 `${DATABASE_HOST:-localhost}`）。
