#!/usr/bin/env bash
set -euo pipefail

info()  { printf "[INFO] %s\n" "$*"; }
ok()    { printf "[OK]   %s\n" "$*"; }
warn()  { printf "[WARN] %s\n" "$*"; }
err()   { printf "[ERR]  %s\n" "$*"; }

INSTALL_REDIS=0
INSTALL_POSTGRESQL=0
INSTALL_PGVECTOR=0
DETECT_ONLY=0
FORCE=0
YES=0
INSTALL_ALL=0
CONFIGURE_ONLY=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<'EOF'
LY-NEXT 依赖安装向导

  直接运行进入交互菜单（检测 → 选择 → 安装）:
    bash install/install.sh

  可选参数:
    -y, --yes             安装所有缺失项（无菜单）
    --all                 安装 Redis + PostgreSQL + pgvector（一键全套）
    --redis / --postgresql / --pgvector   只装指定项
    --detect, -d          仅检测
    --force               已安装也重新执行
    --configure-only      仅写入 config.yaml + 建库/pgvector（不安装包）
    -h, --help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --detect|-d) DETECT_ONLY=1 ;;
    -y|--yes) YES=1 ;;
    --all) INSTALL_ALL=1 ;;
    --redis) INSTALL_REDIS=1 ;;
    --postgresql|--postgres) INSTALL_POSTGRESQL=1 ;;
    --pgvector) INSTALL_PGVECTOR=1 ;;
    --force) FORCE=1 ;;
    --configure-only) CONFIGURE_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) err "未知参数: $1"; usage; exit 1 ;;
  esac
  shift
done

ly_detect_redis() {
  local cli=0 svc=0 ver="" reachable=0
  command -v redis-cli >/dev/null 2>&1 && cli=1
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active --quiet redis-server 2>/dev/null && svc=1
    systemctl is-active --quiet redis 2>/dev/null && svc=1
  fi
  [ "$cli" -eq 1 ] && ver="$(redis-cli --version 2>/dev/null | head -1 || true)"
  [ "$cli" -eq 1 ] && redis-cli ping 2>/dev/null | grep -q PONG && reachable=1
  printf '%s|%s|%s|%s\n' "$cli" "$svc" "$ver" "$reachable"
}

ly_detect_postgresql() {
  local cli=0 svc=0 ver="" reachable=0
  command -v psql >/dev/null 2>&1 && cli=1
  command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet postgresql 2>/dev/null && svc=1
  [ "$cli" -eq 1 ] && ver="$(psql --version 2>/dev/null | head -1 || true)"
  [ "$cli" -eq 1 ] && psql -U postgres -tAc "SELECT 1" 2>/dev/null | grep -q 1 && reachable=1
  printf '%s|%s|%s|%s\n' "$cli" "$svc" "$ver" "$reachable"
}

ly_detect_pgvector() {
  local ok=0 detail=""
  if command -v psql >/dev/null 2>&1 && psql -U postgres -tAc "SELECT 1" 2>/dev/null | grep -q 1; then
    if psql -U postgres -d ly_next -tAc "SELECT 1 FROM pg_extension WHERE extname='vector'" 2>/dev/null | grep -q 1; then
      ok=1; detail="ly_next.vector"
    else
      detail="未启用"
    fi
  else
    detail="需先安装 PostgreSQL"
  fi
  printf '%s|%s\n' "$ok" "$detail"
}

ly_component_ok() {
  local name="$1"
  case "$name" in
    redis)
      IFS='|' read -r cli svc _ _ <<<"$(ly_detect_redis)"
      [ "$cli" = "1" ] || [ "$svc" = "1" ]
      ;;
    postgresql)
      IFS='|' read -r cli svc _ _ <<<"$(ly_detect_postgresql)"
      [ "$cli" = "1" ] || [ "$svc" = "1" ]
      ;;
    pgvector)
      IFS='|' read -r ok _ <<<"$(ly_detect_pgvector)"
      [ "$ok" = "1" ]
      ;;
    *) return 1 ;;
  esac
}

