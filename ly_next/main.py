import asyncio
import os
import secrets
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import quote

# psycopg / LangGraph AsyncPostgresSaver 在 Windows 上需要 SelectorEventLoop，不能是默认的 ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from ly_next import __version__
from ly_next.api import api_router, mcp_router, ws_public_router
from ly_next.api.base import APIRegistry
from ly_next.api.mcp_api import get_mcp_mount_prefix
from ly_next.core.app_context import AppContext, set_app_context
from ly_next.core.auth_context import bind_principal, release_principal
from ly_next.core.auth_gate import authenticate_http, authorize_http, login_with_password
from ly_next.core.auth_jwt import issue_access_token, jwt_enabled
from ly_next.core.cache import cache
from ly_next.core.checkpointer import init_checkpointer, shutdown_checkpointer
from ly_next.core.config import config, get_project_root
from ly_next.core.database import db
from ly_next.core.first_run import sync_first_run_notice
from ly_next.core.logger import (
    get_uvicorn_log_config,
    print_startup_report,
    refresh_ly_next_log_level_from_config,
    setup_logging,
)
from ly_next.core.plugin import PluginLoader
from ly_next.core.security_headers import SecurityHeadersMiddleware
from ly_next.core.service_manager import (
    InstallStatus,
    ServiceInfo,
    ServiceStatus,
    get_service_manager,
)
from ly_next.core.startup_manager import get_startup_manager
from ly_next.core.task_manager import get_task_manager
from ly_next.mcp.remote_bridge import (
    load_remote_mcp_tools,
    remote_mcp_configured,
    remote_mcp_startup_load_enabled,
)

logger = setup_logging()


_LOGIN_BUILD_MISSING = (
    '<!doctype html><html lang="zh-CN"><meta charset="utf-8"/><title>登录</title>'
    '<body style="font-family:system-ui,sans-serif;padding:2rem;max-width:36rem">'
    "<p>未找到登录页静态文件 <code>www/login.html</code>。请使用仓库中已提交的 <code>www/</code>；"
    "若本地有 <code>.workbench-src/</code>，可在项目根目录执行 <code>pnpm install</code> 与 "
    "<code>pnpm run build:workbench</code> 生成。</p></body></html>"
)


async def _ensure_external_service(
    label: str,
    check: Callable[[], Awaitable[ServiceInfo]],
    ensure: Callable[[], Awaitable[ServiceInfo]],
    *,
    log_not_installed: bool = False,
) -> ServiceInfo:
    info = await check()
    if info.status == ServiceStatus.RUNNING:
        logger.debug(info.message)
        return info
    if info.status == ServiceStatus.STOPPED:
        logger.info("%s not running, attempting auto-start...", label)
        return await ensure()
    logger.warning("%s: %s", label, info.message)
    if info.install_status == InstallStatus.NOT_INSTALLED:
        if log_not_installed:
            logger.info("%s not installed, attempting auto-install...", label)
    elif info.status != ServiceStatus.RUNNING:
        logger.info("%s is installed but not reachable, attempting to start...", label)
    return await ensure()


def _auth_exempt_path(path: str, *, ws_paths: tuple[str, ...] = ()) -> bool:
    if path.startswith("/ly/static/"):
        return True
    if ws_paths and path in ws_paths:
        return True
    try:
        from qq_onebot.bridge.paths import is_onebot11_ws_path

        if is_onebot11_ws_path(path):
            return True
    except ImportError:
        if path in ("/OneBotv11", "/onebot/v11/ws") or path.startswith("/onebot/"):
            return True
    return path in (
        "/",
        "/firefly",
        "/ly/login",
        "/ly/login/",
        "/api/ws",
        "/.well-known/appspecific/com.chrome.devtools.json",
    )


def _ly_console_path(path: str) -> bool:
    if path.startswith("/ly/static/"):
        return False
    if path in ("/ly/login", "/ly/login/"):
        return False
    if path == "/ly/app" or path.startswith("/ly/app/"):
        return True
    return path == "/ly" or path.startswith("/ly/")


