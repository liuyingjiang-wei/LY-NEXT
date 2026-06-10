import copy
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from starlette.responses import FileResponse

from ly_next.agent.chat_pipeline import (
    ChatTurnRequest,
    await_user_persist,
    build_agent_deps,
    effective_turn_mode,
    prepare_chat_turn,
    run_agent_on_prepared,
)
from ly_next.agent.factory import AgentFactory
from ly_next.agent.image_reply import ensure_mixed_reply
from ly_next.agent.startup_memory import invalidate_startup_memory_cache
from ly_next.core.cache import cache
from ly_next.core.chat_trace_log import chat_info as chat_trace_info
from ly_next.core.chat_trace_log import chat_warn as chat_trace_warn
from ly_next.core.config import config, get_project_root
from ly_next.core.database import db
from ly_next.core.logger import get_logger, refresh_ly_next_log_level_from_config
from ly_next.core.observability import attach_run_fields
from ly_next.core.plugin.loader_security import plugin_security_profile
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.run_telemetry import snapshot_usage_for_api
from ly_next.core.task_manager import get_task_manager
from ly_next.core.thread_persistence import persist_chat_turn
from ly_next.messaging.models import mixed_message_to_dict
from ly_next.models.factory import LLMFactory
from ly_next.models.registry import ModelRegistry
from ly_next.rag import reset_document_retriever, reset_example_selector
from ly_next.rag.document_retriever import get_document_retriever
from ly_next.tools import get_tool_registry
from ly_next.tools.export_paths import resolve_export_path

router = APIRouter()
logger = get_logger(__name__)


def _resolve_plugins_dir() -> Path:
    raw = config.get("plugins.dir", "plugins")
    path = Path(str(raw or "plugins"))
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _plugins_directory_status() -> dict[str, Any]:
    from ly_next.core.plugin.loader import directory_plugin_load_status

    return directory_plugin_load_status()


def _tool_catalog() -> list[dict[str, Any]]:
    registry = get_tool_registry()
    out: list[dict[str, Any]] = []
    for t in sorted(registry.list_tools(), key=lambda x: x.definition.name):
        out.append(
            {
                "name": t.definition.name,
                "category": t.definition.category or "general",
                "description": (t.definition.description or "")[:400],
            }
        )
    return out


_SETTINGS_LOG_LEVELS = frozenset({"trace", "debug", "info", "warning", "error", "critical"})

_SETTINGS_EDITABLE_ROOTS = frozenset(
    {
        "llm",
        "logging",
        "server",
        "database",
        "redis",
        "services",
        "openai_llm",
        "anthropic_llm",
        "ollama_llm",
        "openai_compat_llm",
        "rag_embedding_llm",
        "rag_rerank_llm",
        "agent",
        "tools",
        "api",
        "auth",
        "bridge",
    }
)
_SETTINGS_RESTART_ROOTS = frozenset({"server", "database", "redis", "services", "bridge"})
_SETTINGS_RESTART_LABELS = {
    "server": "server（监听地址/端口）",
    "database": "database（PostgreSQL）",
    "redis": "redis",
    "services": "services（托管进程）",
    "bridge": "bridge（QQ / Telegram 消息桥接）",
}
_SETTINGS_HOT_LABELS = {
    "llm": "LLM 模型注册表",
    "openai_llm": "OpenAI",
    "anthropic_llm": "Anthropic",
    "ollama_llm": "Ollama",
    "openai_compat_llm": "OpenAI 兼容网关",
    "rag_embedding_llm": "Embedding",
    "rag_rerank_llm": "Rerank",
    "agent": "Agent / RAG",
    "tools": "工具与 MCP",
    "logging": "日志级别",
    "auth": "访问控制",
    "api": "动态 API",
}
_SETTINGS_MASK = "***"
_SETTINGS_SECRET_NORMALIZED = frozenset(
    {
        "api-key",
        "access-token",
        "password",
        "auth-token",
        "authorization",
        "x-api-key",
        "proxy-authorization",
        "bot-token",
    }
)


def _is_secret_leaf(key: str) -> bool:
    return str(key).lower().replace("_", "-") in _SETTINGS_SECRET_NORMALIZED


