from __future__ import annotations

import re
from pathlib import Path

from ly_next.tools.base import ToolResult, tool
from ly_next.tools.host_sandbox import host_int_limit, resolve_host_path


def _max_matches() -> int:
    return host_int_limit("tools.host.grep_max_matches", 100, minimum=1, maximum=500)


def _max_files() -> int:
    return host_int_limit("tools.host.grep_max_files", 2000, minimum=1, maximum=20_000)


def _iter_files(root: Path, glob: str | None) -> list[Path]:
    if root.is_file():
        return [root]
    pattern = (glob or "*").strip() or "*"
    if root.is_dir():
        return sorted(root.rglob(pattern))[: _max_files()]
    return []


def _grep_file(
    path: Path,
    regex: re.Pattern[str],
    *,
    context_lines: int,
) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    hits: list[dict[str, object]] = []
    ctx = max(0, min(int(context_lines), 20))
    for i, line in enumerate(lines):
        if not regex.search(line):
            continue
        start = max(0, i - ctx)
        end = min(len(lines), i + ctx + 1)
        snippet = "\n".join(f"{j + 1}:{lines[j]}" for j in range(start, end))
        hits.append(
            {
                "path": str(path),
                "line": i + 1,
                "text": line,
                "context": snippet,
            }
        )
    return hits


@tool(
    name="grep_code",
    description=(
        "Search text under allowed host roots with a regex. "
        "Use for finding symbols, config keys, or log lines. "
        "For reading a known file, prefer read_file_range or host_read_file."
    ),
    category="host",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {
                "type": "string",
                "description": "File or directory under host roots",
                "default": ".",
            },
            "glob": {
                "type": "string",
                "description": "When path is a directory, glob for files (e.g. *.py)",
                "default": "*",
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context around each match",
                "default": 2,
            },
        },
        "required": ["pattern"],
    },
)
async def grep_code(
    pattern: str,
    path: str = ".",
    glob: str = "*",
    context_lines: int = 2,
) -> ToolResult:
    pat = (pattern or "").strip()
    if not pat:
        return ToolResult(success=False, error="pattern is required")
    try:
        regex = re.compile(pat)
    except re.error as exc:
        return ToolResult(success=False, error=f"invalid regex: {exc}")

    resolved, err = resolve_host_path(path, must_exist=True)
    if err or resolved is None:
        return ToolResult(success=False, error=err or "invalid path")

    limit = _max_matches()
    matches: list[dict[str, object]] = []
    truncated = False
    for fp in _iter_files(resolved, glob):
        if not fp.is_file():
            continue
        for hit in _grep_file(fp, regex, context_lines=context_lines):
            matches.append(hit)
            if len(matches) >= limit:
                truncated = True
                break
        if truncated:
            break

    return ToolResult(
        success=True,
        result={
            "pattern": pat,
            "root": str(resolved),
            "matches": matches,
            "truncated": truncated,
            "limit": limit,
        },
    )
