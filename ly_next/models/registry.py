"""Named LLM model registry — ly-ask style registration on top of format factories."""

from __future__ import annotations

import copy
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.models.migrate import ensure_llm_models_migrated

logger = get_logger(__name__)

MODEL_FORMATS: frozenset[str] = frozenset({"openai", "openai_compat", "anthropic", "ollama"})

MODEL_FORMAT_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "openai_compat": "OpenAI 兼容",
    "anthropic": "Anthropic",
    "ollama": "Ollama",
}

_SETTINGS_MASK = "***"
_SECRET_KEYS = frozenset(
    {"api-key", "access-token", "password", "auth-token", "authorization", "x-api-key"}
)


def _is_secret_key(key: str) -> bool:
    return str(key).lower().replace("_", "-") in _SECRET_KEYS or key == "api_key"


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any]:
    fmt = str(raw.get("format") or "openai").strip().lower()
    if fmt == "openai-compatible":
        fmt = "openai_compat"
    if fmt not in MODEL_FORMATS:
        raise ValueError(f"不支持的格式: {fmt}，允许: {', '.join(sorted(MODEL_FORMATS))}")
    name = str(raw["name"]).strip()
    model_id = str(raw.get("model") or "").strip()
    if not name:
        raise ValueError("模型名称不能为空")
    if not model_id:
        raise ValueError("模型 ID 不能为空")
    entry: dict[str, Any] = {
        "name": name,
        "format": fmt,
        "model": model_id,
        "api_key": str(raw.get("api_key") or ""),
        "base_url": str(raw.get("base_url") or ""),
    }
    for key in ("auth_mode", "auth_header_name", "token_field", "path"):
        if raw.get(key) not in (None, ""):
            entry[key] = raw[key]
    if isinstance(raw.get("model_aliases"), dict):
        entry["model_aliases"] = raw["model_aliases"]
    if isinstance(raw.get("headers"), dict):
        entry["headers"] = raw["headers"]
    return entry