def _mask_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if _is_secret_leaf(k) and isinstance(v, str) and v.strip():
                out[k] = _SETTINGS_MASK
            else:
                out[k] = _mask_secrets(v)
        return out
    if isinstance(obj, list):
        return [_mask_secrets(x) for x in obj]
    return obj


def _extract_editable_settings(full: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for root in _SETTINGS_EDITABLE_ROOTS:
        if root not in full:
            continue
        block = full[root]
        if isinstance(block, dict):
            out[root] = _mask_secrets(copy.deepcopy(block))
        else:
            out[root] = block
    return out


def _restart_hints(patch: dict[str, Any]) -> list[str]:
    return _settings_effects(patch)["restart_required"]


_TELEGRAM_HOT_KEYS = frozenset(
    {
        "allow_from",
        "allowed_user_ids",
        "dm_policy",
        "approved_user_ids",
        "pairing",
        "auto_reply",
    }
)
_TELEGRAM_POLLER_KEYS = frozenset({"enabled", "bot_token", "poll_timeout"})


def _bridge_settings_effects(fragment: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    restart: list[str] = []
    hot: list[str] = []
    notes: list[str] = []

    tg = fragment.get("telegram")
    if isinstance(tg, dict) and tg:
        tg_keys = set(tg.keys())
        if tg_keys & _TELEGRAM_HOT_KEYS:
            hot.append("Telegram 白名单/私聊策略/自动回复")
        if tg_keys & _TELEGRAM_POLLER_KEYS:
            notes.append("Telegram 连接参数已保存，轮询将自动重载")
        token_val = tg.get("bot_token")
        if token_val not in (None, "", _SETTINGS_MASK) and "bot_token" in tg_keys:
            notes.append("Telegram 连接参数已保存，轮询将自动重载")

    ob = fragment.get("onebot11")
    if isinstance(ob, dict) and ob:
        restart.append("QQ OneBot 桥接（onebot11）")

    return restart, hot, notes


def _settings_effects(patch: dict[str, Any]) -> dict[str, Any]:
    restart: list[str] = []
    hot: list[str] = []
    notes: list[str] = []

    for root, fragment in patch.items():
        if root == "bridge" and isinstance(fragment, dict):
            br_restart, br_hot, br_notes = _bridge_settings_effects(fragment)
            restart.extend(br_restart)
            hot.extend(br_hot)
            notes.extend(br_notes)
        elif root in _SETTINGS_RESTART_ROOTS:
            restart.append(_SETTINGS_RESTART_LABELS.get(root, root))
        elif root == "tools" and isinstance(fragment, dict):
            hot.append(_SETTINGS_HOT_LABELS["tools"])
            mcp = fragment.get("mcp")
            if isinstance(mcp, dict) and any(
                k in mcp for k in ("remote", "enabled", "transport", "path")
            ):
                notes.append("远程 MCP 在进程启动时连接，修改后请重启 uv run ly")
        elif root == "auth":
            notes.append("鉴权变更后，已登录 Cookie 可能需要重新登录")
        elif root == "api" and isinstance(fragment, dict):
            hot.append(_SETTINGS_HOT_LABELS["api"])
            if any(k in fragment for k in ("auto_load", "security_profile", "api_dir")):
                notes.append("动态 API 加载策略变更后建议重启进程")
        elif root in _SETTINGS_HOT_LABELS:
            hot.append(_SETTINGS_HOT_LABELS[root])
        elif root == "agent" and isinstance(fragment, dict):
            hot.append(_SETTINGS_HOT_LABELS["agent"])

    restart = list(dict.fromkeys(restart))
    hot = list(dict.fromkeys(hot))
    notes = list(dict.fromkeys(notes))
    return {
        "restart_required": restart,
        "hot_reload": hot,
        "notes": notes,
    }


def _apply_settings_patch(dst: dict[str, Any], patch: dict[str, Any]) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _apply_settings_patch(dst[k], v)
        elif isinstance(v, dict):
            dst[k] = copy.deepcopy(v)
        else:
            if _is_secret_leaf(k) and v == _SETTINGS_MASK:
                continue
            dst[k] = v


PROCESS_STARTED_AT = time.time()
_LAST_NET_SAMPLE: dict[str, float] | None = None
_LAST_CPU_SAMPLE: dict[str, float] | None = None


def _read_windows_cpu_percent() -> float | None:
    global _LAST_CPU_SAMPLE
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor | "
                "Where-Object {$_.Name -eq '_Total'}).PercentProcessorTime",
            ],
            text=True,
            timeout=3,
        ).strip()
        val = float(out.splitlines()[-1]) if out else None
        if val is not None:
            _LAST_CPU_SAMPLE = {"value": val, "ts": time.time()}
            return max(0.0, min(100.0, val))
    except Exception:
        pass
    return _LAST_CPU_SAMPLE["value"] if _LAST_CPU_SAMPLE else None


