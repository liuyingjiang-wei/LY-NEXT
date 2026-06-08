<div align="center">

# pgvector

**PostgreSQL vector 扩展 · RAG 依赖**

[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=plastic&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-Extension-6366f1?style=flat)](https://github.com/pgvector/pgvector)

[← 安装说明](./README.md) · [Docker pgvector](../docker/README.md#pgvector)

</div>

---

## 目录

- [推荐：统一安装](#推荐统一安装)
- [前置条件](#前置条件)
- [Windows 手动编译](#windows-手动编译)
- [Linux 包管理器](#linux-包管理器)
- [Docker](#docker)
- [常见问题](#常见问题)

---

LY-NEXT 的 RAG 依赖 PostgreSQL 的 **vector** 扩展。日常使用请走统一安装脚本，本文档用于手动排错。

---

## 推荐：统一安装

**Windows**（管理员 PowerShell，项目根目录）：

```powershell
.\install.ps1
```

**Linux / macOS**：

```bash
sudo bash install.sh
```

脚本会：检测 → 安装 PostgreSQL（若缺失）→ 启动服务 → 创建 `ly_next` → `CREATE EXTENSION vector`；Windows 上若缺少扩展文件且本机有 Git + VS C++，会尝试编译 pgvector。

仅补 pgvector：

```powershell
.\install.ps1 -Pgvector
```

安装脚本会自动测速常用 GitHub 代理并选用最快的（默认列表含 `gh-proxy.com`、`ghfast.top`、`ghproxy.net` 等）。指定固定代理：

```powershell
$env:LY_NEXT_GITHUB_PROXY = "https://gh-proxy.com/"
.\install.ps1 -Pgvector
```

跳过测速、按默认顺序尝试：`$env:LY_NEXT_GITHUB_PROXY_SKIP_PROBE = "1"`

---

## 前置条件

运行 `.\install.ps1 -Yes` 或 `.\install.ps1 -ConfigureOnly` 后，下列项通常已自动完成。手动排错时检查：

| # | 检查项 |
|---|--------|
| 1 | PostgreSQL **TCP 可连接**（Windows：`Start-Service postgresql-x64-17`） |
| 2 | `data/ly_next/config.yaml` 中已有 **`database.password`**（脚本默认 `postgres`） |
| 3 | 数据库 **`ly_next`** 已存在 |

验证：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
```

---

## Windows 手动编译

> 仅当安装脚本无法自动完成时使用。

需要：Git、Visual Studio 2022 **C++ 桌面开发** 或 Build Tools（含 `vcvars64.bat`）。

1. 确认 `C:\Program Files\PostgreSQL\17\share\extension\vector.control` 是否存在
2. 若不存在，从 [pgvector](https://github.com/pgvector/pgvector) 获取对应 tag 源码。安装脚本会缓存到 `data/ly_next/cache/pgvector_src/pgvector`；若 GitHub 不通，可手动下载 [v0.8.0 zip](https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.0.zip) 解压到该目录（须含 `Makefile.win`）。在 **x64 Native Tools**（建议**管理员** PowerShell）环境中：

```bat
set PGROOT=C:\Program Files\PostgreSQL\17
cd pgvector
nmake /F Makefile.win clean
nmake /F Makefile.win
nmake /F Makefile.win install
```

3. 在库中执行 `CREATE EXTENSION vector;`

---

## Linux 包管理器

将 `17` 换成你的 PostgreSQL 主版本（`psql --version`）。

<details>
<summary><strong>Ubuntu / Debian</strong></summary>

```bash
sudo apt update
sudo apt install -y postgresql-17-pgvector
sudo -u postgres createdb ly_next 2>/dev/null || true
sudo -u postgres psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

</details>

<details>
<summary><strong>RHEL / Rocky / Alma</strong></summary>

```bash
sudo dnf install -y pgvector_17
sudo -u postgres psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
brew install pgvector
psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

</details>

---

## Docker

```bash
docker compose -f docker/docker-compose.yml -f docker/compose.pgvector.yml up -d
```

进入库后执行 `CREATE EXTENSION IF NOT EXISTS vector;`。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `Connection refused` | 启动 PostgreSQL；检查 `postgresql.conf` 中 `port` 与配置一致 |
| 认证失败 | 在 `config.yaml` 填写正确的 `database.password` |
| `vector.control` 已有但扩展未启用 | `.\install.ps1 -Pgvector` 或手动 `CREATE EXTENSION` |
| Windows 无法启动服务 | **管理员**终端，或于「服务」中启动 `postgresql-x64-*` |