ly_show_status() {
  local r p v rcli rsvc rver rr pcli psvc pver pr pgok pgdet
  IFS='|' read -r rcli rsvc rver rr <<<"$(ly_detect_redis)"
  IFS='|' read -r pcli psvc pver pr <<<"$(ly_detect_postgresql)"
  IFS='|' read -r pgok pgdet <<<"$(ly_detect_pgvector)"

  echo ""
  echo "=== LY-NEXT 依赖环境 ==="
  if [ "$rcli" = "1" ] || [ "$rsvc" = "1" ]; then
    printf "  %-12s [已安装]" "Redis"
    [ -n "$rver" ] && printf " — %s" "$rver"
    [ "$rr" = "1" ] && printf ", 可连接"
    printf "\n"
  else
    printf "  %-12s [未安装]\n" "Redis"
  fi
  if [ "$pcli" = "1" ] || [ "$psvc" = "1" ]; then
    printf "  %-12s [已安装]" "PostgreSQL"
    [ -n "$pver" ] && printf " — %s" "$pver"
    [ "$pr" = "1" ] && printf ", 可连接"
    printf "\n"
  else
    printf "  %-12s [未安装]\n" "PostgreSQL"
  fi
  if [ "$pgok" = "1" ]; then
    printf "  %-12s [已安装] — %s\n" "pgvector" "$pgdet"
  else
    printf "  %-12s [未安装] — %s\n" "pgvector" "$pgdet"
  fi
  echo ""
}

ly_missing_list() {
  IFS='|' read -r _ _ _ rr <<<"$(ly_detect_redis)"
  [ "$rr" != "1" ] && echo redis
  ly_component_ok postgresql || echo postgresql
  ly_component_ok pgvector || echo pgvector
}

detect_linux_id() {
  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "${ID:-unknown}"
  else echo "unknown"; fi
}

need_root() {
  [ "$(uname -s)" = "Linux" ] && [ "$(id -u)" -ne 0 ] && { err "Linux 安装需要 sudo"; exit 1; }
}

_ubuntu_setup_pgvector() {
  local PG_VER
  PG_VER="$(pg_lsclusters 2>/dev/null | awk 'NR>1 && $1 ~ /^[0-9]+$/ { print $1; exit }')"
  [ -z "$PG_VER" ] && PG_VER="$(psql --version 2>/dev/null | sed -n 's/.* \([0-9][0-9]*\)\.[0-9].*/\1/p' | head -1)"
  [ -z "$PG_VER" ] && { warn "无法检测 PG 主版本，见 install/pgvector.md"; return 0; }
  apt-get install -y "postgresql-${PG_VER}-pgvector" 2>/dev/null || warn "未找到 postgresql-${PG_VER}-pgvector"
  sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='ly_next'" 2>/dev/null | grep -q 1 \
    || sudo -u postgres createdb ly_next 2>/dev/null || true
  sudo -u postgres psql -d ly_next -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null \
    && ok "已启用 vector 扩展" || warn "CREATE EXTENSION 失败"
}

_ubuntu_redis_password_hint() {
  command -v redis-cli >/dev/null 2>&1 || return 0
  local rp
  rp="$(redis-cli CONFIG GET requirepass 2>/dev/null | tail -n1 | tr -d '\r')"
  [ -n "$rp" ] && [ "$rp" != "(nil)" ] && info "Redis 有密码；LY-NEXT 首次启动会尝试同步到 config"
}

install_redis_linux() {
  case "$(detect_linux_id)" in
    ubuntu|debian) apt-get update -y; apt-get install -y redis-server; systemctl enable --now redis-server || true; _ubuntu_redis_password_hint ;;
    fedora) dnf install -y redis; systemctl enable --now redis || true ;;
    rhel|centos|rocky|almalinux|ol) yum install -y redis; systemctl enable --now redis || true ;;
    arch|manjaro) pacman -Sy --noconfirm --needed redis; systemctl enable --now redis || true ;;
    opensuse*|sles) zypper install -y -n redis; systemctl enable --now redis || true ;;
    *) err "不支持的发行版"; exit 1 ;;
  esac
}

install_postgresql_linux() {
  case "$(detect_linux_id)" in
    ubuntu|debian) apt-get update -y; apt-get install -y postgresql postgresql-contrib; systemctl enable --now postgresql || true ;;
    fedora) dnf install -y postgresql-server postgresql-contrib; systemctl enable --now postgresql || true ;;
    rhel|centos|rocky|almalinux|ol) yum install -y postgresql-server postgresql-contrib; postgresql-setup --initdb || true; systemctl enable --now postgresql || true ;;
    arch|manjaro) pacman -Sy --noconfirm --needed postgresql; systemctl enable --now postgresql || true ;;
    opensuse*|sles) zypper install -y -n postgresql postgresql-server; systemctl enable --now postgresql || true ;;
    *) err "不支持的发行版"; exit 1 ;;
  esac
}