def _read_windows_mem_percent() -> tuple[float | None, int | None, int | None]:
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$os=Get-CimInstance Win32_OperatingSystem; "
                "$total=[double]$os.TotalVisibleMemorySize*1024; "
                "$free=[double]$os.FreePhysicalMemory*1024; "
                "$used=$total-$free; "
                "$pct=if($total -gt 0){($used/$total)*100}else{0}; "
                'Write-Output "$pct|$used|$total"',
            ],
            text=True,
            timeout=3,
        ).strip()
        parts = out.split("|")
        if len(parts) == 3:
            pct = float(parts[0])
            used = int(float(parts[1]))
            total = int(float(parts[2]))
            return max(0.0, min(100.0, pct)), used, total
    except Exception:
        pass
    return None, None, None


def _read_windows_net_bytes() -> tuple[int, int]:
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$n=Get-NetAdapterStatistics | "
                "Where-Object { $_.InterfaceDescription -notlike '*Loopback*' "
                "-and $_.InterfaceDescription -notlike '*Teredo*' }; "
                "$rx=($n|Measure-Object -Property ReceivedBytes -Sum).Sum; "
                "$tx=($n|Measure-Object -Property SentBytes -Sum).Sum; "
                'Write-Output "$rx|$tx"',
            ],
            text=True,
            timeout=3,
        ).strip()
        a, b = out.split("|")
        return int(float(a or 0)), int(float(b or 0))
    except Exception:
        return 0, 0


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    model: str | None = None
    provider: str | None = None
    mode: str = "react"
    temperature: float = 0.7
    max_tokens: int = 2048
    vision_precaption: bool | None = None
    thread_id: str | None = None
    channel: str | None = "web"


class TaskCreateRequest(BaseModel):
    name: str
    metadata: dict[str, Any] | None = None


class RagTryRequest(BaseModel):
    query: str


class LlmTestRequest(BaseModel):
    provider: str | None = None
    overrides: dict[str, Any] | None = None
    timeout: int | None = None


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "ly-next"}


@router.get("/info")
async def get_info():
    from ly_next import __version__

    registry = get_tool_registry()
    return {
        "name": "ly-next",
        "version": __version__,
        "providers": LLMFactory.list_providers(),
        "tools_count": len(registry),
    }


@router.get("/system/readiness")
async def get_system_readiness():
    from ly_next.core.system_readiness import gather_readiness

    return await gather_readiness()


@router.get("/system/security/health")
async def get_security_health():
    from ly_next.core.security_health import gather_security_health

    return gather_security_health()


@router.post("/system/rag/try")
async def try_rag_retrieval(body: RagTryRequest):
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return await get_document_retriever().retrieve_results(query)


@router.post("/system/llm/test")
async def test_llm_connectivity(body: LlmTestRequest):
    from ly_next.core.llm_probe import probe_llm_connectivity

    return await probe_llm_connectivity(
        provider=body.provider,
        overrides=body.overrides,
        timeout=body.timeout,
    )


