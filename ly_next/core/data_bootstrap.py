"""Seed missing runtime files under ``data/ly_next`` (never overwrite user edits)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PKG_ROOT = Path(__file__).resolve().parent.parent
_BUILTIN_PROMPTS = _PKG_ROOT / "agent" / "prompt_builtin"
_SEED_KNOWLEDGE = _PKG_ROOT / "data_seed" / "knowledge"


def bootstrap_data_assets(
    data_root: Path,
    *,
    prompts_subdir: str = "prompts",
) -> dict[str, int]:
    """Ensure prompts and knowledge starter files exist. Returns per-category create counts."""
    created = {"prompts": 0, "knowledge": 0}
    root = data_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    sub = (prompts_subdir or "prompts").strip().replace("\\", "/").strip("/") or "prompts"
    if ".." in Path(sub).parts:
        logger.warning("[data] ignored unsafe prompts_subdir: %s", prompts_subdir)
        sub = "prompts"

    prompts_dir = (root / sub).resolve()
    prompts_dir.mkdir(parents=True, exist_ok=True)
    if _BUILTIN_PROMPTS.is_dir():
        for src in sorted(_BUILTIN_PROMPTS.glob("*.md")):
            dst = prompts_dir / src.name
            if dst.is_file():
                continue
            shutil.copy2(src, dst)
            created["prompts"] += 1

    knowledge_dir = (root / "knowledge").resolve()
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    if _SEED_KNOWLEDGE.is_dir():
        for src in sorted(_SEED_KNOWLEDGE.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(_SEED_KNOWLEDGE)
            dst = knowledge_dir / rel
            if dst.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            created["knowledge"] += 1

    total = created["prompts"] + created["knowledge"]
    if total:
        logger.info(
            "[data] bootstrapped %s prompt(s), %s knowledge file(s) under %s",
            created["prompts"],
            created["knowledge"],
            root,
        )
    return created
