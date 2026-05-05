# 安装（install/）

用于安装 **Redis / PostgreSQL / pgvector**（开发环境）。

## 一键安装 Redis + PostgreSQL

### 自动检测系统（推荐）

```bash
# Linux/macOS
bash install/install-auto.sh
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File ".\install\install-auto.ps1"
```

### 仅 Windows

```powershell
powershell -ExecutionPolicy Bypass -File ".\install\install-windows.ps1"
```

### 仅 Linux / macOS

```bash
bash install/install.sh
```

在 **Ubuntu / Debian** 上，`install.sh` 还会在检测到 PostgreSQL 主版本后尝试安装 `postgresql-<主版本>-pgvector`，创建数据库 `ly_next` 并执行 `CREATE EXTENSION IF NOT EXISTS vector`。若仓库中没有对应 pgvector 包，请按 `install/pgvector.md` 配置 PGDG 或其它源后再安装。

首次启动 LY-NEXT 时，若本机 Redis 启用了 `requirepass` 而配置里 `redis.password` 为空，程序会尝试从运行中的 Redis（`CONFIG GET requirepass` / `redis.conf`）同步密码到配置文件。

## 安装 pgvector（按系统/发行版）

详见 `install/pgvector.md`  
Windows 脚本：`install/pgvector-windows.ps1`