@router.get("/system/extensions")
async def get_system_extensions(request: Request):
    vector = {"available": False, "installed": False, "version": None, "error": None}
    db_status = {"connected": False, "database": None, "error": None}
    redis_status = {"connected": False, "error": None}

    try:
        await db.connect()
        db_status["connected"] = True
        async with db._engine.connect() as conn:
            db_name = await conn.scalar(text("SELECT current_database()"))
            db_status["database"] = db_name

            avail_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT default_version, installed_version "
                            "FROM pg_available_extensions WHERE name = 'vector'"
                        )
                    )
                )
                .mappings()
                .first()
            )
            if avail_row:
                vector["available"] = True
                vector["version"] = avail_row["installed_version"] or avail_row["default_version"]
                vector["installed"] = avail_row["installed_version"] is not None
    except Exception as e:
        db_status["error"] = str(e)
        vector["error"] = str(e)

    try:
        await cache.connect()
        if cache._client is not None:
            await cache._client.ping()
            redis_status["connected"] = True
    except Exception as e:
        redis_status["error"] = str(e)

    plugin_reg = getattr(request.app.state, "plugin_registry", None)
    ctx = getattr(request.app.state, "app_context", None)
    if plugin_reg is None and ctx is not None:
        plugin_reg = ctx.plugin_registry

    plugin_info: list[dict[str, Any]] = []
    bridge_info: list[dict[str, str | bool]] = []
    plugin_extras: dict[str, Any] = {}
    if plugin_reg is not None:
        plugin_info = plugin_reg.list_info()
        bridge_info = plugin_reg.bridge_registry.list_info()
    if ctx is not None:
        plugin_extras = {
            k: v
            for k, v in (ctx.extras or {}).items()
            if k.endswith("_registered") or k.endswith("_count")
        }

    user_plugins = [p for p in plugin_info if not p.get("builtin")]
    tool_registry = get_tool_registry()

    return {
        "database": db_status,
        "redis": redis_status,
        "extensions": {"vector": vector},
        "plugins": plugin_info,
        "plugins_summary": {
            "total": len(plugin_info),
            "builtin": sum(1 for p in plugin_info if p.get("builtin")),
            "user": len(user_plugins),
        },
        "plugins_config": {
            "enabled": bool(config.get("plugins.enabled", True)),
            "dir": str(_resolve_plugins_dir()),
            "security_profile": plugin_security_profile(),
            "entry_points": bool(config.get("plugins.entry_points", True)),
            "tools_plugin_dir": str(config.get("tools.plugin_dir") or ""),
            "directory": _plugins_directory_status(),
        },
        "plugin_extras": plugin_extras,
        "bridges": bridge_info,
        "agent_modes": AgentFactory.list_agent_types(),
        "tool_count": len(tool_registry.list_tools()),
        "host_platform": _host_platform_info(),
        "skills": _skills_extensions_info(),
        "host_approvals_pending": _host_approvals_pending_count(),
    }


def _host_approvals_pending_count() -> int:
    try:
        from ly_next.tools.host_approvals import list_approvals

        return len(list_approvals(status="pending"))
    except Exception:
        return 0


def _host_platform_info() -> dict[str, Any]:
    try:
        from ly_next.tools.host_platform import detect_host_platform, platform_label

        return {
            "platform": detect_host_platform(),
            "label": platform_label(),
        }
    except Exception as e:
        return {"platform": "unknown", "label": str(e)}


def _skills_extensions_info() -> dict[str, Any]:
    try:
        from ly_next.agent.skills_loader import discover_skills, skills_enabled

        if not skills_enabled():
            return {"enabled": False, "count": 0, "skills": []}
        items = discover_skills(force=True)
        return {
            "enabled": True,
            "count": len(items),
            "skills": [
                {"id": s.id, "name": s.name, "description": s.description, "path": s.rel_path}
                for s in items
            ],
        }
    except Exception as e:
        return {"enabled": False, "count": 0, "error": str(e)}


@router.get("/system/host-approvals")
async def list_host_approvals(status: str | None = None):
    from ly_next.tools.host_approvals import list_approvals

    allowed = {"pending", "approved", "denied", "expired", "consumed"}
    st = str(status or "").strip().lower() or None
    if st and st not in allowed:
        raise HTTPException(status_code=400, detail=f"invalid status: {status}")
    return {"approvals": list_approvals(status=st)}


@router.post("/system/host-approvals/{approval_id}/approve")
async def approve_host_action(approval_id: str):
    from ly_next.tools.host_approvals import decide_approval

    item, err = decide_approval(approval_id, approve=True)
    if item is None:
        raise HTTPException(status_code=404, detail=err or "not found")
    if err:
        raise HTTPException(status_code=409, detail=err)
    return {"approval": {"id": item.id, "status": item.status, "summary": item.summary}}


@router.get("/workspace/roots")
async def workspace_roots():
    from ly_next.tools.host_sandbox import host_roots, host_tools_enabled

    if not host_tools_enabled():
        return {
            "enabled": False,
            "roots": [],
            "hint": "请在配置中开启 tools.host.enabled",
        }
    roots = host_roots()
    return {
        "enabled": True,
        "roots": [{"path": str(p), "name": p.name or str(p)} for p in roots],
    }