install_redis_macos() {
  command -v brew >/dev/null 2>&1 || { err "需要 Homebrew"; exit 1; }
  brew install redis; brew services start redis || true
}

install_postgresql_macos() {
  command -v brew >/dev/null 2>&1 || { err "需要 Homebrew"; exit 1; }
  brew install postgresql@17; brew services start postgresql@17 || true
}

should_install() {
  [ "$FORCE" -eq 1 ] && return 0
  ly_component_ok "$1" && { info "跳过 $1（已就绪）"; return 1; }
  return 0
}

main_menu() {
  local missing="" m
  missing="$(ly_missing_list | tr '\n' ' ')"
  echo "请选择操作:"
  if [ -n "$missing" ]; then
    echo "  1) 安装所有缺失项（推荐） — ${missing% }"
  else
    echo "  1) 所有依赖已就绪"
  fi
  echo "  2) 自定义选择要安装的组件"
  echo "  3) 仅检测，退出"
  echo "  0) 退出"
  read -r -p "输入选项 [1]: " choice
  choice="${choice:-1}"
  case "$choice" in
    1)
      if [ -z "$missing" ]; then return 1; fi
      for m in $missing; do
        case "$m" in redis) INSTALL_REDIS=1 ;; postgresql) INSTALL_POSTGRESQL=1 ;; pgvector) INSTALL_PGVECTOR=1 ;; esac
      done
      ;;
    2) custom_menu ;;
    3|0) return 1 ;;
    *) warn "无效输入，使用推荐项"; main_menu ;;
  esac
}

custom_menu() {
  local st1 st2 st3 choice part
  ly_component_ok redis && st1="[已安装]" || st1="[未安装]"
  ly_component_ok postgresql && st2="[已安装]" || st2="[未安装]"
  ly_component_ok pgvector && st3="[已安装]" || st3="[未安装]"
  echo ""
  echo "勾选要安装/配置的项:"
  echo "  1) Redis         $st1"
  echo "  2) PostgreSQL    $st2"
  echo "  3) pgvector      $st3"
  read -r -p "输入编号，逗号分隔（回车=取消）: " choice
  [ -z "$choice" ] && return 1
  INSTALL_REDIS=0; INSTALL_POSTGRESQL=0; INSTALL_PGVECTOR=0
  for part in $(echo "$choice" | tr ',' ' '); do
    case "$part" in
      1) INSTALL_REDIS=1 ;;
      2) INSTALL_POSTGRESQL=1 ;;
      3) INSTALL_PGVECTOR=1 ;;
    esac
  done
}

resolve_plan() {
  if [ "$INSTALL_ALL" -eq 1 ]; then
    INSTALL_REDIS=1
    INSTALL_POSTGRESQL=1
    INSTALL_PGVECTOR=1
    return
  fi
  if [ "$INSTALL_REDIS" -eq 1 ] || [ "$INSTALL_POSTGRESQL" -eq 1 ] || [ "$INSTALL_PGVECTOR" -eq 1 ]; then
    return
  fi
  if [ "$YES" -eq 1 ]; then
    local m
    for m in $(ly_missing_list); do
      case "$m" in
        redis) INSTALL_REDIS=1 ;;
        postgresql) INSTALL_POSTGRESQL=1 ;;
        pgvector) INSTALL_PGVECTOR=1 ;;
      esac
    done
    return
  fi
  main_menu || return 1
}

_ensure_postgres_password() {
  command -v psql >/dev/null 2>&1 || return 0
  local pw="${LY_NEXT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-postgres}}"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER USER postgres PASSWORD '${pw//\'/\'\'}';" \
    2>/dev/null || true
}

