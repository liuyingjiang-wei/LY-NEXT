# pgvector 安装

## Windows（本机 PostgreSQL）

使用脚本（需要 Git + VS Build Tools / VS 2022 C++ 工具链）：

```powershell
# 仅检查
powershell -ExecutionPolicy Bypass -File ".\install\pgvector-windows.ps1" -PostgresMajor 16 -VerifyOnly -UseWeiConfig

# 编译安装 + 在数据库启用扩展
powershell -ExecutionPolicy Bypass -File ".\install\pgvector-windows.ps1" -PostgresMajor 16 -Build -UseWeiConfig

# 手动指定 vcvars64.bat
powershell -ExecutionPolicy Bypass -File ".\install\pgvector-windows.ps1" -PostgresMajor 16 -Build -UseWeiConfig -VcVarsPath "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
```

完成后在目标库执行（脚本会自动执行）：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Ubuntu / Debian

以 PostgreSQL 16 为例（版本按你的 PostgreSQL 主版本调整）：

```bash
sudo apt update
sudo apt install -y postgresql-16-pgvector
sudo -u postgres psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

如果系统源没有对应版本的包，可使用 PostgreSQL 官方仓库（PGDG），然后安装 `postgresql-<ver>-pgvector`。

## RHEL / Rocky / AlmaLinux

以 PostgreSQL 16 为例：

```bash
sudo dnf install -y pgvector_16
sudo -u postgres psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## macOS（Homebrew）

```bash
brew install pgvector
psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## Docker（最省事的开发方式）

如果你用 Docker 跑 PostgreSQL，建议直接使用带 pgvector 的镜像；启动后在库里执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

