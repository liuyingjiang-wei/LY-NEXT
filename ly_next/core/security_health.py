"""Security posture checks for the workbench security panel."""

from __future__ import annotations

from typing import Any

from ly_next.core.config import config

_WEAK_KEY_SAMPLES = frozenset({"changeme", "password", "12345678", "test", "secret"})


def _check(
    check_id: str,
    *,
    ok: bool,
    label: str,
    hint: str | None = None,
    severity: str = "warn",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "ok": ok,
        "label": label,
        "hint": hint,
        "severity": severity if not ok else "ok",
    }


def gather_security_health() -> dict[str, Any]:
    auth_enabled = bool(config.get("auth.enabled", True))
    api_key = str(config.get("auth.api_key") or "").strip()
    allow_query = bool(config.get("auth.allow_api_key_in_query", False))
    cookie_secure = bool(config.get("auth.cookie_secure", False))
    host = str(config.get("server.host", "0.0.0.0") or "0.0.0.0").strip()
    cors_origins = config.get("cors.origins") or []
    whitelist = config.get("auth.whitelist") or []
    store_prompts = bool((config.get("agent.observability") or {}).get("store_prompts", False))

    checks: list[dict[str, Any]] = []

    if auth_enabled:
        checks.append(
            _check(
                "auth_enabled",
                ok=True,
                label="服务鉴权已开启",
                hint=None,
            )
        )
        key_ok = bool(api_key)
        weak = api_key.lower() in _WEAK_KEY_SAMPLES or (len(api_key) > 0 and len(api_key) < 16)
        checks.append(
            _check(
                "api_key_set",
                ok=key_ok and not weak,
                label="API 密钥强度",
                hint=None
                if key_ok and not weak
                else (
                    "请设置至少 16 位的随机 API 密钥"
                    if not key_ok
                    else "当前密钥过短或为常见弱口令，建议更换"
                ),
            )
        )
    else:
        checks.append(
            _check(
                "auth_enabled",
                ok=False,
                label="服务鉴权已关闭",
                hint="生产环境应开启 auth.enabled 并配置 api_key",
                severity="critical",
            )
        )

    checks.append(
        _check(
            "query_api_key",
            ok=not allow_query,
            label="禁止 URL 传参 api_key",
            hint=None
            if not allow_query
            else "auth.allow_api_key_in_query 为 true，密钥可能出现在访问日志中",
        )
    )

    public_bind = host in ("0.0.0.0", "::")
    checks.append(
        _check(
            "bind_address",
            ok=not public_bind or auth_enabled,
            label="监听地址",
            hint=None
            if not public_bind
            else f"server.host={host} 对外暴露；请确认防火墙与反向代理，并启用鉴权",
        )
    )

    if public_bind and not cookie_secure:
        checks.append(
            _check(
                "cookie_secure",
                ok=False,
                label="HTTPS Cookie",
                hint="对外服务时建议开启 auth.cookie_secure，并通过 HTTPS 访问工作台",
            )
        )
    else:
        checks.append(
            _check(
                "cookie_secure",
                ok=True,
                label="HTTPS Cookie",
                hint="已启用 cookie_secure" if cookie_secure else "仅本机访问时可保持关闭",
            )
        )

    cors_wildcard = isinstance(cors_origins, list) and "*" in cors_origins
    checks.append(
        _check(
            "cors_origins",
            ok=not cors_wildcard,
            label="CORS 来源",
            hint=None
            if not cors_wildcard
            else "cors.origins 含 *，浏览器跨域站点可携带凭据发起请求",
        )
    )

    risky_wl = [
        str(r)
        for r in (whitelist if isinstance(whitelist, list) else [])
        if str(r).strip() in ("/*", "*", "/api/*")
    ]
    checks.append(
        _check(
            "auth_whitelist",
            ok=not risky_wl,
            label="鉴权白名单",
            hint=None if not risky_wl else f"白名单过宽：{', '.join(risky_wl)}，可能绕过 API 密钥",
        )
    )

    checks.append(
        _check(
            "store_prompts",
            ok=not store_prompts,
            label="Run 存 Prompt 全文",
            hint="store_prompts 已关闭（推荐）"
            if not store_prompts
            else "agent.observability.store_prompts 已开启，Run 事件可能含对话全文",
            severity="info" if store_prompts else "ok",
        )
    )

    suggestions: list[str] = []
    for c in checks:
        if not c["ok"] and c.get("hint") and c.get("severity") != "info":
            suggestions.append(str(c["hint"]))

    critical = [c for c in checks if not c["ok"] and c.get("severity") == "critical"]
    all_ok = not any(not c["ok"] and c.get("severity") not in ("info", "ok") for c in checks)

    return {
        "checks": checks,
        "suggestions": suggestions,
        "all_ok": all_ok,
        "critical_count": len(critical),
    }