@router.get("/workspace/tree")
async def workspace_tree(path: str = ".", recursive: bool = True):
    from ly_next.tools.host_files import host_list_dir
    from ly_next.tools.host_sandbox import host_tools_enabled

    if not host_tools_enabled():
        raise HTTPException(
            status_code=503,
            detail="host tools disabled; enable tools.host.enabled in config",
        )
    result = await host_list_dir(path=path, recursive=recursive)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "list failed")
    payload = result.result if isinstance(result.result, dict) else {}
    return {
        "path": payload.get("path"),
        "entries": payload.get("entries") or [],
        "truncated": bool(payload.get("truncated")),
        "limit": payload.get("limit"),
    }


@router.post("/system/host-approvals/{approval_id}/deny")
async def deny_host_action(approval_id: str):
    from ly_next.tools.host_approvals import decide_approval

    item, err = decide_approval(approval_id, approve=False)
    if item is None:
        raise HTTPException(status_code=404, detail=err or "not found")
    if err:
        raise HTTPException(status_code=409, detail=err)
    return {"approval": {"id": item.id, "status": item.status, "summary": item.summary}}


@router.get("/system/metrics")
async def get_system_metrics():
    global _LAST_NET_SAMPLE
    cpu_percent = None
    mem_percent = None
    disk_percent = None
    net_recv_bytes = 0
    net_sent_bytes = 0
    net_recv_rate = None
    net_sent_rate = None
    mem_used_bytes = None
    mem_total_bytes = None
    disk_used_bytes = None
    disk_total_bytes = None

    source = "fallback"
    try:
        import psutil  # type: ignore

        cpu_percent = psutil.cpu_percent(interval=0.15)
        vm = psutil.virtual_memory()
        mem_percent = vm.percent
        mem_used_bytes = vm.used
        mem_total_bytes = vm.total
        du = psutil.disk_usage(os.getcwd())
        disk_percent = du.percent
        disk_used_bytes = du.used
        disk_total_bytes = du.total
        net = psutil.net_io_counters()
        net_recv_bytes = int(net.bytes_recv)
        net_sent_bytes = int(net.bytes_sent)
        source = "psutil"
        now = time.time()
        if _LAST_NET_SAMPLE:
            dt = max(0.001, now - _LAST_NET_SAMPLE["ts"])
            net_recv_rate = max(0.0, (net_recv_bytes - _LAST_NET_SAMPLE["recv"]) / dt)
            net_sent_rate = max(0.0, (net_sent_bytes - _LAST_NET_SAMPLE["sent"]) / dt)
        _LAST_NET_SAMPLE = {"ts": now, "recv": float(net_recv_bytes), "sent": float(net_sent_bytes)}
    except Exception:
        if sys.platform.startswith("win"):
            cpu_percent = _read_windows_cpu_percent()
            mem_percent, mem_used_bytes, mem_total_bytes = _read_windows_mem_percent()
            net_recv_bytes, net_sent_bytes = _read_windows_net_bytes()
            source = "powershell"
            now = time.time()
            if _LAST_NET_SAMPLE:
                dt = max(0.001, now - _LAST_NET_SAMPLE["ts"])
                net_recv_rate = max(0.0, (net_recv_bytes - _LAST_NET_SAMPLE["recv"]) / dt)
                net_sent_rate = max(0.0, (net_sent_bytes - _LAST_NET_SAMPLE["sent"]) / dt)
            _LAST_NET_SAMPLE = {
                "ts": now,
                "recv": float(net_recv_bytes),
                "sent": float(net_sent_bytes),
            }
        try:
            du = shutil.disk_usage(os.getcwd())
            disk_total_bytes = du.total
            disk_used_bytes = du.used
            if du.total:
                disk_percent = round((du.used / du.total) * 100, 2)
        except Exception:
            pass

    uptime_seconds = max(0.0, time.time() - PROCESS_STARTED_AT)

    return {
        "cpu_percent": cpu_percent,
        "mem_percent": mem_percent,
        "disk_percent": disk_percent,
        "uptime_seconds": uptime_seconds,
        "net_recv_bytes": net_recv_bytes,
        "net_sent_bytes": net_sent_bytes,
        "net_recv_rate": net_recv_rate,
        "net_sent_rate": net_sent_rate,
        "mem_used_bytes": mem_used_bytes,
        "mem_total_bytes": mem_total_bytes,
        "disk_used_bytes": disk_used_bytes,
        "disk_total_bytes": disk_total_bytes,
        "source": source,
    }