_run_configure_local() {
  local pw rp patch
  pw="${LY_NEXT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-postgres}}"
  rp=""
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli ping 2>/dev/null | grep -q PONG || true
    rp="$(redis-cli CONFIG GET requirepass 2>/dev/null | tail -n1 | tr -d '\r')"
    [ "$rp" = "(nil)" ] && rp=""
  fi
  patch="$(LY_PG_PW="$pw" LY_REDIS_PW="$rp" python3 - <<'PY'
import json, os
print(json.dumps({
    "database": {
        "host": "127.0.0.1",
        "port": 5432,
        "username": "postgres",
        "password": os.environ.get("LY_PG_PW", "postgres"),
        "database": "ly_next",
        "try_unix_socket": False,
    },
    "redis": {
        "host": "127.0.0.1",
        "port": 6379,
        "password": os.environ.get("LY_REDIS_PW", ""),
        "db": 0,
    },
}))
PY
)"

  cd "$REPO_ROOT" || exit 1
  if command -v uv >/dev/null 2>&1; then
    uv run python install/configure_local.py --repo-root "$REPO_ROOT" --patch-json "$patch"
  else
    python3 install/configure_local.py --repo-root "$REPO_ROOT" --patch-json "$patch"
  fi
}

finalize_postgres_stack() {
  command -v psql >/dev/null 2>&1 || return 0
  _ensure_postgres_password
  export PGPASSWORD="${LY_NEXT_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-postgres}}"
  psql -U postgres -h 127.0.0.1 -tAc "SELECT 1" 2>/dev/null | grep -q 1 \
    || psql -U postgres -tAc "SELECT 1" 2>/dev/null | grep -q 1 || {
    warn "PostgreSQL 未响应，跳过建库/pgvector"
    return 0
  }
  psql -U postgres -h 127.0.0.1 -tc "SELECT 1 FROM pg_database WHERE datname='ly_next'" 2>/dev/null | grep -q 1 \
    || psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='ly_next'" 2>/dev/null | grep -q 1 \
    || sudo -u postgres createdb ly_next 2>/dev/null || warn "创建 ly_next 失败"
  ly_component_ok pgvector && return 0
  case "$(detect_linux_id)" in
    ubuntu|debian) _ubuntu_setup_pgvector ;;
    *) warn "pgvector 自动安装仅支持 Ubuntu/Debian，见 install/pgvector.md" ;;
  esac
}

ly_configure_local() {
  info "写入 data/ly_next/config.yaml ..."
  _ensure_postgres_password
  _run_configure_local || warn "写入配置失败（需要 uv 或 python3+pyyaml）"
  finalize_postgres_stack
  ok "本地配置已更新，可运行: uv run ly"
}

run_install() {
  case "$(uname -s)" in
    Linux)
      need_root
      if [ "$INSTALL_REDIS" -eq 1 ] && should_install redis; then
        info "安装 Redis"
        install_redis_linux
      fi
      if [ "$INSTALL_POSTGRESQL" -eq 1 ] && should_install postgresql; then
        info "安装 PostgreSQL"
        install_postgresql_linux
      fi
      ;;
    Darwin)
      if [ "$INSTALL_REDIS" -eq 1 ] && should_install redis; then
        info "安装 Redis"
        install_redis_macos
      fi
      if [ "$INSTALL_POSTGRESQL" -eq 1 ] && should_install postgresql; then
        info "安装 PostgreSQL"
        install_postgresql_macos
      fi
      if [ "$INSTALL_PGVECTOR" -eq 1 ] || [ "$INSTALL_ALL" -eq 1 ]; then
        warn "macOS 请按 install/pgvector.md 手动安装 pgvector"
      fi
      ;;
    *)
      err "Windows 请运行: powershell -File install/install.ps1"
      exit 1
      ;;
  esac
}

echo ""
echo "LY-NEXT 依赖安装向导"
ly_show_status

[ "$DETECT_ONLY" -eq 1 ] && { ok "检测完成。"; exit 0; }

if [ "$CONFIGURE_ONLY" -eq 1 ]; then
  need_root
  ly_configure_local
  ly_show_status
  exit 0
fi

resolve_plan || { ok "已退出。"; exit 0; }

if [ "$INSTALL_REDIS" -eq 0 ] && [ "$INSTALL_POSTGRESQL" -eq 0 ] && [ "$INSTALL_PGVECTOR" -eq 0 ]; then
  ok "未选择安装项。"
  exit 0
fi

run_install

if [ "$INSTALL_REDIS" -eq 1 ] || [ "$INSTALL_POSTGRESQL" -eq 1 ] || [ "$INSTALL_PGVECTOR" -eq 1 ] \
  || [ "$INSTALL_ALL" -eq 1 ] || [ "$YES" -eq 1 ] || [ "$CONFIGURE_ONLY" -eq 1 ]; then
  ly_configure_local
fi

ly_show_status
ok "完成。启动: uv run ly"
