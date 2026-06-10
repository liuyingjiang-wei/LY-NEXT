"""Host filesystem tools scoped to configured roots (default: user home)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from ly_next.tools.base import ToolResult, tool
from ly_next.tools.host_approvals import check_approval_gate, delete_needs_approval
from ly_next.tools.host_sandbox import host_int_limit, resolve_host_path


def _max_read_bytes() -> int:
    return host_int_limit("tools.host.max_read_bytes", 2_097_152, minimum=1024, maximum=16_777_216)


def _max_write_bytes() -> int:
    return host_int_limit("tools.host.max_write_bytes", 4_194_304, minimum=1024, maximum=16_777_216)


def _max_list_entries() -> int:
    return host_int_limit("tools.host.max_list_entries", 500, minimum=1, maximum=5000)


def _entry_info(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        mtime = None
    kind = "dir" if path.is_dir() else "file"
    return {
        "name": path.name,
        "path": str(path),
        "type": kind,
        "size": stat.st_size if mtime is not None else None,
        "modified_utc": mtime,
    }


@tool(
    name="host_read_file",
    description=(
        "Read a full text file under allowed host roots. "
        "For large files use read_file_range; to search use grep_code."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or root-relative file path"},
            "encoding": {
                "type": "string",
                "description": "Text encoding",
                "default": "utf-8",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return",
                "default": 120000,
            },
        },
        "required": ["path"],
    },
)
async def host_read_file(
    path: str,
    encoding: str = "utf-8",
    max_chars: int = 120_000,
) -> ToolResult:
    resolved, err = resolve_host_path(path, must_exist=True)
    if err or resolved is None:
        return ToolResult(success=False, error=err or "invalid path")
    if not resolved.is_file():
        return ToolResult(success=False, error=f"not a file: {resolved}")

    cap_bytes = _max_read_bytes()
    cap_chars = max(1024, min(int(max_chars), cap_bytes))
    try:
        size = resolved.stat().st_size
        if size > cap_bytes:
            return ToolResult(
                success=False,
                error=f"file too large ({size} bytes); max_read_bytes={cap_bytes}",
            )
        text = resolved.read_text(encoding=encoding or "utf-8", errors="replace")
    except OSError as exc:
        return ToolResult(success=False, error=str(exc))

    truncated = len(text) > cap_chars
    if truncated:
        text = text[:cap_chars] + f"\n… truncated ({len(text)} chars total)"
    return ToolResult(
        success=True,
        result={
            "path": str(resolved),
            "size": size,
            "truncated": truncated,
            "content": text,
        },
    )


@tool(
    name="read_file_range",
    description=(
        "Read a line range from a text file under allowed host roots (1-based inclusive). "
        "Prefer over host_read_file for large sources."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "start_line": {"type": "integer", "description": "First line (>=1)", "default": 1},
            "end_line": {
                "type": "integer",
                "description": "Last line inclusive; omit to read through end_line=start+199",
            },
            "encoding": {"type": "string", "default": "utf-8"},
        },
        "required": ["path"],
    },
)
async def read_file_range(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    encoding: str = "utf-8",
) -> ToolResult:
    resolved, err = resolve_host_path(path, must_exist=True)
    if err or resolved is None:
        return ToolResult(success=False, error=err or "invalid path")
    if not resolved.is_file():
        return ToolResult(success=False, error=f"not a file: {resolved}")

    start = max(1, int(start_line))
    span = host_int_limit("tools.host.read_range_max_lines", 500, minimum=1, maximum=2000)
    stop = end_line if end_line is not None else start + span - 1
    stop = max(start, int(stop))
    if stop - start + 1 > span:
        stop = start + span - 1

    cap_bytes = _max_read_bytes()
    try:
        size = resolved.stat().st_size
        if size > cap_bytes:
            return ToolResult(
                success=False,
                error=f"file too large ({size} bytes); max_read_bytes={cap_bytes}",
            )
        lines = resolved.read_text(encoding=encoding or "utf-8", errors="replace").splitlines()
    except OSError as exc:
        return ToolResult(success=False, error=str(exc))

    total = len(lines)
    if start > total:
        return ToolResult(
            success=True,
            result={
                "path": str(resolved),
                "total_lines": total,
                "start_line": start,
                "end_line": stop,
                "content": "",
            },
        )

    slice_lines = lines[start - 1 : stop]
    body = "\n".join(f"{lineno}:{text}" for lineno, text in enumerate(slice_lines, start=start))
    return ToolResult(
        success=True,
        result={
            "path": str(resolved),
            "total_lines": total,
            "start_line": start,
            "end_line": start + len(slice_lines) - 1,
            "content": body,
        },
    )


@tool(
    name="host_list_dir",
    description=(
        "List files and subdirectories under the allowed host roots. "
        "Returns entry names, types, sizes, and modification times."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (default: first host root)",
                "default": ".",
            },
            "recursive": {
                "type": "boolean",
                "description": "List recursively (depth-first, capped)",
                "default": False,
            },
        },
        "required": [],
    },
)
async def host_list_dir(path: str = ".", recursive: bool = False) -> ToolResult:
    resolved, err = resolve_host_path(path, must_exist=True)
    if err or resolved is None:
        return ToolResult(success=False, error=err or "invalid path")
    if not resolved.is_dir():
        return ToolResult(success=False, error=f"not a directory: {resolved}")

    limit = _max_list_entries()
    entries: list[dict[str, object]] = []

    def _walk_dir(directory: Path) -> bool:
        try:
            children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            entries.append({"name": directory.name, "path": str(directory), "error": str(exc)})
            return False
        for child in children:
            if len(entries) >= limit:
                return True
            entries.append(_entry_info(child))
            if recursive and child.is_dir():
                if _walk_dir(child):
                    return True
        return False

    truncated = _walk_dir(resolved)
    return ToolResult(
        success=True,
        result={
            "path": str(resolved),
            "entries": entries,
            "truncated": truncated,
            "limit": limit,
        },
    )


@tool(
    name="host_write_file",
    description=(
        "Create or overwrite a text file under the allowed host roots. "
        "Parent directories are created when needed."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Target file path"},
            "content": {"type": "string", "description": "File content to write"},
            "encoding": {"type": "string", "description": "Text encoding", "default": "utf-8"},
            "append": {
                "type": "boolean",
                "description": "Append instead of overwrite",
                "default": False,
            },
        },
        "required": ["path", "content"],
    },
)
async def host_write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    append: bool = False,
) -> ToolResult:
    resolved, err = resolve_host_path(path, allow_create_parent=True)
    if err or resolved is None:
        return ToolResult(success=False, error=err or "invalid path")

    payload = content if content is not None else ""
    enc = encoding or "utf-8"
    try:
        encoded = payload.encode(enc)
    except UnicodeEncodeError as exc:
        return ToolResult(success=False, error=f"encoding error: {exc}")

    max_bytes = _max_write_bytes()
    if len(encoded) > max_bytes:
        return ToolResult(
            success=False,
            error=f"content too large ({len(encoded)} bytes); max_write_bytes={max_bytes}",
        )

    if resolved.exists() and resolved.is_dir():
        return ToolResult(success=False, error=f"path is a directory: {resolved}")

    try:
        if append and resolved.exists():
            with resolved.open("ab") as fh:
                fh.write(encoded)
        else:
            resolved.write_bytes(encoded)
        size = resolved.stat().st_size
    except OSError as exc:
        return ToolResult(success=False, error=str(exc))

    return ToolResult(
        success=True,
        result={
            "path": str(resolved),
            "bytes_written": len(encoded),
            "size": size,
            "append": bool(append),
        },
    )


@tool(
    name="host_delete_path",
    description=(
        "Delete a file or empty directory under the allowed host roots. "
        "Requires user approval unless approval_token is provided after confirmation. "
        "Set recursive=true to remove a directory tree."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or directory to delete"},
            "recursive": {
                "type": "boolean",
                "description": "Allow deleting non-empty directories",
                "default": False,
            },
            "approval_token": {
                "type": "string",
                "description": "Token from a prior approval_required response after user confirmed",
            },
        },
        "required": ["path"],
    },
)
async def host_delete_path(
    path: str,
    recursive: bool = False,
    approval_token: str | None = None,
) -> ToolResult:
    resolved, err = resolve_host_path(path, must_exist=True)
    if err or resolved is None:
        return ToolResult(success=False, error=err or "invalid path")

    gate = check_approval_gate(
        tool="host_delete_path",
        action="delete",
        summary=f"Delete {'tree' if recursive else 'path'}: {resolved}",
        payload={"path": str(resolved), "recursive": bool(recursive)},
        approval_token=approval_token,
        needs_approval=delete_needs_approval(recursive=recursive),
    )
    if gate is not None:
        return gate

    try:
        if resolved.is_file() or resolved.is_symlink():
            resolved.unlink()
            kind = "file"
        elif resolved.is_dir():
            if recursive:
                shutil.rmtree(resolved)
                kind = "dir_tree"
            else:
                resolved.rmdir()
                kind = "dir"
        else:
            return ToolResult(success=False, error=f"unsupported path type: {resolved}")
    except OSError as exc:
        return ToolResult(success=False, error=str(exc))

    return ToolResult(success=True, result={"path": str(resolved), "deleted": kind})
