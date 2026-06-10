"""Host shell execution under configured roots (default cwd: user home)."""

from __future__ import annotations

import asyncio
import os
import subprocess

from ly_next.tools.base import ToolResult, tool
from ly_next.tools.host_approvals import check_approval_gate, command_needs_approval
from ly_next.tools.host_sandbox import (
    default_shell_command,
    host_exec_max_output_chars,
    host_exec_timeout_seconds,
    resolve_host_cwd,
)
from ly_next.tools.host_platform import platform_label


def _truncate_output(text: str, cap: int) -> tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap] + f"\n… truncated ({len(text)} chars total)", True


@tool(
    name="host_run_command",
    description=(
        "Run a shell command on the host machine. Working directory must stay within "
        "allowed roots (default: user home). Use for installing packages, running scripts, "
        "or invoking CLI tools. Returns stdout, stderr, and exit code."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "cwd": {
                "type": "string",
                "description": "Working directory (default: tools.host.exec.default_cwd or home)",
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Timeout in seconds (capped by server config)",
            },
            "approval_token": {
                "type": "string",
                "description": "Token after user approved a destructive command",
            },
        },
        "required": ["command"],
    },
)
async def host_run_command(
    command: str,
    cwd: str | None = None,
    timeout_seconds: float | None = None,
    approval_token: str | None = None,
) -> ToolResult:
    cmd_text = str(command or "").strip()
    if not cmd_text:
        return ToolResult(success=False, error="command is required")

    workdir, err = resolve_host_cwd(cwd)
    if err or workdir is None:
        return ToolResult(success=False, error=err or "invalid cwd")
    if not workdir.is_dir():
        return ToolResult(success=False, error=f"cwd is not a directory: {workdir}")

    from ly_next.tools.host_exec_guard import command_hard_blocked, minimal_exec_env

    blocked = command_hard_blocked(cmd_text)
    if blocked:
        return ToolResult(success=False, error=blocked)

    gate = check_approval_gate(
        tool="host_run_command",
        action="exec",
        summary=f"Run command in {workdir}: {cmd_text[:240]}",
        payload={"command": cmd_text, "cwd": str(workdir)},
        approval_token=approval_token,
        needs_approval=command_needs_approval(cmd_text),
    )
    if gate is not None:
        return gate

    timeout = host_exec_timeout_seconds()
    if timeout_seconds is not None:
        try:
            timeout = max(1.0, min(float(timeout_seconds), host_exec_timeout_seconds()))
        except (TypeError, ValueError):
            pass

    cap = host_exec_max_output_chars()
    try:
        argv = default_shell_command(cmd_text)
    except OSError as exc:
        return ToolResult(success=False, error=str(exc))

    def _run_sync() -> subprocess.CompletedProcess[bytes]:
        env = minimal_exec_env()
        return subprocess.run(
            argv,
            cwd=str(workdir),
            capture_output=True,
            timeout=timeout,
            env=env if env is not None else os.environ.copy(),
            check=False,
        )

    try:
        completed = await asyncio.to_thread(_run_sync)
    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            error=f"command timed out after {timeout}s",
            result={"cwd": str(workdir), "command": cmd_text, "timed_out": True},
        )
    except OSError as exc:
        return ToolResult(success=False, error=f"failed to start process: {exc}")

    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    out_text, out_trunc = _truncate_output(stdout, cap)
    err_text, err_trunc = _truncate_output(stderr, cap)
    exit_code = int(completed.returncode)

    return ToolResult(
        success=exit_code == 0,
        result={
            "platform": platform_label(),
            "cwd": str(workdir),
            "command": cmd_text,
            "exit_code": exit_code,
            "stdout": out_text,
            "stderr": err_text,
            "stdout_truncated": out_trunc,
            "stderr_truncated": err_trunc,
        },
        error=None if exit_code == 0 else f"exit code {exit_code}",
    )
