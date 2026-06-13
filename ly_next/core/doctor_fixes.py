"""Safe one-click fixes exposed to the workbench doctor panel."""

from __future__ import annotations

from typing import Any

from ly_next.core.config import config

DOCTOR_FIX_CATALOG: list[dict[str, str]] = [
    {
        "id": "sync_auth_key",
        "label": "同步 FIRST_RUN.txt 与 config.yaml 登录密钥",
        "detail": "将 auth.api_key 写回 data 目录下的 FIRST_RUN.txt",
    },
    {
        "id": "disable_query_api_key",
        "label": "禁止 URL 传参 api_key",
        "detail": "设置 auth.allow_api_key_in_query = false",
    },
    {
        "id": "enable_cookie_secure",
        "label": "启用 Cookie Secure",
        "detail": "设置 auth.cookie_secure = true（HTTPS 部署推荐）",
    },
    {
        "id": "run_config_migrate",
        "label": "迁移 legacy LLM 配置块",
        "detail": "合并 *_llm 到 llm.models 并修正 compat Base URL",
    },
]


def list_doctor_fixes() -> list[dict[str, str]]:
    return [dict(x) for x in DOCTOR_FIX_CATALOG]


def apply_doctor_fix(fix_id: str) -> dict[str, Any]:
    fid = str(fix_id or "").strip()
    if fid == "sync_auth_key":
        from ly_next.core.first_run import sync_first_run_notice

        changed = sync_first_run_notice(str(config.get("auth.api_key") or ""))
        return {"ok": True, "fix_id": fid, "changed": changed, "message": "已同步 FIRST_RUN.txt"}

    if fid == "disable_query_api_key":
        if not config.get("auth.allow_api_key_in_query", False):
            return {"ok": True, "fix_id": fid, "changed": False, "message": "已是禁止 URL 传参"}
        config.set("auth.allow_api_key_in_query", False, save=True)
        config.load()
        return {"ok": True, "fix_id": fid, "changed": True, "message": "已关闭 URL 传参 api_key"}

    if fid == "enable_cookie_secure":
        if config.get("auth.cookie_secure", False):
            return {"ok": True, "fix_id": fid, "changed": False, "message": "Cookie Secure 已开启"}
        config.set("auth.cookie_secure", True, save=True)
        config.load()
        return {"ok": True, "fix_id": fid, "changed": True, "message": "已开启 auth.cookie_secure"}

    if fid == "run_config_migrate":
        from ly_next.core.config_migrate import run_config_migrate

        result = run_config_migrate(save=True, prune_legacy=True)
        changes = result.get("changes") or []
        return {
            "ok": True,
            "fix_id": fid,
            "changed": bool(changes),
            "message": "；".join(changes) if changes else "无需迁移",
            "migrate": result,
        }

    return {"ok": False, "fix_id": fid, "error": f"未知修复项: {fid}"}
