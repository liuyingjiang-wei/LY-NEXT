"""Shared helpers for onboarding UI, login hints, and dependency actions."""

from __future__ import annotations

from typing import Any

from ly_next.core.config import config, get_data_root, get_project_root
from ly_next.core.first_run import (
    first_run_notice_path,
    read_first_run_api_key,
    sync_first_run_notice,
)
from ly_next.core.system_readiness import mask_api_key


def gather_auth_key_status() -> dict[str, Any]:
    cfg_key = str(config.get("auth.api_key") or "").strip()
    file_key = read_first_run_api_key()
    path = first_run_notice_path()
    data_root = get_data_root()
    try:
        rel_first_run = str(path.relative_to(data_root.parent))
    except ValueError:
        rel_first_run = str(path.name)

    synced: bool | None
    if cfg_key and file_key:
        synced = file_key == cfg_key
    elif cfg_key and path.is_file():
        synced = False
    else:
        synced = None

    hint: str | None = None
    if not cfg_key:
        hint = "auth.api_key 未设置，重启服务后将自动生成"
    elif synced is False:
        hint = (
            "FIRST_RUN.txt 与 config.yaml 中的 API Key 不一致；"
            "请使用 config.yaml 中的密钥登录，或点击下方同步"
        )
    elif path.is_file():
        hint = f"登录密钥见 {rel_first_run} 或下方脱敏预览"
    else:
        hint = "重启服务后将写入 FIRST_RUN.txt"

    return {
        "configured": bool(cfg_key),
        "masked_key": mask_api_key(cfg_key),
        "first_run_path": rel_first_run.replace("\\", "/"),
        "first_run_exists": path.is_file(),
        "synced": synced,
        "hint": hint,
    }


def login_page_hints() -> dict[str, Any]:
    status = gather_auth_key_status()
    return {
        "api_key_configured": status["configured"],
        "masked_key": status["masked_key"],
        "first_run_path": status["first_run_path"],
        "first_run_exists": status["first_run_exists"],
        "key_synced": status["synced"],
        "hint": status["hint"],
        "docs_url": "https://github.com/liuyingjiang-wei/LY-NEXT#快速开始",
    }


def dependency_actions(*, db_connected: bool, redis_connected: bool) -> dict[str, Any]:
    root = get_project_root()
    compose = "docker compose -f docker/docker-compose.yml up -d"
    compose_pgvector = (
        "docker compose -f docker/docker-compose.yml -f docker/compose.pgvector.yml up -d"
    )
    return {
        "docker_compose_deps": compose,
        "docker_compose_pgvector": compose_pgvector,
        "install_linux": "bash install.sh",
        "install_windows": 'powershell -ExecutionPolicy Bypass -File ".\\install.ps1"',
        "project_root": str(root),
        "postgres_connected": db_connected,
        "redis_connected": redis_connected,
        "skip_persistence_note": (
            "不安装 PostgreSQL 时仍可对话；会话历史、Run 追踪与 RAG 向量检索会降级或不可用。"
        ),
        "copy_hint": "在仓库根目录执行下方命令，然后重启 LY-NEXT",
    }


def sync_auth_first_run_file() -> dict[str, Any]:
    key = str(config.get("auth.api_key") or "").strip()
    if not key:
        return {"ok": False, "error": "auth.api_key 未配置，无法同步"}
    changed = sync_first_run_notice(key)
    status = gather_auth_key_status()
    path = first_run_notice_path()
    return {
        "ok": True,
        "updated": changed,
        "synced": status.get("synced"),
        "first_run_path": status.get("first_run_path"),
        "path": str(path),
    }