@router.get("/system/settings")
async def get_workbench_settings():
    init = config.ensure_initialized()
    from ly_next.models.migrate import ensure_llm_models_migrated

    ensure_llm_models_migrated(save=False)
    ModelRegistry.ensure_loaded()
    full = config.to_dict()
    abs_path = Path(init["path"])
    try:
        rel_path = str(abs_path.relative_to(config.project_root.resolve()))
    except ValueError:
        rel_path = str(abs_path)
    return {
        "editable": _extract_editable_settings(full),
        "config_path": rel_path,
        "config_abs_path": str(abs_path),
        "config_init": {
            "created": init["created"],
            "exists": init["exists"],
            "parent_writable": init["parent_writable"],
        },
        "llm_providers": LLMFactory.list_providers(),
        "model_formats": sorted(["openai", "openai_compat", "anthropic", "ollama"]),
        "registered_models": ModelRegistry.list_model_infos(),
        "agent_modes": AgentFactory.list_agent_types(),
        "tool_catalog": _tool_catalog(),
    }


@router.patch("/system/settings")
async def patch_workbench_settings(body: dict[str, Any]):
    config.ensure_initialized()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    unknown = [k for k in body if k not in _SETTINGS_EDITABLE_ROOTS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"不允许修改的配置段: {', '.join(unknown)}")
    for root, fragment in body.items():
        if not isinstance(fragment, dict):
            raise HTTPException(status_code=400, detail=f"{root} 必须为对象")
        if root == "logging" and "level" in fragment:
            lv = str(fragment["level"] or "").strip().lower()
            if lv not in _SETTINGS_LOG_LEVELS:
                raise HTTPException(
                    status_code=400,
                    detail=f"logging.level 无效，允许: {', '.join(sorted(_SETTINGS_LOG_LEVELS))}",
                )
        base = config.get(root, {})
        if not isinstance(base, dict):
            base = {}
        merged = copy.deepcopy(base)
        _apply_settings_patch(merged, fragment)
        config.set(root, merged, save=False)
    config.save()
    config.load()
    from ly_next.models.migrate import ensure_llm_models_migrated

    ensure_llm_models_migrated(save=False)
    if "auth" in body:
        from ly_next.core.first_run import sync_first_run_notice

        sync_first_run_notice(str(config.get("auth.api_key") or ""))
    bridge_patch = body.get("bridge")
    if isinstance(bridge_patch, dict) and isinstance(bridge_patch.get("telegram"), dict):
        try:
            from telegram_bot.api import reload_telegram_poller

            await reload_telegram_poller(bridge_patch["telegram"])
        except ImportError:
            pass
        except Exception:
            pass
    refresh_ly_next_log_level_from_config()
    LLMFactory.clear_cache()
    ModelRegistry.reload()
    reset_document_retriever()
    reset_example_selector()
    invalidate_startup_memory_cache()
    init = config.ensure_initialized()
    full = config.to_dict()
    abs_path = Path(init["path"])
    try:
        rel_path = str(abs_path.relative_to(config.project_root.resolve()))
    except ValueError:
        rel_path = str(abs_path)
    effects = _settings_effects(body)
    return {
        "ok": True,
        "editable": _extract_editable_settings(full),
        "config_path": rel_path,
        "config_abs_path": str(abs_path),
        "config_init": {
            "created": init["created"],
            "exists": init["exists"],
            "parent_writable": init["parent_writable"],
        },
        "tool_catalog": _tool_catalog(),
        "llm_providers": LLMFactory.list_providers(),
        "registered_models": ModelRegistry.list_model_infos(),
        "restart_required": effects["restart_required"],
        "settings_effects": effects,
    }


