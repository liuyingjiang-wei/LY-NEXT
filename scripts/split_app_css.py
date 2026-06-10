#!/usr/bin/env python3
"""Move feature-scoped CSS blocks from app.css into split stylesheets."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".workbench-src" / "src"
APP = ROOT / "app.css"

# 1-based inclusive line ranges to extract (verified against current app.css)
EXTRACT = {
    "styles/status.css": [
        (625, 718),  # kpi, resource, ring
        (1041, 1126),  # spark, net
    ],
    "styles/api.css": [
        (1128, 1208),  # api explorer (not global form controls)
    ],
    "styles/tasks.css": [
        (747, 791),  # tasks-panel toolbar/table
        (759, 767),  # btn-task-primary (overlaps - handled by dedupe)
        (981, 1022),  # task-actions, btn-inline, task-status
    ],
    "styles/runs.css": [
        (798, 951),  # runs-panel tables/events
    ],
}

# settings.css gets appended blocks (prefix-based second pass)
SETTINGS_PREFIXES = (
    ".settings-",
    ".plugins-",
    ".host-approval",
    ".agent-preset",
    ".qq-",
    ".tg-",
    ".wb-settings",
    ".btn-secondary",
    ".btn-save-settings",
    ".match-rules",
    ".mcp-server",
    ".mcp-servers",
)


def lines_to_text(lines: list[str], ranges: list[tuple[int, int]]) -> str:
    chunks: list[str] = []
    seen: set[int] = set()
    for start, end in ranges:
        for i in range(start, end + 1):
            if i in seen:
                continue
            seen.add(i)
            chunks.append(lines[i - 1])
    return "".join(chunks).strip() + "\n"


def extract_by_prefix(css: str) -> str:
    """Extract rule blocks whose first selector line matches a prefix."""
    out: list[str] = []
    i = 0
    n = len(css)
    while i < n:
        if css[i] == ".":
            j = css.find("{", i)
            if j == -1:
                break
            selector = css[i:j].strip()
            first = selector.split(",")[0].strip()
            if any(first.startswith(p) for p in SETTINGS_PREFIXES):
                depth = 0
                k = j
                while k < n:
                    if css[k] == "{":
                        depth += 1
                    elif css[k] == "}":
                        depth -= 1
                        if depth == 0:
                            out.append(css[i : k + 1].strip() + "\n\n")
                            i = k + 1
                            break
                    k += 1
                else:
                    break
                continue
        i += 1
    return "".join(out).strip() + ("\n" if out else "")


def remove_line_ranges(lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    drop: set[int] = set()
    for start, end in ranges:
        drop.update(range(start, end + 1))
    return [line for idx, line in enumerate(lines, start=1) if idx not in drop]


def remove_prefix_blocks(css: str) -> str:
    i = 0
    n = len(css)
    parts: list[str] = []
    while i < n:
        if css[i] == ".":
            j = css.find("{", i)
            if j == -1:
                parts.append(css[i:])
                break
            selector = css[i:j].strip()
            first = selector.split(",")[0].strip()
            if any(first.startswith(p) for p in SETTINGS_PREFIXES):
                depth = 0
                k = j
                while k < n:
                    if css[k] == "{":
                        depth += 1
                    elif css[k] == "}":
                        depth -= 1
                        if depth == 0:
                            i = k + 1
                            break
                    k += 1
                else:
                    parts.append(css[i:])
                    break
                continue
        # copy until next potential rule at line start
        next_dot = css.find("\n.", i)
        if next_dot == -1:
            parts.append(css[i:])
            break
        parts.append(css[i : next_dot + 1])
        i = next_dot + 1
    return "".join(parts)


def main() -> None:
    lines = APP.read_text(encoding="utf-8").splitlines(keepends=True)
    all_ranges: list[tuple[int, int]] = []
    for ranges in EXTRACT.values():
        all_ranges.extend(ranges)

    for rel, ranges in EXTRACT.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"/* split from app.css — {rel} */\n\n"
        path.write_text(header + lines_to_text(lines, ranges), encoding="utf-8")
        print(f"wrote {path}")

    # settings.css append: lead panel + prefix blocks from remaining app.css
    remaining_lines = remove_line_ranges(lines, all_ranges)
    remaining = "".join(remaining_lines)

    settings_extra = ""
    if ".settings-lead-panel" in remaining:
        settings_extra += (
            ".settings-lead-panel .settings-lead,\n.api-page-panel .api {\n  margin: 0;\n}\n\n"
        )
    settings_extra += ".settings-lead { margin: 0 0 14px; max-width: 52rem; }\n\n"
    settings_extra += extract_by_prefix(remaining)

    settings_path = ROOT / "styles" / "settings.css"
    existing = settings_path.read_text(encoding="utf-8") if settings_path.exists() else ""
    settings_path.write_text(
        existing.rstrip()
        + "\n\n/* --- split from app.css --- */\n\n"
        + settings_extra.strip()
        + "\n",
        encoding="utf-8",
    )
    print(f"appended to {settings_path}")

    # shrink app.css
    shrunk_lines = remove_line_ranges(lines, all_ranges)
    shrunk = "".join(shrunk_lines)
    shrunk = remove_prefix_blocks(shrunk)
    # clean excessive blank lines
    while "\n\n\n\n" in shrunk:
        shrunk = shrunk.replace("\n\n\n\n", "\n\n\n")
    APP.write_text(shrunk, encoding="utf-8")
    print(f"trimmed {APP}")


if __name__ == "__main__":
    main()
