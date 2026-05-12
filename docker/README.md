# Docker

## 仅依赖（Redis + PostgreSQL）

在仓库根目录：

```bash
docker compose -f docker/docker-compose.yml up -d
```

或进入本目录后：

```bash
cd docker
cp .env.example .env   # 可选
docker compose up -d
```

## 构建并运行应用（含上述依赖）

构建镜像前请确认仓库根目录下 **`www/` 已存在且内容完整**（`docker/Dockerfile` 会 `COPY www`，不在镜像内做前端构建）。

然后：

```bash
docker compose -f docker/docker-compose.yml --profile app up -d --build
```

## pgvector

使用带 vector 扩展的 PostgreSQL 镜像：

```bash
docker compose -f docker/docker-compose.yml -f docker/compose.pgvector.yml up -d
```

建库后执行：`CREATE EXTENSION IF NOT EXISTS vector;`

## 配置说明

- 应用在容器内通过环境变量 `DATABASE_HOST=postgres`、`REDIS_HOST=redis` 连接依赖服务；本地 `uv run ly` 仍默认 `localhost`（见默认配置中的 `${DATABASE_HOST:-localhost}`）。
- 持久化：`ly-app-data` 挂载到 `/app/data`（`--profile app` 时）。
