"""Bot global persona — persisted to data/ly_next/bot_persona.json."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ly_next.core.config import config, get_data_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

PERSONA_FILENAME = "bot_persona.json"

_DEFAULT_PERSONA_TEXT = (
    "你是 LY-NEXT 工作台里的智能助手。性格友善、表达清晰，愿意认真帮用户解决问题。\n\n"
    "【回复风格】\n"
    "用简洁自然的中文回答；需要列表时用短句，避免冗长套话。\n\n"
    "【禁忌与边界】\n"
    "不要编造未经验证的事实；不要声称自己是其他产品或真人。"
)

CHANNEL_BRIDGE_KEYS: dict[str, str] = {
    "qq": "onebot11",
    "telegram": "telegram",
    "wechat": "wechat_oc",
}

_prompt_text_cache: tuple[float, str] | None = None


class PersonaOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    bot_name: str = Field(default="", max_length=64)
    persona: str = Field(default="", max_length=20000)
    example_dialogues: str = Field(default="", max_length=12000)
    replace: bool = False


class BotPersona(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    bot_name: str = Field(default="小LY", max_length=64)
    trigger_names: str = Field(default="", max_length=256)
    persona: str = Field(default="", max_length=20000)
    example_dialogues: str = Field(default="", max_length=12000)


def persona_file_path() -> Any:
    return get_data_root() / PERSONA_FILENAME


def _persona_file_mtime() -> float:
    path = persona_file_path()
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def invalidate_persona_cache() -> None:
    global _prompt_text_cache
    _prompt_text_cache = None


def _config_persona_defaults() -> dict[str, Any]:
    raw = config.get("agent.persona", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    text = str(raw.get("persona") or "").strip()
    return {
        "enabled": bool(raw.get("enabled", True)),
        "bot_name": str(raw.get("bot_name") or "小LY").strip()[:64] or "小LY",
        "trigger_names": str(raw.get("trigger_names") or ""),
        "persona": text or _DEFAULT_PERSONA_TEXT,
        "example_dialogues": str(raw.get("example_dialogues") or "").strip(),
    }


def flatten_persona_record(raw: dict[str, Any]) -> BotPersona:
    base = {**_config_persona_defaults(), **{k: v for k, v in raw.items() if v is not None}}
    return BotPersona(
        enabled=bool(base.get("enabled", True)),
        bot_name=str(base.get("bot_name") or "小LY").strip()[:64] or "小LY",
        trigger_names=str(base.get("trigger_names") or ""),
        persona=str(base.get("persona") or _DEFAULT_PERSONA_TEXT).strip() or _DEFAULT_PERSONA_TEXT,
        example_dialogues=str(base.get("example_dialogues") or "").strip(),
    )


def _ensure_file() -> None:
    path = persona_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        slim = flatten_persona_record(_config_persona_defaults())
        path.write_text(slim.model_dump_json(indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_persona() -> BotPersona:
    _ensure_file()
    path = persona_file_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return flatten_persona_record(raw)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("[persona] read failed, using defaults: %s", e)
    return flatten_persona_record(_config_persona_defaults())


def save_persona(data: BotPersona) -> BotPersona:
    _ensure_file()
    slim = BotPersona(
        enabled=data.enabled,
        bot_name=data.bot_name.strip() or "小LY",
        trigger_names=data.trigger_names,
        persona=data.persona.strip() or _DEFAULT_PERSONA_TEXT,
        example_dialogues=data.example_dialogues.strip(),
    )
    persona_file_path().write_text(
        slim.model_dump_json(indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    invalidate_persona_cache()
    logger.info("[persona] saved bot persona")
    return slim


def _parse_override(raw: Any) -> PersonaOverride | None:
    if not isinstance(raw, dict):
        return None
    try:
        ov = PersonaOverride.model_validate(raw)
    except ValueError:
        return None
    if not ov.enabled:
        return None
    if not (ov.bot_name.strip() or ov.persona.strip() or ov.example_dialogues.strip()):
        return None
    return ov


def _channel_persona_override(channel: str | None) -> PersonaOverride | None:
    ch = str(channel or "").strip().lower()
    bridge_key = CHANNEL_BRIDGE_KEYS.get(ch)
    if not bridge_key:
        return None
    bridge = config.get(f"bridge.{bridge_key}", {}) or {}
    if not isinstance(bridge, dict):
        return None
    return _parse_override(bridge.get("persona_override"))


def merge_persona_layers(base: BotPersona, override: PersonaOverride | None) -> BotPersona:
    if override is None:
        return base
    bot_name = override.bot_name.strip() or base.bot_name
    persona = base.persona
    if override.persona.strip():
        persona = (
            override.persona.strip()
            if override.replace
            else f"{persona}\n\n{override.persona.strip()}"
        )
    examples = base.example_dialogues
    if override.example_dialogues.strip():
        examples = (
            override.example_dialogues.strip()
            if override.replace
            else f"{examples}\n\n{override.example_dialogues.strip()}".strip()
        )
    return BotPersona(
        enabled=base.enabled,
        bot_name=bot_name,
        trigger_names=base.trigger_names,
        persona=persona.strip() or base.persona,
        example_dialogues=examples.strip(),
    )


async def load_thread_persona_override(thread_id: str | None) -> PersonaOverride | None:
    tid = str(thread_id or "").strip()
    if not tid:
        return None
    from ly_next.core.thread_persistence import get_thread

    row = await get_thread(tid)
    if not row:
        return None
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return _parse_override(meta.get("persona_override"))


async def resolve_effective_persona(
    *,
    channel: str | None = None,
    thread_id: str | None = None,
    persona_override: dict[str, Any] | None = None,
) -> BotPersona:
    effective = load_persona()
    effective = merge_persona_layers(effective, _channel_persona_override(channel))
    thread_ov = await load_thread_persona_override(thread_id)
    if thread_ov is not None:
        effective = merge_persona_layers(effective, thread_ov)
    elif persona_override is not None:
        req_ov = _parse_override(persona_override)
        if req_ov is not None:
            effective = merge_persona_layers(effective, req_ov)
    return effective


def persona_to_prompt_text(data: BotPersona | None = None) -> str:
    global _prompt_text_cache
    mtime = _persona_file_mtime()
    use_cache = data is None
    if use_cache and _prompt_text_cache and _prompt_text_cache[0] == mtime:
        return _prompt_text_cache[1]

    p = data or load_persona()
    if not p.enabled:
        text = "（未启用人设覆盖，使用内置默认规范）"
    else:
        blocks: list[str] = []
        if p.bot_name.strip():
            blocks.append(f"名称：{p.bot_name.strip()}")
        if p.persona.strip():
            blocks.append(p.persona.strip())
        if p.example_dialogues.strip():
            blocks.append("【示例对话】\n" + p.example_dialogues.strip())
        text = "\n\n".join(blocks) if blocks else "（人设内容为空）"

    if use_cache:
        _prompt_text_cache = (mtime, text)
    return text


async def resolve_persona_system_prefix(
    *,
    channel: str | None = None,
    thread_id: str | None = None,
    persona_override: dict[str, Any] | None = None,
) -> str:
    effective = await resolve_effective_persona(
        channel=channel,
        thread_id=thread_id,
        persona_override=persona_override,
    )
    if not effective.enabled:
        return ""
    return persona_to_prompt_text(effective)


def combine_native_system_prefix(persona_block: str = "") -> str:
    from ly_next.agent.prompt_templates import get_native_system_prefix

    native = get_native_system_prefix()
    persona = str(persona_block or "").strip()
    if persona:
        return f"## Bot 人设（最高优先级）\n{persona}\n\n{native}"
    return native
