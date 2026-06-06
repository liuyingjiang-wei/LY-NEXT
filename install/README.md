<div align="center">

# 依赖安装

**Redis · PostgreSQL 17 · pgvector · 自动写入 config.yaml**

[![Redis](https://img.shields.io/badge/Redis-6379-DC382D?style=plastic&logo=redis&logoColor=white)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=plastic&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-Enabled-6366f1?style=flat)](./pgvector.md)

<br />

[← 返回主 README](../README.md)

</div>

---

## 快速开始

| 系统 | 命令（项目根目录） |
|------|-------------------|
| **Windows** | 管理员 PowerShell：`.\install.ps1 -Yes` |
| **Linux** | `sudo bash install.sh -y` |
| **macOS** | `sudo bash install.sh -y`（pgvector 见 [pgvector.md](./pgvector.md)） |

安装脚本会自动：

- 安装并启动 Redis、PostgreSQL
- 写入 **`database.*` / `redis.*`** 到 `data/ly_next/config.yaml`
- 创建数据库 **`ly_next`** 并执行 **`CREATE EXTENSION vector`**
- Windows 上 Chocolatey/winget 安装 PG 时默认密码 **`postgres`**

---

## 常用参数

**PowerShell**

```powershell
.\install.ps1 -Yes              # 安装未就绪项 + 写配置
.\install.ps1 -ConfigureOnly    # 仅写配置 / 建库 / pgvector
.\install.ps1 -DetectOnly       # 仅检测
```

**Bash**

```bash
sudo bash install.sh -y
sudo bash install.sh --configure-only
```

**自定义 PostgreSQL 密码**

```powershell
$env:LY_NEXT_POSTGRES_PASSWORD = "你的密码"
.\install.ps1 -ConfigureOnly
```

---

## 安装后

```bash
uv run ly
```

一般**无需再改** `config.yaml`。若 winget 安装 PG 时用了其它密码：

```powershell
.\install.ps1 -ConfigureOnly
```

---

## 目录说明

| 文件 | 说明 |
|------|------|
| `install.ps1` / `install.sh` | 安装向导 |
| `pg-common.ps1` | Windows：连库、pgvector、写配置 |
| `configure_local.py` | 合并写入 `config.yaml` |
| `pgvector.md` | 手动排错 |

根目录 `install.ps1`、`install.sh` 转发到本目录。
