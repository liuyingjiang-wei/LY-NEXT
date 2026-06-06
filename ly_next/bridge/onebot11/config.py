from __future__ import annotations

from dataclasses import dataclass

from ly_next.bridge.onebot11.paths import DEFAULT_ONEBOT11_WS_PATHS, merge_ws_paths
from ly_next.core.config import config


@dataclass(frozen=True)
class OneBot11Triggers:
    private: bool
    group: bool
    group_at_only: bool
    prefixes: tuple[str, ...]
    ignore_self: bool


@dataclass(frozen=True)
class OneBot11AutoReply:
    enabled: bool
    mode: str
    temperature: float
    max_tokens: int
    provider: str | None
    model: str | None


@dataclass(frozen=True)
class OneBot11Settings:
    enabled: bool
    access_token: str
    ws_paths: tuple[str, ...]
    auto_reply: OneBot11AutoReply
    triggers: OneBot11Triggers


def _str_list(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        s = value.strip()
        return (s,) if s else ()
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            s = str(item).strip()
            if s:
                out.append(s)
        return tuple(out)
    return ()


def get_onebot11_settings() -> OneBot11Settings:
    raw = config.get("bridge.onebot11", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    auto = raw.get("auto_reply", {}) or {}
    if not isinstance(auto, dict):
        auto = {}
    trig = raw.get("triggers", {}) or {}
    if not isinstance(trig, dict):
        trig = {}
    paths = merge_ws_paths(_str_list(raw.get("ws_paths")) or DEFAULT_ONEBOT11_WS_PATHS[:1])
    token = str(raw.get("access_token") or "").strip()
    if not token:
        legacy = config.get("onebotv11", {}) or {}
        if isinstance(legacy, dict):
            token = str(legacy.get("access_token") or "").strip()
    return OneBot11Settings(
        enabled=bool(raw.get("enabled", True)),
        access_token=token,
        ws_paths=tuple(paths),
        auto_reply=OneBot11AutoReply(
            enabled=bool(auto.get("enabled", True)),
            mode=str(auto.get("mode") or "react"),
            temperature=float(auto.get("temperature", 0.7)),
            max_tokens=int(auto.get("max_tokens", 2048)),
            provider=(str(auto["provider"]).strip() or None) if auto.get("provider") else None,
            model=(str(auto["model"]).strip() or None) if auto.get("model") else None,
        ),
        triggers=OneBot11Triggers(
            private=bool(trig.get("private", True)),
            group=bool(trig.get("group", True)),
            group_at_only=bool(trig.get("group_at_only", True)),
            prefixes=_str_list(trig.get("prefixes")),
            ignore_self=bool(trig.get("ignore_self", True)),
        ),
    )
