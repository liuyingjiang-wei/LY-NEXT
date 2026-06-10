"""Register host filesystem and shell tools when enabled in config."""

from __future__ import annotations

from ly_next.core.logger import get_logger
from ly_next.tools.host_exec import host_run_command
from ly_next.tools.host_files import (
    host_delete_path,
    host_list_dir,
    host_read_file,
    host_write_file,
    read_file_range,
)
from ly_next.tools.host_sandbox import host_exec_enabled, host_tools_enabled
from ly_next.tools.host_search import grep_code
from ly_next.tools.registry import ToolRegistry

logger = get_logger(__name__)

_HOST_FILE_TOOLS = (
    host_read_file,
    read_file_range,
    grep_code,
    host_list_dir,
    host_write_file,
    host_delete_path,
)


def register_host_tools(registry: ToolRegistry) -> int:
    if not host_tools_enabled():
        logger.debug("[HostTools] tools.host.enabled=false; skipping host tools")
        return 0

    registered = 0
    for tool_obj in _HOST_FILE_TOOLS:
        try:
            registry.register(tool_obj)
            registered += 1
        except Exception as exc:
            logger.warning("[HostTools] failed to register %s: %s", tool_obj.name, exc)

    if host_exec_enabled():
        try:
            registry.register(host_run_command)
            registered += 1
        except Exception as exc:
            logger.warning("[HostTools] failed to register host_run_command: %s", exc)

    if registered:
        logger.info("[HostTools] registered %s host tools", registered)
    return registered