def _safe_ly_next_path(path: str) -> str:
    """登录成功后仅允许跳回工作台路径，避免开放重定向。"""
    p = (path or "").strip()
    if not p.startswith("/") or p.startswith("//") or "\\" in p:
        return "/ly/"
    if "\0" in p or "@" in p:
        return "/ly/"
    if p in ("/ly/login", "/ly/login/"):
        return "/ly/"
    if p.startswith("/ly/static/"):
        return "/ly/"
    if not _ly_console_path(p):
        return "/ly/"
    return p


def _login_redirect_url(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return f"/ly/login?next={quote(target, safe='/?=&')}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    started_at = time.perf_counter()

    refresh_ly_next_log_level_from_config()

    cfg_init = config.ensure_initialized()
    if cfg_init.get("created"):
        logger.info("已创建用户配置文件: %s", cfg_init.get("path"))
    elif not cfg_init.get("exists"):
        logger.warning("配置文件不可用: %s", cfg_init.get("path"))
    elif not cfg_init.get("parent_writable"):
        logger.warning("配置目录可能不可写: %s", cfg_init.get("path"))

    from ly_next.models.migrate import ensure_llm_models_migrated
    from ly_next.models.registry import ModelRegistry

    if ensure_llm_models_migrated(save=True):
        logger.info("Legacy LLM blocks migrated into llm.models registry")
    ModelRegistry.ensure_loaded()

    startup_mgr = get_startup_manager()
    await startup_mgr.run_first_time_setup()

    if startup_mgr._is_first_run:
        sys_info = startup_mgr.get_system_info()
        logger.debug(f"System info: {sys_info}")

    service_mgr = get_service_manager()
    logger.info("Checking external services...")

    if startup_mgr._is_first_run:
        logger.info("First run detected, auto-configuring services...")
        await service_mgr.auto_configure_services()

    redis_info = await _ensure_external_service(
        "Redis",
        service_mgr.check_redis,
        service_mgr.ensure_redis,
    )
    postgres_info = await _ensure_external_service(
        "PostgreSQL",
        service_mgr.check_postgres,
        service_mgr.ensure_postgres,
        log_not_installed=True,
    )

    from ly_next.core.postgres_port import sync_database_port_from_install

    sync_database_port_from_install()

    try:
        await db.connect()
        logger.info("Database connected")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        if service_mgr._is_production:
            raise
        logger.warning("Continuing without database - some features may not work")

    app.state.redis_available = False
    try:
        await cache.connect()
        app.state.redis_available = True
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        logger.info("Continuing without Redis - caching features disabled")

    if db._engine is not None:
        try:
            await db.create_tables()
        except Exception as e:
            logger.error("Database schema setup failed: %s", e)
            if service_mgr._is_production:
                raise
            logger.warning(
                "Continuing without full DB schema — task/run persistence may be limited"
            )
        else:
            try:
                await init_checkpointer()
            except Exception as e:
                logger.warning("LangGraph checkpointer init skipped: %s", e)

    ctx = AppContext.create()
    set_app_context(ctx)
    app.state.app_context = ctx

    api_registry = APIRegistry()
    plugin_loader = PluginLoader()
    plugin_registry = plugin_loader.load_all(ctx, api_registry=api_registry)
    app.state.plugin_registry = plugin_registry

    n_bi = ctx.extras.get("builtin_tools_registered", 0)
    registry = ctx.tool_registry
    logger.debug("Registered %s built-in tools (%s total in registry)", n_bi, len(registry))

    try:
        if remote_mcp_startup_load_enabled():
            await load_remote_mcp_tools()
        elif remote_mcp_configured():
            logger.info(
                "远程 MCP 已启用，将在首次对话时连接（tools.mcp.load_remote_on_startup=false，"
                "避免每次重启触发 npx/uvx 下载）"
            )
    except Exception as e:
        logger.warning("Remote MCP init: %s", e)

    await api_registry.startup(app)
    await plugin_registry.startup(app, ctx)
    app.state.api_registry = api_registry
    logger.debug(
        "Loaded %s APIs, %s plugins",
        len(api_registry.list_apis()),
        len(plugin_registry.list_plugins()),
    )

    host = config.get("server.host", "0.0.0.0")
    port = config.get("server.port", 8000)
    startup_ms = int((time.perf_counter() - started_at) * 1000)
    app.state._startup_ms = startup_ms

    http_routes = 0
    ws_routes = 0
    ws_paths: list[str] = []
    for r in app.router.routes:
        if isinstance(r, APIRoute):
            http_routes += 1
        elif isinstance(r, APIWebSocketRoute):
            ws_routes += 1
            p = getattr(r, "path", None)
            if p:
                ws_paths.append(p)

    mem_str = "--"
    cpu_str = "--"
    try:
        import psutil  # type: ignore

        p = psutil.Process()
        mem_mb = p.memory_info().rss / (1024 * 1024)
        mem_str = f"{mem_mb:.2f}MB"
        cpu_str = f"{psutil.cpu_count(logical=True)}核"
    except Exception:
        pass

    auth_key = config.get("auth.api_key", "")
    wl = config.get("auth.whitelist", []) or []
    header_name = config.get("auth.header_name", "X-API-Key")

    ws_host = "localhost" if host in ("0.0.0.0", "::") else host
    onebot_paths = getattr(app.state, "onebot11_ws_paths", None) or []
    if onebot_paths:
        ws_service_line = f"ws://{ws_host}:{port}{onebot_paths[0]} (NapCat OneBot11)"
    else:
        ws_service_line = f"ws://{ws_host}:{port}/api/ws (workbench chat)"
    report = {
        "title": "运行快照",
        "startup_ms": startup_ms,
        "started_at": time.strftime("%Y/%m/%d %H:%M:%S"),
        "version": __version__,
        "server_url": f"http://{host}:{port}",
        "docs_url": f"http://{host}:{port}/docs",
        "workbench_url": f"http://{host}:{port}/ly/",
        "workbench_home_url": f"http://{host}:{port}/",
        "workbench_login_url": f"http://{host}:{port}/ly/login",
        "ws": {
            "url": f"ws://{host}:{port}",
            "paths": f"{len(ws_paths)}个 [{', '.join(ws_paths) if ws_paths else ''}]",
            "service_line": ws_service_line,
        },
        "perf": {
            "mem": mem_str,
            "cpu": cpu_str,
            "platform": f"{__import__('platform').system().lower()} {__import__('platform').machine().lower()}",
            "python": __import__("sys").version.split()[0],
        },
        "api": {
            "modules": str(len(api_registry.list_apis())),
            "http_routes": str(http_routes),
            "ws_routes": str(ws_routes),
        },
        "auth": {"api_key": auth_key, "header": header_name, "whitelist": wl},
        "services": {
            "PostgreSQL": postgres_info.status == ServiceStatus.RUNNING,
            "Redis": redis_info.status == ServiceStatus.RUNNING,
        },
    }
    if config.get("bridge.onebot11.enabled", False):
        if onebot_paths:
            logger.info(
                "OneBot11 reverse WS listening (NapCat WebSocket client): %s",
                ", ".join(onebot_paths),
            )
        else:
            logger.warning(
                "bridge.onebot11.enabled is true but no WS paths registered; "
                "install plugins/local/qq_onebot and restart (see plugins/README.md)"
            )

    plugin_names = {p.name for p in plugin_registry.list_plugins()}
    if config.get("bridge.telegram.enabled", False):
        tg_token = str(
            config.get("bridge.telegram.bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
        ).strip()
        if "telegram-bot" not in plugin_names:
            logger.warning(
                "bridge.telegram.enabled is true but telegram-bot plugin not loaded; "
                "install plugins/local/telegram_bot (see plugins/README.md)"
            )
        elif not tg_token:
            logger.warning(
                "bridge.telegram.enabled is true but bot_token missing; "
                "set TELEGRAM_BOT_TOKEN or bridge.telegram.bot_token"
            )
        else:
            logger.info("Telegram bridge enabled (plugin telegram-bot, long polling, pairing)")

    if config.get("bridge.wechat_oc.enabled", False):
        if "wechat-oc" not in plugin_names:
            logger.warning(
                "bridge.wechat_oc.enabled is true but wechat-oc plugin not loaded; "
                "install wechat_oc (see plugins/README.md)"
            )
        else:
            logger.info("WeChat OC bridge enabled (plugin wechat-oc, QR login, private chat only)")

    await print_startup_report(report)

    logger.info(f"LY-Next v{__version__} started successfully")

    yield

    logger.info("Shutting down LY-Next...")
    plugin_reg = getattr(app.state, "plugin_registry", None)
    app_ctx = getattr(app.state, "app_context", None)
    if plugin_reg is not None and app_ctx is not None:
        await plugin_reg.shutdown(app, app_ctx)
    api_reg = getattr(plugin_reg, "api_registry", None) if plugin_reg else None
    if api_reg is not None:
        await api_reg.shutdown(app)

    with suppress(Exception):
        await shutdown_checkpointer()

    with suppress(Exception):
        await db.disconnect()
    with suppress(Exception):
        await cache.disconnect()

    await get_service_manager().shutdown_managed_services()

    task_manager = get_task_manager()
    cleared_count = await task_manager.clear_completed()
    logger.info(f"Cleared {cleared_count} completed tasks")

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="LY-Next",
        description="FastAPI + LangGraph Agent Framework with MCP support",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get("cors.origins")
        or ["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if config.get("security.headers.enabled", True):
        app.add_middleware(SecurityHeadersMiddleware)

    from ly_next.core.plugin.early_bridges import (
        bootstrap_message_bridges,
    )

    _bridge_reg, bridge_ws_paths = bootstrap_message_bridges(ws_public_router, app)
    app.state.bridge_ws_paths = bridge_ws_paths
    app.state.onebot11_ws_paths = bridge_ws_paths

    app.include_router(api_router)
    if config.get("tools.mcp.enabled", True):
        app.include_router(mcp_router, prefix=get_mcp_mount_prefix())
    else:
        logger.info("MCP router skipped (tools.mcp.enabled is false)")
    app.include_router(ws_public_router)

    if config.get("auth.enabled", True) and not str(config.get("auth.api_key") or "").strip():
        new_key = secrets.token_urlsafe(32)
        config.set("auth.api_key", new_key, save=True)
        sync_first_run_notice(new_key)
    else:
        sync_first_run_notice(str(config.get("auth.api_key") or ""))

    removed = config.sanitize_auth_whitelist()
    if removed:
        logger.info("已从 auth.whitelist 移除不安全路径：" + ", ".join(removed))
    added = config.ensure_required_auth_whitelist()
    if added:
        logger.info("已补全 auth.whitelist 必需项：" + ", ".join(added))

    def _is_whitelisted(path: str) -> bool:
        rules = config.get("auth.whitelist", []) or []
        for r in rules:
            if not r:
                continue
            if r.endswith("*") and path.startswith(r[:-1]):
                return True
            if path == r:
                return True
        return False

    def _jwt_cookie_name() -> str:
        jc = config.get("auth.jwt") or {}
        if isinstance(jc, dict) and jc.get("cookie_name"):
            return str(jc["cookie_name"])
        return "ly_session"

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        if not config.get("auth.enabled", True):
            return await call_next(request)

        path = request.url.path
        ws_paths = tuple(getattr(request.app.state, "bridge_ws_paths", None) or [])
        if _auth_exempt_path(path, ws_paths=ws_paths):
            return await call_next(request)
        if _is_whitelisted(path):
            return await call_next(request)

        principal = authenticate_http(request)
        if not principal:
            if _ly_console_path(path):
                return RedirectResponse(url=_login_redirect_url(request), status_code=302)
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        allowed, reason = authorize_http(principal, request)
        if not allowed:
            return JSONResponse({"detail": reason or "Forbidden"}, status_code=403)

        request.state.principal = principal
        token = bind_principal(principal)
        try:
            return await call_next(request)
        finally:
            release_principal(token)

    _quiet_http_debug_paths = frozenset(
        {
            "/api/health",
            "/api/info",
            "/api/system/metrics",
            "/api/system/extensions",
        }
    )

    @app.middleware("http")
    async def debug_http_access(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        if path in _quiet_http_debug_paths or path.startswith("/ly/static/"):
            return response
        elapsed_ms = (time.perf_counter() - start) * 1000
        client = request.client.host if request.client else "-"
        logger.debug(
            "%s %s %s -> %s %.1fms",
            client,
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
        return response

    workbench_dir = get_project_root() / "www"
    _html_no_cache = {"Cache-Control": "no-cache, must-revalidate"}
    if workbench_dir.is_dir():
        app.mount(
            "/ly/static",
            StaticFiles(directory=str(workbench_dir), html=False),
            name="ly_static",
        )

        @app.get("/", include_in_schema=False)
        async def site_home():
            home = workbench_dir / "home.html"
            if not home.is_file():
                return HTMLResponse(_LOGIN_BUILD_MISSING, status_code=503)
            return HTMLResponse(home.read_text(encoding="utf-8"), headers=_html_no_cache)

        @app.get("/firefly", include_in_schema=False)
        async def site_firefly():
            firefly_html = workbench_dir / "firefly.html"
            if not firefly_html.is_file():
                return HTMLResponse(_LOGIN_BUILD_MISSING, status_code=503)
            return HTMLResponse(firefly_html.read_text(encoding="utf-8"), headers=_html_no_cache)

        @app.get("/ly", include_in_schema=False)
        @app.get("/ly/", include_in_schema=False)
        async def ly_workbench():
            app_html = workbench_dir / "app.html"
            if not app_html.is_file():
                app_html = workbench_dir / "index.html"
            if not app_html.is_file():
                return HTMLResponse(_LOGIN_BUILD_MISSING, status_code=503)
            return HTMLResponse(app_html.read_text(encoding="utf-8"), headers=_html_no_cache)

        @app.get("/ly/app", include_in_schema=False)
        @app.get("/ly/app/", include_in_schema=False)
        async def ly_app_legacy_redirect():
            return RedirectResponse(url="/ly/", status_code=307)

        @app.get("/ly/chat", include_in_schema=False)
        @app.get("/ly/chat/", include_in_schema=False)
        async def ly_chat_legacy_redirect():
            return RedirectResponse(url="/ly/?tab=chat", status_code=307)

        @app.get("/ly/login", include_in_schema=False)
        async def ly_login_page():
            login_html = workbench_dir / "login.html"
            if not login_html.is_file():
                return HTMLResponse(_LOGIN_BUILD_MISSING, status_code=503)
            return HTMLResponse(login_html.read_text(encoding="utf-8"), headers=_html_no_cache)

        @app.post("/ly/login", include_in_schema=False)
        async def ly_login_submit(request: Request):
            from ly_next.core.audit_log import audit_auth_event

            form = await request.form()
            api_key = (form.get("api_key") or "").strip()
            username = (form.get("username") or "").strip()
            password = (form.get("password") or "").strip()
            key = config.get("auth.api_key", "")
            cookie_name = config.get("auth.cookie_name", "ly_api_key")
            session_cookie = _jwt_cookie_name()
            remember = str(form.get("remember") or "").strip().lower() in ("1", "true", "yes", "on")
            cookie_secure = bool(config.get("auth.cookie_secure", False))
            cookie_kwargs: dict[str, Any] = {
                "httponly": True,
                "samesite": "lax",
                "secure": cookie_secure,
            }
            if remember:
                cookie_kwargs["max_age"] = 30 * 24 * 3600

            if username and password and jwt_enabled():
                principal = login_with_password(username, password)
                if principal:
                    token, _ttl = issue_access_token(
                        username=principal.subject,
                        role=principal.role,
                    )
                    next_path = _safe_ly_next_path(str(form.get("next") or ""))
                    resp = RedirectResponse(url=next_path, status_code=302)
                    resp.set_cookie(session_cookie, token, **cookie_kwargs)
                    audit_auth_event(
                        "login_success",
                        username=principal.subject,
                        role=principal.role,
                        via="workbench",
                    )
                    return resp
                audit_auth_event("login_failed", username=username, via="workbench")
                return RedirectResponse(url="/ly/login?e=1", status_code=302)

            if not api_key:
                return RedirectResponse(url="/ly/login?e=2", status_code=302)
            if key and api_key == str(key).strip():
                next_path = _safe_ly_next_path(str(form.get("next") or ""))
                resp = RedirectResponse(url=next_path, status_code=302)
                resp.set_cookie(cookie_name, api_key, **cookie_kwargs)
                audit_auth_event("login_success", via="api_key_cookie")
                return resp
            audit_auth_event("login_failed", via="api_key_cookie")
            return RedirectResponse(url="/ly/login?e=1", status_code=302)

    @app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
    async def chrome_devtools_well_known():
        return JSONResponse({})

    return app


def run():
    import argparse
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from ly_next.core.doctor import run_doctor_cli

        raise SystemExit(run_doctor_cli(sys.argv[2:]))

    if len(sys.argv) >= 3 and sys.argv[1] == "config" and sys.argv[2] == "migrate":
        from ly_next.core.config_migrate import run_config_migrate_cli

        raise SystemExit(run_config_migrate_cli(sys.argv[3:]))

    if len(sys.argv) >= 3 and sys.argv[1] == "plugins" and sys.argv[2] == "sync-deps":
        from ly_next.core.plugin_deps import run_plugin_deps_sync_cli

        raise SystemExit(run_plugin_deps_sync_cli(sys.argv[3:]))

    if len(sys.argv) >= 2 and sys.argv[1] == "sync":
        from ly_next.core.project_sync import run_sync_cli

        raise SystemExit(run_sync_cli(sys.argv[2:]))

    from ly_next.core.server_port import (
        ENV_PORT,
        is_port_in_use,
        remember_port,
        resolve_startup_port,
    )

    parser = argparse.ArgumentParser(
        description="LY-Next Agent Framework Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                     # 交互选择端口（TTY）或使用配置默认 8000
  %(prog)s --port 9000         # 指定端口 9000
  %(prog)s --host 127.0.0.1    # 仅本机监听
  %(prog)s --reload            # 开发热重载
  %(prog)s doctor              # 环境诊断（依赖、安全、配置）
  %(prog)s config migrate      # 合并 legacy LLM 块并清理 config.yaml
  %(prog)s sync                # 等同 uv sync --inexact + 插件依赖（推荐）
  %(prog)s plugins sync-deps   # 仅安装 plugins/local 插件 pip 依赖
  LY_NEXT_PORT=9000 %(prog)s   # 环境变量指定端口（非交互）
        """,
    )

    parser.add_argument("--host", default=None, help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help=f"Port to bind to (default: config or {ENV_PORT} or interactive)",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Skip interactive port prompt; use config / env / default",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument(
        "--show-full-api-key",
        action="store_true",
        help="Print full auth API key in startup report (default: masked)",
    )
    args = parser.parse_args()

    if args.show_full_api_key:
        os.environ["LY_NEXT_SHOW_FULL_API_KEY"] = "1"

    host = args.host or config.get("server.host", "0.0.0.0")
    config_port = config.get("server.port", 8000)
    port = resolve_startup_port(
        args.port,
        config_port,
        host=host,
        interactive=not args.no_prompt,
    )
    reload = args.reload or config.get("server.reload", False)
    log_level = str(config.get("server.log_level", "info")).lower()

    if args.host:
        config.set("server.host", host)
    if args.port or port != int(config_port or 8000):
        config.set("server.port", port)
    if args.reload:
        config.set("server.reload", reload)

    remember_port(port)

    refresh_ly_next_log_level_from_config()

    logger.subtitle("启动 LY-Next 服务")
    logger.status(f"Host {host}", "info", "CYAN")
    logger.status(f"Port {port}", "info", "CYAN")
    logger.status(f"Reload {'on' if reload else 'off'}", "running" if reload else "info", "YELLOW")
    logger.status(
        f"Uvicorn {log_level} · App {config.get('logging.level', 'info')}",
        "info",
        "CYAN",
    )

    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if is_port_in_use(bind_host, port):
        alt = port + 1
        logger.error(f"端口 {port} 已被占用，无法绑定")
        logger.tip(f"可尝试: uv run ly --port {alt}  或  LY_NEXT_PORT={alt} uv run ly --no-prompt")
        raise SystemExit(1)

    if config.get("bridge.onebot11.enabled", False):
        napcat_path = "/OneBotv11"
        ob_paths = config.get("bridge.onebot11.ws_paths") or []
        if ob_paths:
            napcat_path = str(ob_paths[0])
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        logger.status(
            f"NapCat WS ws://{display_host}:{port}{napcat_path}",
            "network",
            "MAGENTA",
        )

    logger.line("─", 44, "DIM")

    # uvicorn 在 Win 上 loop=auto 会显式 new ProactorEventLoop，与 psycopg 不兼容；loop=none 走策略
    uvicorn.run(
        "ly_next.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        access_log=False,
        log_config=get_uvicorn_log_config(),
        loop="none",
    )


app = create_app()


if __name__ == "__main__":
    run()