@router.get("/tasks")
async def list_tasks(status: str | None = None, limit: int = 100):
    manager = get_task_manager()
    tasks = await manager.list_tasks(status=status, limit=limit)
    return {"tasks": [t.model_dump(mode="json") for t in tasks], "count": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    manager = get_task_manager()
    task = await manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.model_dump(mode="json")


@router.post("/tasks")
async def create_task(request: TaskCreateRequest):
    manager = get_task_manager()
    task_id = await manager.create_task(name=request.name, metadata=request.metadata)
    entry = await manager.get_task(task_id)
    return {"task_id": task_id, "task": (entry.model_dump(mode="json") if entry else None)}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    manager = get_task_manager()
    if not await manager.delete(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True}


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    manager = get_task_manager()
    if not await manager.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": await manager.stop(task_id)}


@router.get("/tools")
async def list_tools():
    registry = get_tool_registry()
    return {
        "tools": registry.get_tools_for_llm(),
        "count": len(registry),
        "categories": registry.list_categories(),
    }


@router.get("/tools/{tool_name}")
async def get_tool(tool_name: str):
    registry = get_tool_registry()
    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {
        "name": tool.definition.name,
        "description": tool.definition.description,
        "parameters": tool.definition.parameters,
        "category": tool.definition.category,
    }


@router.post("/tools/{tool_name}/call")
async def call_tool(tool_name: str, arguments: dict[str, Any]):
    registry = get_tool_registry()
    return await registry.call_tool(tool_name, arguments)


@router.get("/exports/{filename}")
async def download_export(filename: str):
    path = resolve_export_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )


@router.post("/chat")
async def chat(request: ChatRequest):
    manager = get_task_manager()
    task_id = await manager.create_task(name="Chat Request")
    await manager.update(task_id, status="running")

    chat_trace_info(
        "recv",
        task_id=task_id,
        requested_mode=request.mode,
        thread_id=request.thread_id,
        channel=request.channel or "web",
        client_messages=list(request.messages),
    )

    try:
        chat_req = ChatTurnRequest(
            client_messages=list(request.messages),
            thread_id=request.thread_id,
            mode=request.mode,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            provider=request.provider,
            model=request.model,
            skip_vision_precaption=request.vision_precaption is False,
            channel=request.channel or "web",
            turn_meta_extra={
                "task_id": task_id,
                "requested_mode": request.mode,
                "channel": request.channel or "web",
            },
        )
        prepared = await prepare_chat_turn(chat_req)
        mode = effective_turn_mode(prepared)
        chat_trace_info(
            "prepared",
            task_id=task_id,
            effective_mode=mode,
            thread_id=prepared.thread_id,
            provider=prepared.routed.provider,
            model=prepared.routed.model,
            plan=prepared.plan,
            messages=prepared.messages,
        )
    except ValueError as e:
        chat_trace_warn("prepare_failed", task_id=task_id, error=str(e))
        await manager.fail(task_id, str(e))
        raise HTTPException(status_code=404, detail=str(e)) from e

    telemetry_token = await start_observed_run(
        task_id,
        mode=mode,
        thread_id=prepared.thread_id,
        router=prepared.router_payload,
    )
    run_status = "ok"
    run_error: str | None = None
    snap: dict[str, Any] | None = None
    result = ""
    mixed_payload: dict[str, Any] | None = None
    image_urls: list[str] = []
    try:
        deps = build_agent_deps(
            prepared,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            agent_mode=mode,
        )
        result = await run_agent_on_prepared(prepared, deps, mode=mode)
        await await_user_persist(prepared)
        mixed = await ensure_mixed_reply(deps, result)
        mixed_payload = mixed_message_to_dict(mixed)
        image_urls = mixed.image_urls()

        await persist_chat_turn(
            prepared.thread_id,
            [],
            result,
            metadata={
                **prepared.turn_meta,
                "run_id": task_id,
                "mixed_message": mixed_payload,
                "image_urls": image_urls,
            },
        )

        await manager.complete(task_id, result=result)
    except Exception as e:
        run_status = "error"
        run_error = str(e)
        await manager.fail(task_id, str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        snap = await finish_observed_run(
            telemetry_token, task_id, status=run_status, error=run_error
        )

    if snap:
        logger.info("[api.chat] task=%s run_summary=%s", task_id, snap)
    body: dict[str, Any] = {
        "task_id": task_id,
        "run_id": task_id,
        "thread_id": prepared.thread_id,
        "response": result,
        "usage": snapshot_usage_for_api(snap),
        "router": prepared.router_payload,
    }
    if mixed_payload is not None:
        body["mixed_message"] = mixed_payload
        body["image_urls"] = image_urls
    return attach_run_fields(body, snap)
