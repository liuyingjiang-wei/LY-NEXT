"""User config migration CLI (`ly config migrate`)."""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.parse import urlparse

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.models.migrate import _LEGACY_FORMAT_BLOCKS, ensure_llm_models_migrated

logger = get_logger(__name__)

_LEGACY_LLM_TOP_KEYS = tuple(block_key for _, block_key in _LEGACY_FORMAT_BLOCKS)


def is_self_service_llm_url(base_url: str, *, port: int | None = None) -> bool:
    """True when base_url points at this LY-NEXT HTTP port (common misconfiguration)."""
    raw = str(base_url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        return False
    svc_port = int(port if port is not None else config.get("server.port") or 8000)
    url_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return url_port == svc_port


def _fix_compat_base_urls(*, port: int) -> list[str]:
    fixes: list[str] = []
    models = config.get("llm.models")
    if isinstance(models, list):
        changed = False
        for entry in models:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("format") or "").strip().lower() != "openai_compat":
                continue
            base = str(entry.get("base_url") or "").strip()
            if not is_self_service_llm_url(base, port=port):
                continue
            entry["base_url"] = "http://127.0.0.1:11434/v1"
            name = str(entry.get("name") or "openai_compat")
            fixes.append(f"llm.models[{name}].base_url → Ollama /v1")
            changed = True
        if changed:
            config.set("llm.models", models, save=False)

    for _, block_key in _LEGACY_FORMAT_BLOCKS:
        block = config.get(block_key)
        if not isinstance(block, dict):
            continue
        base = str(block.get("base_url") or "").strip()
        if is_self_service_llm_url(base, port=port):
            block = dict(block)
            block["base_url"] = "http://127.0.0.1:11434/v1"
            config.set(block_key, block, save=False)
            fixes.append(f"{block_key}.base_url → Ollama /v1")
    return fixes


def _prune_legacy_llm_blocks() -> list[str]:
    models = config.get("llm.models")
    if not isinstance(models, list) or not models:
        return []
    removed: list[str] = []
    root = config.to_dict()
    for key in _LEGACY_LLM_TOP_KEYS:
        if key in root and root.get(key) is not None:
            del config._config[key]
            removed.append(key)
    if removed:
        config._cache.clear()
    return removed


def run_config_migrate(*, save: bool = True, prune_legacy: bool = True) -> dict[str, Any]:
    """Migrate legacy LLM blocks, fix self-referential compat URLs, optionally prune legacy keys."""
    port = int(config.get("server.port") or 8000)
    changes: list[str] = []

    if ensure_llm_models_migrated(save=False):
        changes.append("已将 legacy *_llm 合并进 llm.models")

    url_fixes = _fix_compat_base_urls(port=port)
    changes.extend(url_fixes)

    removed: list[str] = []
    if prune_legacy:
        removed = _prune_legacy_llm_blocks()
        if removed:
            changes.append(f"已移除遗留块：{', '.join(removed)}")

    saved = False
    if save and changes:
        config.save()
        saved = True
        logger.info("Config migrate applied %s change(s)", len(changes))

    return {
        "ok": True,
        "saved": saved,
        "changes": changes,
        "removed_legacy_keys": removed,
        "config_path": str(config.config_file),
    }


def run_config_migrate_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ly config migrate",
        description="合并 legacy LLM 配置块、修正错误的 compat Base URL，并清理已迁移的 *_llm 键",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅报告将要执行的变更，不写回 config.yaml",
    )
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="保留顶层 openai_llm / ollama_llm 等遗留块（仅合并到 llm.models）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    result = run_config_migrate(save=not args.dry_run, prune_legacy=not args.keep_legacy)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        path = result.get("config_path") or "config.yaml"
        if not result["changes"]:
            print(f"无需迁移：{path} 已是最新结构。")
        else:
            prefix = "[dry-run] " if args.dry_run else ""
            print(f"{prefix}已处理 {path}：")
            for line in result["changes"]:
                print(f"  · {line}")
            if args.dry_run:
                print("（未写入磁盘，去掉 --dry-run 以保存）")
            else:
                print("请重启 uv run ly 使全部变更生效。")

    return 0
