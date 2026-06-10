"""Security posture checks for the workbench security panel."""

from __future__ import annotations

from typing import Any

from ly_next.core.audit_log import audit_enabled
from ly_next.core.auth_gate import auth_mode, rbac_enabled
from ly_next.core.auth_jwt import jwt_enabled, jwt_secret_configured
from ly_next.core.auth_users import users_configured, users_with_plaintext_password
from ly_next.core.config import UNSAFE_DOCS_WHITELIST, config

_WEAK_KEY_SAMPLES = frozenset({"changeme", "password", "12345678", "test", "secret"})
_SAFE_SECURITY_PROFILES = frozenset({"production", "verified"})


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
    api_profile = (
        str(config.get("api.security_profile", "development") or "development").strip().lower()
    )
    plugin_profile = (
        str(
            config.get("plugins.security_profile")
            or config.get("api.security_profile", "development")
            or "development"
        )
        .strip()
        .lower()
    )
    tools_profile = (
        str(config.get("tools.security_profile") or plugin_profile or "development").strip().lower()
    )
    host_enabled = bool((config.get("tools.host") or {}).get("enabled", False))
    host_exec = bool(((config.get("tools.host") or {}).get("exec") or {}).get("enabled", False))
    built_in = config.get("tools.built_in") or []
    built_in_names = {str(x) for x in built_in} if isinstance(built_in, list) else set()
    policy = config.get("agent.tool_policy") or {}
    deny_raw = policy.get("deny_tools") if isinstance(policy, dict) else []
    deny_names = (
        {str(x) for x in deny_raw if str(x).strip()} if isinstance(deny_raw, list) else set()
    )
    security = config.get("security") or {}
    headers_cfg = security.get("headers") if isinstance(security, dict) else {}
    rate_cfg = security.get("rate_limit") if isinstance(security, dict) else {}
    headers_enabled = bool((headers_cfg or {}).get("enabled", True))
    trust_proxy = bool((rate_cfg or {}).get("trust_proxy_headers", False))
    agent_policy = security.get("agent_policy") if isinstance(security, dict) else {}
    agent_policy_enabled = bool((agent_policy or {}).get("enabled", True))
    host_exec_cfg = (
        ((config.get("tools.host") or {}).get("exec") or {})
        if isinstance(config.get("tools.host"), dict)
        else {}
    )
    host_minimal_env = bool(host_exec_cfg.get("minimal_env", True))
    host_hard_blocks = host_exec_cfg.get("hard_block_patterns")
    has_custom_hard_blocks = isinstance(host_hard_blocks, list) and len(host_hard_blocks) > 0

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

    docs_wl = [
        str(r)
        for r in (whitelist if isinstance(whitelist, list) else [])
        if str(r).strip() in UNSAFE_DOCS_WHITELIST
    ]
    checks.append(
        _check(
            "docs_whitelist",
            ok=not docs_wl,
            label="OpenAPI 文档免鉴权",
            hint=None
            if not docs_wl
            else f"生产环境不应放行：{', '.join(docs_wl)}；请从 auth.whitelist 移除",
        )
    )

    checks.append(
        _check(
            "api_security_profile",
            ok=api_profile in _SAFE_SECURITY_PROFILES,
            label="动态 API 安全档位",
            hint=None
            if api_profile in _SAFE_SECURITY_PROFILES
            else f"api.security_profile={api_profile}；生产请设为 production 或 verified",
        )
    )
    checks.append(
        _check(
            "plugins_security_profile",
            ok=plugin_profile in _SAFE_SECURITY_PROFILES,
            label="插件安全档位",
            hint=None
            if plugin_profile in _SAFE_SECURITY_PROFILES
            else f"plugins.security_profile={plugin_profile}；生产请设为 production 或 verified",
        )
    )
    try:
        from ly_next.core.plugin.loader import directory_plugin_load_status

        plugin_dir_status = directory_plugin_load_status()
        if plugin_dir_status.get("blocked"):
            checks.append(
                _check(
                    "plugins_directory_blocked",
                    ok=False,
                    label="plugins/local 目录插件",
                    hint=str(plugin_dir_status.get("hint") or "目录插件被安全档位拦截"),
                    severity="critical",
                )
            )
    except Exception:
        pass
    checks.append(
        _check(
            "tools_security_profile",
            ok=tools_profile in _SAFE_SECURITY_PROFILES,
            label="工具目录安全档位",
            hint=None
            if tools_profile in _SAFE_SECURITY_PROFILES
            else f"tools.security_profile={tools_profile}；生产请设为 production 或 verified",
        )
    )

    host_risk = host_enabled and host_exec
    checks.append(
        _check(
            "host_tools",
            ok=not host_risk,
            label="本机 Host 工具",
            hint=None
            if not host_risk
            else (
                "tools.host.enabled 与 exec.enabled 均为 true，模型可执行 shell；"
                "公网请关闭 host 或至少关闭 exec"
            ),
            severity="critical" if host_risk else "ok",
        )
    )
    if host_enabled and not host_exec:
        checks.append(
            _check(
                "host_tools_partial",
                ok=True,
                label="Host Shell 已关闭",
                hint="tools.host.enabled 为 true 但 exec 已关闭，仅保留文件类工具",
                severity="info",
            )
        )

    checks.append(
        _check(
            "web_scrape_builtin",
            ok="web_scrape" not in built_in_names,
            label="web_scrape 内置工具",
            hint=None
            if "web_scrape" not in built_in_names
            else "tools.built_in 含 web_scrape；建议移除并改用 web_fetch",
        )
    )
    checks.append(
        _check(
            "web_scrape_denied",
            ok="web_scrape" in deny_names,
            label="web_scrape 工具策略",
            hint=None
            if "web_scrape" in deny_names
            else "agent.tool_policy.deny_tools 应包含 web_scrape（默认配置勿重复定义 deny_tools）",
        )
    )

    checks.append(
        _check(
            "security_headers",
            ok=headers_enabled,
            label="安全响应头",
            hint=None if headers_enabled else "建议开启 security.headers.enabled",
        )
    )
    if trust_proxy:
        checks.append(
            _check(
                "trust_proxy_headers",
                ok=True,
                label="限流信任代理头",
                hint="trust_proxy_headers 已开启；请确保仅可信反代可设置 X-Forwarded-For",
                severity="info",
            )
        )
    elif public_bind:
        checks.append(
            _check(
                "reverse_proxy_tls",
                ok=False,
                label="反向代理 / TLS",
                hint="对外暴露时建议在 Nginx/Caddy 后终止 TLS，并视情况开启 auth.cookie_secure",
            )
        )

    checks.append(
        _check(
            "audit_log",
            ok=audit_enabled(),
            label="安全审计日志",
            hint=None if audit_enabled() else "建议开启 security.audit.enabled 记录工具调用",
        )
    )

    checks.append(
        _check(
            "agent_content_policy",
            ok=agent_policy_enabled,
            label="Agent 内容信任策略",
            hint=None
            if agent_policy_enabled
            else "建议开启 security.agent_policy.enabled，限制不可信上下文调用 Host 工具",
        )
    )

    if host_enabled and host_exec:
        checks.append(
            _check(
                "host_exec_minimal_env",
                ok=host_minimal_env,
                label="Host Shell 最小环境",
                hint=None
                if host_minimal_env
                else "tools.host.exec.minimal_env 为 false；子进程将继承完整环境变量",
            )
        )
        checks.append(
            _check(
                "host_exec_hard_blocks",
                ok=True,
                label="Host Shell 硬拦截",
                hint="内置危险命令模式拦截已启用"
                if not has_custom_hard_blocks
                else "已配置自定义 hard_block_patterns；请确认规则不会误拦合法命令",
                severity="info" if has_custom_hard_blocks else "ok",
            )
        )

    mode = auth_mode()
    users_ok = users_configured()
    if mode in ("jwt", "hybrid"):
        checks.append(
            _check(
                "auth_users",
                ok=users_ok,
                label="JWT 用户配置",
                hint=None if users_ok else "auth.mode 为 jwt/hybrid 时需配置 auth.users",
                severity="critical" if not users_ok else "ok",
            )
        )
        checks.append(
            _check(
                "jwt_enabled",
                ok=jwt_enabled(),
                label="JWT 登录",
                hint=None
                if jwt_enabled()
                else "请配置 auth.users 并设置 auth.jwt.enabled（hybrid/jwt 模式）",
            )
        )
        if jwt_enabled() and not jwt_secret_configured():
            checks.append(
                _check(
                    "jwt_secret_env",
                    ok=False,
                    label="JWT 密钥",
                    hint="未设置 auth.jwt.secret / LY_NEXT_JWT_SECRET；多实例部署会各自生成不同密钥",
                )
            )
        plaintext_users = users_with_plaintext_password()
        if plaintext_users:
            checks.append(
                _check(
                    "auth_plaintext_password",
                    ok=False,
                    label="用户明文密码",
                    hint=f"auth.users 含明文 password 字段：{', '.join(plaintext_users)}；"
                    "请改用 password_hash 并删除明文",
                )
            )
    if rbac_enabled():
        checks.append(
            _check(
                "rbac",
                ok=True,
                label="RBAC 已启用",
                hint="多用户模式已启用角色权限（viewer/operator/admin）",
                severity="info",
            )
        )
    elif mode == "jwt":
        checks.append(
            _check(
                "rbac",
                ok=False,
                label="RBAC",
                hint="auth.mode=jwt 但未配置用户，无法启用 RBAC",
                severity="critical",
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
