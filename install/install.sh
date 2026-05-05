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
