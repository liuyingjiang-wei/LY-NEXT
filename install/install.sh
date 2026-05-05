#!/usr/bin/env bash
set -euo pipefail

info()    { printf "[INFO] %s\n" "$*"; }
ok()      { printf "[OK]   %s\n" "$*"; }
warn()    { printf "[WARN] %s\n" "$*"; }
err()     { printf "[ERR]  %s\n" "$*"; }

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    err "Please run with sudo/root."
    exit 1
  fi
}

detect_linux_id() {
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "${ID:-unknown}"
  else
    echo "unknown"
  fi
}

_ubuntu_setup_pgvector() {
  local PG_VER
  PG_VER="$(pg_lsclusters 2>/dev/null | awk 'NR>1 && $1 ~ /^[0-9]+$/ { print $1; exit }')"
  if [ -z "$PG_VER" ]; then
    PG_VER="$(psql --version 2>/dev/null | sed -n 's/.* \([0-9][0-9]*\)\.[0-9].*/\1/p' | head -1)"
  fi
  if [ -z "$PG_VER" ]; then
    warn "无法检测 PostgreSQL 主版本，跳过 postgresql-*-pgvector 安装；可手动执行 install/pgvector.md"
    return 0
  fi
  info "检测到 PostgreSQL 主版本: $PG_VER"
  if apt-get install -y "postgresql-${PG_VER}-pgvector" 2>/dev/null; then
    ok "已安装 postgresql-${PG_VER}-pgvector"
  else
    warn "未找到软件包 postgresql-${PG_VER}-pgvector（需换源或参考 install/pgvector.md 使用 PGDG）"
  fi
  if command -v psql >/dev/null 2>&1; then
    if ! sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'ly_next'" 2>/dev/null | grep -q 1; then
      sudo -u postgres createdb ly_next 2>/dev/null || warn "创建数据库 ly_next 失败，请检查 PostgreSQL 与本地连接方式"
    fi
    if sudo -u postgres psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null; then
      ok "已在库 ly_next 中启用 vector 扩展（pgvector）"
    else
      warn "未能执行 CREATE EXTENSION vector；请确认已安装 postgresql-${PG_VER}-pgvector 且库 ly_next 可访问"
    fi
  fi
}

_ubuntu_redis_password_hint() {
  if ! command -v redis-cli >/dev/null 2>&1; then
    return 0
  fi
  if ! systemctl is-active --quiet redis-server 2>/dev/null && ! systemctl is-active --quiet redis 2>/dev/null; then
    return 0
  fi
  local rp
  rp="$(redis-cli CONFIG GET requirepass 2>/dev/null | tail -n1 | tr -d '\r')"
  if [ -n "$rp" ] && [ "$rp" != "(nil)" ] && [ "$rp" != '""' ]; then
    info "当前 Redis 已设置 requirepass。首次启动 LY-NEXT 时会尝试把密码同步到 config 中的 redis.password；也可手工编辑 data/ly_next/config.yaml"
  fi
}

install_linux() {
  need_root
  local id
  id="$(detect_linux_id)"
  case "$id" in
    ubuntu|debian)
      apt-get update -y
      apt-get install -y redis-server postgresql postgresql-contrib
      systemctl enable --now redis-server || true
      systemctl enable --now postgresql || true
      _ubuntu_setup_pgvector
      _ubuntu_redis_password_hint
      ;;
    fedora)
      dnf install -y redis postgresql-server postgresql-contrib
      systemctl enable --now redis || true
      systemctl enable --now postgresql || true
      ;;
    rhel|centos|rocky|almalinux|ol)
      yum install -y redis postgresql-server postgresql-contrib
      postgresql-setup --initdb || true
      systemctl enable --now redis || true
      systemctl enable --now postgresql || true
      ;;
    arch|manjaro)
      pacman -Sy --noconfirm --needed redis postgresql
      systemctl enable --now redis || true
      systemctl enable --now postgresql || true
      ;;
    opensuse*|sles)
      zypper install -y -n redis postgresql postgresql-server
      systemctl enable --now redis || true
      systemctl enable --now postgresql || true
      ;;
    *)
      err "Unsupported Linux distro: $id"
      exit 1
      ;;
  esac
}

install_macos() {
  if ! command -v brew >/dev/null 2>&1; then
    err "Homebrew not found. Install from https://brew.sh"
    exit 1
  fi
  brew install redis postgresql@16
  brew services start redis || true
  brew services start postgresql@16 || true
}

verify() {
  if command -v redis-cli >/dev/null 2>&1; then ok "Redis: $(redis-cli --version 2>/dev/null || true)"; else warn "redis-cli not found"; fi
  if command -v psql >/dev/null 2>&1; then ok "PostgreSQL: $(psql --version 2>/dev/null || true)"; else warn "psql not found"; fi
}

case "$(uname -s)" in
  Linux)  info "Installing Redis + PostgreSQL (Linux)"; install_linux ;;
  Darwin) info "Installing Redis + PostgreSQL (macOS)"; install_macos ;;
  *)      err "Unsupported OS. Use install.ps1 on Windows." ; exit 1 ;;
esac

verify
ok "Done."
