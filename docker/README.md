<div align="center">

# Docker 部署

[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

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

> 构建前请确认仓库根目录 **`www/`** 已存在且完整（`Dockerfile` 会 `COPY www`，不在镜像内构建前端）。

```bash
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

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
