import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from ly_next.agent.deps import create_agent_deps
from ly_next.agent.factory import AgentFactory
from ly_next.agent.model_router import resolve_model_routing
from ly_next.agent.prompt_augment import augment_messages_async
from ly_next.agent.vision_precaption import apply_vision_precaption_if_needed
from ly_next.api.bridge import (
    SUPPORTED_CHANNELS,
    emit_channel_event,
    get_device_session,
    is_supported_channel,
    list_device_sessions,
    update_device_session,
)
from ly_next.core.cache import cache
from ly_next.core.config import config
from ly_next.core.database import db
from ly_next.core.logger import refresh_ly_next_log_level_from_config
from ly_next.core.task_manager import get_task_manager
from ly_next.models.factory import LLMFactory
from ly_next.rag import reset_document_retriever, reset_example_selector
from ly_next.tools import get_tool_registry

router = APIRouter()


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
        "openai_llm",
        "anthropic_llm",
        "ollama_llm",
        "openai_compat_llm",
        "rag_embedding_llm",
        "agent",
        "tools",
    }
)
_SETTINGS_MASK = "***"
_SETTINGS_SECRET_NORMALIZED = frozenset(
    {"api-key", "password", "auth-token", "authorization", "x-api-key", "proxy-authorization"}
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
    router_hint: str | None = None
    use_model_router: bool | None = None


class TaskCreateRequest(BaseModel):
    name: str
    metadata: dict[str, Any] | None = None


class BridgeEmitRequest(BaseModel):
    event: str = "event"
    source: str = "http"
    payload: dict[str, Any] = {}
    device_id: str | None = None


class DeviceSessionUpdateRequest(BaseModel):
    status: str = "online"
    state: dict[str, Any] = {}
    meta: dict[str, Any] = {}


class StdinReplayRequest(BaseModel):
    record: dict[str, Any] | None = None
    journal_line: str | None = None
    log_line: str | None = None
    line: str | None = None
    source: str = "http_replay"


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


@router.get("/system/extensions")
async def get_system_extensions():
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

    return {
        "database": db_status,
        "redis": redis_status,
        "extensions": {"vector": vector},
    }


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
    refresh_ly_next_log_level_from_config()
    LLMFactory.clear_cache()
    reset_document_retriever()
    reset_example_selector()
    init = config.ensure_initialized()
    full = config.to_dict()
    abs_path = Path(init["path"])
    try:
        rel_path = str(abs_path.relative_to(config.project_root.resolve()))
    except ValueError:
        rel_path = str(abs_path)
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


@router.post("/chat")
async def chat(request: ChatRequest):
    manager = get_task_manager()
    task_id = await manager.create_task(name="Chat Request")
    await manager.update(task_id, status="running")

    try:
        messages = await apply_vision_precaption_if_needed(list(request.messages))
        routed = await resolve_model_routing(
            messages,
            request_provider=request.provider,
            request_model=request.model,
            router_hint=request.router_hint,
            enabled_override=request.use_model_router,
        )
        deps = create_agent_deps(provider=routed.provider, model=routed.model)
        deps.temperature = request.temperature
        deps.max_tokens = request.max_tokens
        deps.tool_registry = get_tool_registry()

        messages = await augment_messages_async(messages)
        agent = AgentFactory.create_agent(mode=request.mode, deps=deps)
        result = await agent.run(messages)

        await manager.complete(task_id, result=result)
        return {
            "task_id": task_id,
            "response": result,
            "usage": {"total_tokens": 0},
            "router": {
                "task_kind": routed.task_kind.value,
                "via": routed.via,
                "provider": routed.provider,
                "model": routed.model,
            },
        }
    except Exception as e:
        await manager.fail(task_id, str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/bridge/channels")
async def bridge_channels():
    return {"channels": sorted(SUPPORTED_CHANNELS), "count": len(SUPPORTED_CHANNELS)}


@router.post("/bridge/{channel}/emit")
async def bridge_emit(channel: str, request: BridgeEmitRequest):
    if not is_supported_channel(channel):
        raise HTTPException(status_code=404, detail=f"Unsupported channel: {channel}")
    receivers = await emit_channel_event(
        channel,
        request.event or f"{channel}_event",
        {
            "source": request.source,
            "payload": request.payload,
            "device_id": request.device_id,
        },
    )
    return {"success": True, "channel": channel, "receivers": receivers}


@router.post("/bridge/stdin/replay")
async def bridge_stdin_replay(request: StdinReplayRequest):
    from ly_next.core.stdin_journal import extract_line_source, parse_log_line, publish_stdin_line

    def _replay_from_rec(rec: dict[str, Any]) -> tuple[str, str]:
        pair = extract_line_source(rec)
        if not pair:
            raise HTTPException(status_code=400, detail="record has no string line field")
        return pair

    if request.record:
        line, src = _replay_from_rec(request.record)
        receivers = await publish_stdin_line(line, src, replay=True)
        return {"success": True, "channel": "stdin", "receivers": receivers, "source": src}

    jl = (request.journal_line or "").strip()
    if jl:
        try:
            rec = json.loads(jl)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"journal_line is not JSON: {e}") from e
        if not isinstance(rec, dict):
            raise HTTPException(status_code=400, detail="journal_line must be one JSON object")
        line, src = _replay_from_rec(rec)
        receivers = await publish_stdin_line(line, src, replay=True)
        return {"success": True, "channel": "stdin", "receivers": receivers, "source": src}

    raw_log = (request.log_line or "").strip()
    if raw_log:
        rec = parse_log_line(raw_log)
        if not rec:
            raise HTTPException(
                status_code=400,
                detail="log_line must contain legacy LY_NEXT_STDIN payload",
            )
        line, src = _replay_from_rec(rec)
        receivers = await publish_stdin_line(line, src, replay=True)
        return {"success": True, "channel": "stdin", "receivers": receivers, "source": src}

    if request.line is not None and str(request.line).strip() != "":
        receivers = await publish_stdin_line(
            str(request.line).replace("\r\n", "\n").replace("\r", "\n"),
            request.source.strip() or "http_replay",
            replay=True,
        )
        return {"success": True, "channel": "stdin", "receivers": receivers}

    raise HTTPException(
        status_code=400,
        detail="Provide record, journal_line, log_line (legacy), or non-empty line",
    )


@router.get("/bridge/device/sessions")
async def bridge_device_sessions():
    rows = list_device_sessions()
    return {"sessions": rows, "count": len(rows)}


@router.get("/bridge/device/sessions/{device_id}")
async def bridge_device_session(device_id: str):
    row = get_device_session(device_id)
    if not row:
        raise HTTPException(status_code=404, detail="Device session not found")
    return row


@router.post("/bridge/device/sessions/{device_id}")
async def bridge_device_session_update(device_id: str, request: DeviceSessionUpdateRequest):
    session = update_device_session(
        device_id,
        status=request.status,
        state=request.state,
        meta=request.meta,
        channel="device",
    )
    await emit_channel_event("device", "device_status", {"session": session, "source": "http"})
    return {"success": True, "session": session}
