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

## 安装 pgvector（按系统/发行版）

详见 `install/pgvector.md`  
Windows 脚本：`install/pgvector-windows.ps1`

