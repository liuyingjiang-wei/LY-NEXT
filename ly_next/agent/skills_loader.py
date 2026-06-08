"""Discover agent SKILL.md files."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE | re.IGNORECASE)

_cache: dict[str, Any] = {"at": 0.0, "skills": []}


@dataclass(frozen=True)
class SkillInfo:
    id: str
    name: str
    description: str
    path: str
    rel_path: str


def _skills_cfg() -> dict[str, Any]:
    raw = config.get("agent.skills", {}) or {}
    return raw if isinstance(raw, dict) else {}


def skills_enabled() -> bool:
    return bool(_skills_cfg().get("enabled", True))


def _resolve_skill_dirs() -> list[Path]:
    root = get_project_root()
    raw = _skills_cfg().get("dirs")
    rels: list[str] = []
    if isinstance(raw, list) and raw:
        rels = [str(x).strip() for x in raw if str(x).strip()]
    else:
        rels = [".agents/skills", "skills"]

    out: list[Path] = []
    seen: set[str] = set()
    for rel in rels:
        p = Path(rel)
        if not p.is_absolute():
            p = (root / p).resolve()
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_dir():
            out.append(p)
    return out


def _parse_frontmatter(text: str) -> tuple[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return "", _first_paragraph(text)
    fm = m.group(1)
    body = text[m.end() :]
    name = ""
    desc = ""
    nm = _NAME_RE.search(fm)
    if nm:
        name = nm.group(1).strip().strip("\"'")
    dm = _DESC_RE.search(fm)
    if dm:
        desc = dm.group(1).strip().strip("\"'")
    return name, desc or _first_paragraph(body)


def _first_paragraph(body: str) -> str:
    lines: list[str] = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if not s:
            if lines:
                break
            continue
        if s.startswith("#"):
            continue
        lines.append(s)
        if len(" ".join(lines)) > 240:
            break
    text = " ".join(lines).strip()
    return text[:400] if len(text) > 400 else text


def _skill_id(skill_path: Path, base: Path) -> str:
    rel = skill_path.relative_to(base)
    parent = rel.parent
    if parent == Path("."):
        return skill_path.parent.name
    return str(parent).replace("\\", "/")


def discover_skills(*, force: bool = False) -> list[SkillInfo]:
    if not skills_enabled():
        return []

    ttl = max(5, int(_skills_cfg().get("cache_ttl_seconds", 30) or 30))
    now = time.time()
    if not force and _cache["skills"] and now - float(_cache["at"]) < ttl:
        return list(_cache["skills"])

    found: dict[str, SkillInfo] = {}
    for base in _resolve_skill_dirs():
        for skill_file in sorted(base.rglob("SKILL.md")):
            if not skill_file.is_file():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("[skills] cannot read %s: %s", skill_file, exc)
                continue
            name, desc = _parse_frontmatter(text)
            sid = _skill_id(skill_file, base)
            if not name:
                name = sid.split("/")[-1] or sid
            if sid in found:
                continue
            rel = str(skill_file.relative_to(get_project_root())).replace("\\", "/")
            found[sid] = SkillInfo(
                id=sid,
                name=name,
                description=desc or "(no description)",
                path=str(skill_file.resolve()),
                rel_path=rel,
            )

    skills = sorted(found.values(), key=lambda s: s.id.lower())
    _cache["at"] = now
    _cache["skills"] = skills
    return skills


def get_skill_by_id(skill_id: str) -> SkillInfo | None:
    needle = str(skill_id or "").strip().replace("\\", "/")
    if not needle:
        return None
    for item in discover_skills():
        if item.id == needle or item.rel_path == needle:
            return item
    return None


def read_skill_content(
    skill_id: str, *, max_chars: int | None = None
) -> tuple[str | None, str | None]:
    item = get_skill_by_id(skill_id)
    if item is None:
        return None, f"skill not found: {skill_id}"
    limit = max_chars
    if limit is None:
        limit = max(4000, int(_skills_cfg().get("max_read_chars", 32000) or 32000))
    try:
        text = Path(item.path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, str(exc)
    if len(text) > limit:
        text = (
            text[:limit]
            + f"\n\n… [truncated at {limit} chars; use host_read_file for full file if needed]"
        )
    return text, None


def format_skills_summary(*, max_items: int | None = None) -> str:
    skills = discover_skills()
    if not skills:
        return ""
    cap = max_items
    if cap is None:
        cap = max(1, int(_skills_cfg().get("max_summary_skills", 24) or 24))
    lines = [
        "可用 Skills（任务相关时先用 list_skills / read_skill 加载完整说明，再按 SKILL 执行）：",
    ]
    for item in skills[:cap]:
        lines.append(f"- {item.id}: {item.name} — {item.description}")
    if len(skills) > cap:
        lines.append(f"… 另有 {len(skills) - cap} 个 skill，请 list_skills 查看。")
    return "\n".join(lines)


def invalidate_skills_cache() -> None:
    _cache["at"] = 0.0
    _cache["skills"] = []
