"""Agent prompts: `data/ly_next/<prompts_dir>/` first; package `prompt_builtin/` only if enabled."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_data_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_BUILTIN_DIR = Path(__file__).resolve().parent / "prompt_builtin"
_CACHE: dict[str, tuple[float, str]] = {}

_FALLBACK_NATIVE = (
    "You are a helpful assistant with access to function tools registered by the host system. "
    "When a tool can retrieve facts or perform actions needed to answer the user, call it. "
    "After receiving tool results, reason briefly if needed and respond in clear natural language."
)

_FALLBACK_COMPAT_PREAMBLE = (
    "You are a tool-using agent. The host system will execute tools for you.\n\n"
    "Available tools:\n{tools_desc}\n"
)

_FALLBACK_PLAN_PREAMBLE = (
    "You are a tool orchestration AI. Your goal is to solve the problem in minimum steps.\n\n"
    "Available tools:\n{tools_desc}\n"
)

_COMPAT_JSON_RULES = """You MUST output only JSON, no extra text.

When you need to call a tool:
{"type":"tool","name":"<tool_name>","args":{...}}

When you can answer directly:
{"type":"final","final":"..."}

Constraints:
- Only choose from these tools: {tool_names}
- args must be a JSON object"""

_PLAN_JSON_RULES = """Output only JSON (no extra text).

When you need to call a tool:
{"type":"tool","name":"<tool_name>","args":{...}}

When you can answer directly:
{"type":"final","final":"..."}

Constraints:
- Only choose from these tools: {tool_names}
- args must be JSON object
- If a tool returns success=false, try a different approach"""

_FALLBACK_TOOL_MANIFEST = (
    "【宿主已注册的工具】以下名称可通过标准 function calling（tool_calls）调用；"
    "回答用户「有哪些工具」时请罗列这些名称，不要说系统未提供工具。\n{tool_names_csv}"
)


def _prompts_cfg() -> dict[str, Any]:
    raw = config.get("agent.prompts", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _prompts_enabled() -> bool:
    return bool(_prompts_cfg().get("enabled", True))


def _safe_relative_path(raw: str) -> Path | None:
    s = (raw or "").strip().replace("\\", "/")
    if not s or s.startswith("/"):
        return None
    rel = Path(s)
    if any(p == ".." for p in rel.parts):
        return None
    return rel


def _user_prompt_path(rel: Path) -> Path | None:
    cfg = _prompts_cfg()
    sub = str(cfg.get("prompts_dir") or "prompts").strip() or "prompts"
    root = (get_data_root() / sub).resolve()
    with contextlib.suppress(OSError):
        root.mkdir(parents=True, exist_ok=True)
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        logger.warning("[prompts] ignored path outside prompts_dir: %s", rel)
        return None
    return candidate if candidate.is_file() else None


def _builtin_path(rel: Path) -> Path:
    return (_BUILTIN_DIR / rel).resolve()


def _resolved_prompt_path(rel: Path) -> Path | None:
    user = _user_prompt_path(rel)
    if user is not None:
        return user
    if not _prompts_enabled():
        return None
    b = _builtin_path(rel)
    return b if b.is_file() else None


def _load_text(rel: Path) -> str | None:
    path = _resolved_prompt_path(rel)
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.warning("[prompts] read failed %s: %s", path, e)
        return None
    _CACHE[key] = (mtime, text)
    logger.debug("[prompts] loaded %s (%s chars)", path.name, len(text))
    return text


def _apply_placeholders(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, val in mapping.items():
        out = out.replace("{" + key + "}", val)
    return out


def _tools_desc_lines(tools: list[dict[str, Any]]) -> tuple[str, str]:
    lines: list[str] = []
    names: list[str] = []
    for t in tools or ():
        if not isinstance(t, dict):
            continue
        n = str(t.get("name") or "").strip()
        if not n:
            continue
        d = str(t.get("description") or "").strip()
        lines.append(f"- {n}: {d}" if d else f"- {n}")
        names.append(n)
    tools_desc = "\n".join(lines) if lines else "(no tools)"
    return tools_desc, ", ".join(names)


def _preamble_from_config(
    *,
    file_cfg_key: str,
    default_filename: str,
    fallback_template: str,
    ph: dict[str, str],
) -> str:
    cfg = _prompts_cfg()
    fn = str(cfg.get(file_cfg_key) or default_filename).strip() or default_filename
    rel = _safe_relative_path(fn)
    raw = _load_text(rel) if rel is not None else None
    base = (raw or fallback_template).strip()
    return _apply_placeholders(base, ph)


def _join_decision_blocks(
    *,
    tools: list[dict[str, Any]],
    file_cfg_key: str,
    default_filename: str,
    fallback_preamble: str,
    rules: str,
    suffix_template: str,
    suffix_fields: dict[str, str],
) -> str:
    tools_desc, tool_names = _tools_desc_lines(tools)
    preamble = _preamble_from_config(
        file_cfg_key=file_cfg_key,
        default_filename=default_filename,
        fallback_template=fallback_preamble,
        ph={"tools_desc": tools_desc, "tool_names": tool_names},
    )
    body_rules = _apply_placeholders(rules, {"tool_names": tool_names})
    suffix = _apply_placeholders(suffix_template, suffix_fields)
    return "\n\n".join((preamble.strip(), body_rules.strip(), suffix.strip())).strip()


def get_native_system_prefix() -> str:
    cfg = _prompts_cfg()
    name = str(cfg.get("native_system_file") or "native_system.md").strip() or "native_system.md"
    rel = _safe_relative_path(name)
    if rel is None:
        return _FALLBACK_NATIVE
    text = _load_text(rel)
    return text if text else _FALLBACK_NATIVE


def build_compat_decision_prompt(
    *,
    dialog: str,
    tools: list[dict[str, Any]],
    scratchpad: str,
) -> str:
    return _join_decision_blocks(
        tools=tools,
        file_cfg_key="compat_react_preamble_file",
        default_filename="compat_react_preamble.md",
        fallback_preamble=_FALLBACK_COMPAT_PREAMBLE,
        rules=_COMPAT_JSON_RULES,
        suffix_template=("Conversation:\n{dialog}\n\nKnown process (scratchpad):\n{scratchpad}"),
        suffix_fields={"dialog": dialog, "scratchpad": scratchpad},
    )


def build_plan_decision_prompt(
    *, question: str, tools: list[dict[str, Any]], scratchpad: str
) -> str:
    return _join_decision_blocks(
        tools=tools,
        file_cfg_key="plan_decision_preamble_file",
        default_filename="plan_decision_preamble.md",
        fallback_preamble=_FALLBACK_PLAN_PREAMBLE,
        rules=_PLAN_JSON_RULES,
        suffix_template=(
            "Question:\n{question}\n\nKnown process (for reference, don't repeat):\n{scratchpad}"
        ),
        suffix_fields={"question": question, "scratchpad": scratchpad},
    )


def format_tool_manifest_block(tool_names: list[str]) -> str:
    csv = ", ".join(tool_names)
    preamble = _preamble_from_config(
        file_cfg_key="tool_manifest_file",
        default_filename="tool_manifest_suffix.md",
        fallback_template=_FALLBACK_TOOL_MANIFEST,
        ph={"tool_names_csv": csv},
    )
    return "\n\n" + preamble
