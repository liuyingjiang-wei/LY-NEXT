import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from ly_next import __version__
from ly_next.api import api_router, mcp_router, ws_public_router
from ly_next.api.bridge import SUPPORTED_CHANNELS
from ly_next.api.loader import APILoader
from ly_next.api.mcp_api import get_mcp_mount_prefix
from ly_next.core.cache import cache
from ly_next.core.config import config, get_project_root
from ly_next.core.database import db
from ly_next.core.logger import (
    print_startup_report,
    refresh_ly_next_log_level_from_config,
    setup_logging,
)
from ly_next.core.service_manager import (
    InstallStatus,
    ServiceInfo,
    ServiceStatus,
    get_service_manager,
)
from ly_next.core.startup_manager import get_startup_manager
from ly_next.core.task_manager import get_task_manager
from ly_next.mcp.remote_bridge import load_remote_mcp_tools
from ly_next.tools import BUILTIN_TOOLS, get_tool_registry

logger = setup_logging()

_LOGIN_BUILD_MISSING = (
    '<!doctype html><html lang="zh-CN"><meta charset="utf-8"/><title>登录</title>'
    '<body style="font-family:system-ui,sans-serif;padding:2rem;max-width:36rem">'
    "<p>未找到 React 登录页。请在项目根目录执行 <code>pnpm run build:workbench</code> 生成 "
    "<code>www/login.html</code>。</p></body></html>"
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
    if log_not_installed and info.install_status == InstallStatus.NOT_INSTALLED:
        logger.info("%s not installed, attempting auto-install...", label)
    return await ensure()


def _auth_exempt_path(path: str) -> bool:
    if path.startswith("/ly/static/"):
        return True
    return path in (
        "/ly/login",
        "/ly/login/",
        "/.well-known/appspecific/com.chrome.devtools.json",
    )


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

    if app.state.redis_available or db._engine is not None:
        try:
            await db.create_tables()
        except Exception as e:
            logger.warning(f"Table creation failed: {e}")

    registry = get_tool_registry()
    for tool in BUILTIN_TOOLS:
        try:
            registry.register(tool)
        except Exception as e:
            logger.warning(f"Failed to register tool {tool.name}: {e}")

    logger.debug(f"Registered {len(registry)} tools")

    try:
        await load_remote_mcp_tools()
    except Exception as e:
        logger.warning("Remote MCP init: %s", e)

    api_loader = APILoader()
    api_loader.load_apis()
    await api_loader.registry.startup(app)
    logger.debug(f"Loaded {len(api_loader.registry.list_apis())} APIs")

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
    report = {
        "title": "LY-Next 启动完成",
        "startup_ms": startup_ms,
        "started_at": time.strftime("%Y/%m/%d %H:%M:%S"),
        "server_url": f"http://{host}:{port}",
        "docs_url": f"http://{host}:{port}/docs",
        "workbench_url": f"http://{host}:{port}/ly/",
        "workbench_login_url": f"http://{host}:{port}/ly/login",
        "ws": {
            "url": f"ws://{host}:{port}",
            "paths": f"{len(ws_paths)}个 [{', '.join(ws_paths) if ws_paths else ''}]",
            "service_line": f"ws://{ws_host}:{port}/ [{', '.join(sorted(SUPPORTED_CHANNELS))}]",
        },
        "perf": {
            "mem": mem_str,
            "cpu": cpu_str,
            "platform": f"{__import__('platform').system().lower()} {__import__('platform').machine().lower()}",
            "python": __import__("sys").version.split()[0],
        },
        "api": {
            "modules": str(len(api_loader.registry.list_apis())),
            "http_routes": str(http_routes),
            "ws_routes": str(ws_routes),
        },
        "auth": {"api_key": auth_key, "header": header_name, "whitelist": wl},
        "services": {
            "PostgreSQL": postgres_info.status == ServiceStatus.RUNNING,
            "Redis": redis_info.status == ServiceStatus.RUNNING,
        },
    }
    print_startup_report(report)

    logger.info(f"LY-Next v{__version__} started successfully")

    yield

    logger.info("Shutting down LY-Next...")
    await api_loader.registry.shutdown(app)

    for svc in [db.disconnect(), cache.disconnect()]:
        with suppress(Exception):
            await svc

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
        allow_origins=config.get("cors.origins", ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    if config.get("tools.mcp.enabled", True):
        app.include_router(mcp_router, prefix=get_mcp_mount_prefix())
    else:
        logger.info("MCP router skipped (tools.mcp.enabled is false)")
    app.include_router(ws_public_router)

    if config.get("auth.enabled", True) and not config.get("auth.api_key"):
        config.set("auth.api_key", secrets.token_urlsafe(32), save=True)

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

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        if not config.get("auth.enabled", True):
            return await call_next(request)

        path = request.url.path
        if _auth_exempt_path(path):
            return await call_next(request)
        if _is_whitelisted(path):
            return await call_next(request)

        key = config.get("auth.api_key", "")
        header_name = config.get("auth.header_name", "X-API-Key")
        cookie_name = config.get("auth.cookie_name", "ly_api_key")

        provided = (
            request.headers.get(header_name)
            or request.cookies.get(cookie_name)
            or request.query_params.get("api_key")
        )
        if key and provided == key:
            return await call_next(request)

        if path.startswith("/ly"):
            return RedirectResponse(url="/ly/login", status_code=302)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

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
    if workbench_dir.is_dir():
        app.mount(
            "/ly/static",
            StaticFiles(directory=str(workbench_dir), html=False),
            name="ly_static",
        )

        @app.get("/ly/", include_in_schema=False)
        async def ly_index():
            index = workbench_dir / "index.html"
            return HTMLResponse(index.read_text(encoding="utf-8"))

        @app.get("/ly/login", include_in_schema=False)
        async def ly_login_page():
            login_html = workbench_dir / "login.html"
            if not login_html.is_file():
                return HTMLResponse(_LOGIN_BUILD_MISSING, status_code=503)
            return HTMLResponse(login_html.read_text(encoding="utf-8"))

        @app.post("/ly/login", include_in_schema=False)
        async def ly_login_submit(request: Request):
            form = await request.form()
            api_key = (form.get("api_key") or "").strip()
            key = config.get("auth.api_key", "")
            cookie_name = config.get("auth.cookie_name", "ly_api_key")
            if not api_key:
                return RedirectResponse(url="/ly/login?e=2", status_code=302)
            if key and api_key == key:
                resp = RedirectResponse(url="/ly/", status_code=302)
                resp.set_cookie(cookie_name, api_key, httponly=True, samesite="lax")
                return resp
            return RedirectResponse(url="/ly/login?e=1", status_code=302)

    @app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
    async def chrome_devtools_well_known():
        return JSONResponse({})

    return app


def run():
    import argparse

    parser = argparse.ArgumentParser(
        description="LY-Next Agent Framework Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                  # Start with default settings (0.0.0.0:8000)
  %(prog)s --port 9000     # Start on port 9000
  %(prog)s --host 127.0.0.1  # Bind to localhost only
  %(prog)s --reload        # Enable auto-reload for development
        """,
    )

    parser.add_argument("--host", default=None, help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument(
        "-p", "--port", type=int, default=None, help="Port to bind to (default: 8000)"
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    host = args.host or config.get("server.host", "0.0.0.0")
    port = args.port or config.get("server.port", 8000)
    reload = args.reload or config.get("server.reload", False)
    log_level = str(config.get("server.log_level", "info")).lower()

    if args.host:
        config.set("server.host", host)
    if args.port:
        config.set("server.port", port)
    if args.reload:
        config.set("server.reload", reload)

    logger.info("=" * 50)
    logger.info("Starting LY-Next Server")
    logger.info(f"Host: {host}")
    logger.info(f"Port: {port}")
    logger.info(f"Reload: {reload}")
    logger.info(
        "Uvicorn: server.log_level=%s | App: logging.level=%s",
        log_level,
        config.get("logging.level", "info"),
    )
    logger.info("=" * 50)

    refresh_ly_next_log_level_from_config()

    uvicorn.run(
        "ly_next.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        access_log=False,
    )


app = create_app()


if __name__ == "__main__":
    run()