class ModelRegistry:
    _entries: dict[str, dict[str, Any]] = {}
    _loaded = False

    @classmethod
    def ensure_loaded(cls) -> None:
        if cls._loaded:
            return
        ensure_llm_models_migrated(save=True)
        cls._reload_from_config()
        cls._loaded = True

    @classmethod
    def reload(cls) -> None:
        from ly_next.models.factory import LLMFactory

        cls._loaded = False
        LLMFactory.clear_cache()
        cls.ensure_loaded()

    @classmethod
    def _reload_from_config(cls) -> None:
        raw = config.get("llm.models", []) or []
        entries: dict[str, dict[str, Any]] = {}
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                try:
                    norm = _normalize_entry(item)
                    entries[norm["name"]] = norm
                except ValueError as e:
                    logger.warning("Skip invalid llm.models entry: %s", e)
        cls._entries = entries

    @classmethod
    def list_names(cls) -> list[str]:
        cls.ensure_loaded()
        return list(cls._entries.keys())

    @classmethod
    def get_entry(cls, name: str | None) -> dict[str, Any] | None:
        cls.ensure_loaded()
        if not name:
            return None
        return cls._entries.get(str(name).strip())

    @classmethod
    def default_name(cls) -> str:
        cls.ensure_loaded()
        for key in ("llm.default_model", "llm.default_provider"):
            val = str(config.get(key) or "").strip()
            if val and val in cls._entries:
                return val
        if cls._entries:
            return next(iter(cls._entries))
        return str(config.get("llm.default_provider") or "openai")

    @classmethod
    def set_default_name(cls, name: str, *, save: bool = True) -> None:
        key = name.strip()
        if key not in cls._entries:
            raise ValueError(f"模型 '{key}' 未注册")
        llm_block = dict(config.get("llm", {}) or {})
        llm_block["default_model"] = key
        llm_block["default_provider"] = key
        config.set("llm", llm_block, save=save)
        logger.info("Default LLM model set to %s", key)

    @classmethod
    def _persist_entries(cls, entries: list[dict[str, Any]], *, save: bool = True) -> None:
        llm_block = dict(config.get("llm", {}) or {})
        llm_block["models"] = entries
        config.set("llm", llm_block, save=save)
        cls._entries = {e["name"]: e for e in entries}

    @classmethod
    def merge_update(
        cls,
        name: str,
        *,
        format: str,
        api_key: str,
        base_url: str,
        model: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cls.ensure_loaded()
        key = name.strip()
        existing = cls._entries.get(key) or {}
        resolved_key = api_key.strip()
        if not resolved_key or resolved_key == _SETTINGS_MASK:
            resolved_key = str(existing.get("api_key") or "")
        payload: dict[str, Any] = {
            "name": key,
            "format": format or existing.get("format") or "openai",
            "api_key": resolved_key,
            "base_url": base_url.strip() or str(existing.get("base_url") or ""),
            "model": model.strip() or str(existing.get("model") or ""),
        }
        if extra:
            payload.update(extra)
        norm = _normalize_entry(payload)
        if norm["format"] not in ("ollama",) and not norm.get("api_key"):
            if norm["format"] == "openai_compat" and str(norm.get("base_url") or "").strip():
                pass
            elif norm["format"] != "openai_compat" or str(
                norm.get("api_key") or ""
            ).lower() not in (
                "not-needed",
                "not_needed",
            ):
                raise ValueError("API Key 不能为空（留空表示保留原 Key）")
        return norm

    @classmethod
    def upsert(cls, entry: dict[str, Any], *, save: bool = True) -> dict[str, Any]:
        cls.ensure_loaded()
        norm = _normalize_entry(entry)
        entries = [e for e in cls._entries.values() if e["name"] != norm["name"]]
        entries.append(norm)
        cls._persist_entries(entries, save=save)
        if save:
            from ly_next.models.factory import LLMFactory

            LLMFactory.clear_cache()
        return norm

    @classmethod
    def remove(cls, name: str, *, save: bool = True) -> None:
        cls.ensure_loaded()
        key = name.strip()
        if key not in cls._entries:
            raise ValueError(f"模型 '{key}' 不存在")
        if len(cls._entries) <= 1:
            raise ValueError("至少保留一个已注册模型")
        entries = [e for e in cls._entries.values() if e["name"] != key]
        cls._persist_entries(entries, save=save)
        if cls.default_name() == key:
            cls.set_default_name(entries[0]["name"], save=save)
        if save:
            from ly_next.models.factory import LLMFactory

            LLMFactory.clear_cache()

    @classmethod
    def mask_entry_for_api(cls, entry: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(entry)
        if out.get("api_key"):
            out["api_key"] = _SETTINGS_MASK
            out["has_api_key"] = True
        else:
            out["has_api_key"] = False
        out["format_label"] = MODEL_FORMAT_LABELS.get(out.get("format", ""), out.get("format"))
        return out

    @classmethod
    def model_info(cls, name: str) -> dict[str, Any]:
        cls.ensure_loaded()
        key = name.strip()
        entry = cls._entries.get(key)
        if not entry:
            raise ValueError(f"模型 '{key}' 未注册")
        info = cls.mask_entry_for_api(entry)
        info["is_default"] = key == cls.default_name()
        info["can_remove"] = len(cls._entries) > 1
        return info

    @classmethod
    def list_model_infos(cls) -> list[dict[str, Any]]:
        cls.ensure_loaded()
        default = cls.default_name()
        out: list[dict[str, Any]] = []
        for name in sorted(cls._entries):
            info = cls.model_info(name)
            info["is_default"] = name == default
            out.append(info)
        return out

    @classmethod
    def entry_for_edit(cls, name: str) -> dict[str, Any]:
        cls.ensure_loaded()
        key = name.strip()
        entry = cls._entries.get(key)
        if not entry:
            raise ValueError(f"模型 '{key}' 未注册")
        return {
            "name": key,
            "format": entry.get("format", "openai"),
            "base_url": entry.get("base_url", ""),
            "model": entry.get("model", ""),
            "has_api_key": bool(entry.get("api_key")) or entry.get("format") == "ollama",
            "auth_mode": entry.get("auth_mode", "bearer"),
            "auth_header_name": entry.get("auth_header_name", ""),
            "token_field": entry.get("token_field", ""),
            "is_default": key == cls.default_name(),
        }

    @classmethod
    def build_client_kwargs(
        cls,
        name: str | None = None,
        *,
        model_override: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        cls.ensure_loaded()
        key = (name or cls.default_name()).strip()
        entry = cls._entries.get(key)
        if not entry:
            raise ValueError(f"模型 '{key}' 未注册，请在工作台添加")
        kw: dict[str, Any] = dict(entry)
        kw["registry_name"] = key
        kw["provider"] = entry.get("format")
        if model_override and str(model_override).strip():
            kw["model"] = str(model_override).strip()
        if timeout is not None:
            kw["timeout"] = timeout
        req_timeout = config.get("llm.request_timeout")
        if "timeout" not in kw and req_timeout is not None:
            kw["timeout"] = int(req_timeout)
        return kw
