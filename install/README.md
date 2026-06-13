<div align="center">

# 依赖安装与基础设施

**Redis · PostgreSQL · pgvector · 写入 `config.yaml`**

[![Redis](https://img.shields.io/badge/Redis-6379-DC382D?style=plastic&logo=redis&logoColor=white)](https://redis.io/docs/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=plastic&logo=postgresql&logoColor=white)](https://www.postgresql.org/docs/)
[![pgvector](https://img.shields.io/badge/pgvector-Extension-6366f1?style=flat)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=plastic&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

<br />

[← 返回主 README](../README.md) · [Docker 部署](../docker/README.md) · [pgvector 排错](./pgvector.md)

</div>

---

## LY-NEXT 需要哪些基础设施？

| 组件 | 用途 | 是否必须 |
|------|------|----------|
| **LLM API / Ollama** | 对话与嵌入 | 聊天必须 |
| **PostgreSQL** | 会话持久化、Run、部分状态 | 可选（无则主要用浏览器本地） |
| **Redis** | 缓存、协调、部分队列 | 可选 |
| **pgvector** | RAG 向量检索 | 仅 RAG 需要（依赖 PostgreSQL） |

应用本身可在 **任意能跑 Python 的机器** 上启动（笔记本、服务器、容器）。PostgreSQL / Redis 可以与 LY-NEXT **同机**，也可以 **Docker 单独起依赖**、**远程 VPS** 或 **云托管**（RDS、Azure Database、Upstash 等）。限制在于 **网络能否连通** 与 **pgvector 是否在目标库上可用**，而不是「只能本机」。

官方参考：

- [uv 安装](https://docs.astral.sh/uv/getting-started/installation/)（项目 Python 依赖）
- [PostgreSQL 下载与文档](https://www.postgresql.org/download/)
- [Redis 安装](https://redis.io/docs/latest/operate/oss_and_stack/install/)
- [pgvector 安装方式汇总](https://github.com/pgvector/pgvector#installation)（包管理器、源码、Docker、托管库）
- [Docker Compose 文档](https://docs.docker.com/compose/)

---

## 三种常见部署方式

### 方式 A：系统包安装脚本（同机 PG + Redis）

在 **将要运行 `uv run ly` 的机器** 上，用脚本安装 Redis、PostgreSQL，并写入 `data/ly_next/config.yaml`（默认连接 `127.0.0.1`）。

| 系统 | 命令（仓库根目录） |
|------|-------------------|
| **Windows** | 管理员 PowerShell：`.\install.ps1 -Yes` |
| **Linux** | `sudo bash install.sh -y` |
| **macOS** | `bash install.sh -y`（需 Homebrew；pgvector 见下） |

脚本会尝试：

- 安装并启动 Redis、PostgreSQL（按发行版用 apt/dnf/yum/pacman/winget/choco 等）
- 合并 **`database.*` / `redis.*`** 到 `data/ly_next/config.yaml`
- 创建库 **`ly_next`**，并执行 **`CREATE EXTENSION vector`**（在支持的平台上）
- Windows 上 winget/Chocolatey 安装 PG 时常见默认密码 **`postgres`**

**Linux 发行版（包安装）：** Ubuntu/Debian、Fedora、RHEL/Rocky/Alma、Arch、openSUSE（见 `install/install.sh`）。  
**macOS：** 通过 Homebrew 安装 `redis`、`postgresql@17`；pgvector 会尝试 `brew install pgvector`，失败时见 [pgvector.md](./pgvector.md)。

---

### 方式 B：Docker 只跑依赖（应用在宿主机 `uv run ly`）

适合：不想在系统里装 PG/Redis，但希望在本机或内网用 Docker 提供依赖。

```bash
# 仓库根目录
docker compose -f docker/docker-compose.yml up -d

# RAG 需要 pgvector 镜像
docker compose -f docker/docker-compose.yml -f docker/compose.pgvector.yml up -d
```

Compose 会把 **5432 / 6379** 映射到宿主机（可在 `docker/.env` 改 `POSTGRES_PUBLISH`、`REDIS_PUBLISH`）。  
在宿主机启动 LY-NEXT 时，连接地址为 **映射后的主机与端口**（本机一般为 `127.0.0.1`）：

```bash
export DATABASE_HOST=127.0.0.1
export REDIS_HOST=127.0.0.1
# 密码与 docker/.env 中 POSTGRES_PASSWORD 一致
export LY_NEXT_POSTGRES_PASSWORD=postgres
bash install.sh --configure-only   # 写入 config.yaml
uv run ly
```

也可直接编辑 `data/ly_next/config.yaml`，或仅依赖运行时环境变量（见下节）。  
完整说明：[docker/README.md](../docker/README.md)。

---

### 方式 C：远程或托管 PostgreSQL / Redis

适合：云服务器分体部署、团队共用数据库、托管 Redis/PG。

1. 准备可连通的 PostgreSQL（**RAG 需支持 pgvector**；多数托管库需在控制台启用扩展，见 [pgvector 托管列表](https://github.com/pgvector/pgvector#hosted-postgres)）。
2. 创建数据库 `ly_next`，执行 `CREATE EXTENSION IF NOT EXISTS vector;`（RAG 时）。
3. 配置连接（任选其一）：

**环境变量**（与 `ly_next/default_config.yaml` 一致，运行时生效）：

```bash
export DATABASE_HOST=db.example.com
export DATABASE_PORT=5432
export REDIS_HOST=redis.example.com
export REDIS_PORT=6379
export LY_NEXT_POSTGRES_PASSWORD='你的密码'
uv run ly
```

**写入 config.yaml**（`install/configure_local.py` 合并写入，不覆盖未改字段）：

```bash
export LY_NEXT_DATABASE_HOST=db.example.com
export LY_NEXT_REDIS_HOST=redis.example.com
export LY_NEXT_POSTGRES_PASSWORD='你的密码'
bash install.sh --configure-only
```

**不要**在远程库场景下运行 `install.sh -y` 去装系统 PostgreSQL（除非你就是要在该机装服务）。用 `-ConfigureOnly` 或手改配置即可。

---

### 方式 D：应用也跑在 Docker（`--profile app`）

```bash
bash docker/demo-up.sh
# 或 docker compose -f docker/docker-compose.yml --profile app up -d --build
```

容器内 `DATABASE_HOST=postgres`、`REDIS_HOST=redis` 由 Compose 注入，**无需**再跑 `install.ps1`。见 [docker/README.md](../docker/README.md)。

---

## 常用命令与参数

根目录 `install.ps1`、`install.sh` 会转发到本目录。

**PowerShell**

```powershell
.\install.ps1 -Yes              # 安装缺失项 + 写配置
.\install.ps1 -ConfigureOnly    # 只写配置 / 建库 / pgvector（不装系统包）
.\install.ps1 -DetectOnly       # 只检测环境
.\install.ps1 -Pgvector         # 只处理 pgvector
.\install.ps1 -All              # Redis + PostgreSQL + pgvector
```

**Bash**

```bash
sudo bash install.sh -y
sudo bash install.sh --configure-only
sudo bash install.sh --detect-only
sudo bash install.sh --pgvector
```

**环境变量（安装 / 配置阶段）**

| 变量 | 作用 |
|------|------|
| `LY_NEXT_POSTGRES_PASSWORD` / `POSTGRES_PASSWORD` | PostgreSQL 密码（写 config、建库认证） |
| `LY_NEXT_DATABASE_HOST` / `DATABASE_HOST` | 写入 `database.host`（默认 `127.0.0.1`） |
| `LY_NEXT_DATABASE_PORT` / `DATABASE_PORT` | 写入 `database.port`（默认 `5432`） |
| `LY_NEXT_REDIS_HOST` / `REDIS_HOST` | 写入 `redis.host`（默认 `127.0.0.1`） |
| `LY_NEXT_REDIS_PORT` / `REDIS_PORT` | 写入 `redis.port`（默认 `6379`） |
| `LY_NEXT_GITHUB_PROXY` | Windows 编译 pgvector 时 GitHub 代理（见 [pgvector.md](./pgvector.md)） |

---

## 安装后

```bash
uv sync          # 首次克隆后
uv run ly        # 或 uv run ly --no-prompt
uv run ly doctor # 检查 LLM / PG / Redis / pgvector
```

若 PostgreSQL 密码与脚本假设不一致，修正 `data/ly_next/config.yaml` 后执行：

```powershell
.\install.ps1 -ConfigureOnly
```

---

## 目录说明

| 文件 | 说明 |
|------|------|
| `install.ps1` / `install.sh` | 交互/一键安装向导 |
| `pg-common.ps1` | Windows：检测服务、连库、pgvector、写配置 |
| `configure_local.py` | 将 JSON patch 深度合并进 `config.yaml` |
| `pgvector.md` | 各平台手动安装与排错 |

---

## 与「只能本机」有关的澄清

| 说法 | 实际情况 |
|------|----------|
| 默认 `127.0.0.1` | 脚本为 **同机安装的 PG/Redis** 填本地地址；远程部署请改 host 或用环境变量 |
| `install.sh` 要 sudo | 仅 **在 Linux 上安装系统包** 时需要；`--configure-only` 在 macOS 上通常不需 sudo |
| Windows 要管理员 | 安装/启动 **Windows 服务**（PostgreSQL、Redis）时需要 |
| pgvector 自动安装 | Ubuntu/Debian、RHEL 系会尝试包名 `postgresql-*-pgvector` / `pgvector_*`；其余见 [pgvector.md](./pgvector.md) |
| 不装 PG/Redis | 路径 ① 仍可聊天；会话主要留在浏览器，见 [QUICKSTART](../docs/QUICKSTART.md) |
