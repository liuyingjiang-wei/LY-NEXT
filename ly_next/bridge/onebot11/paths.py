from __future__ import annotations

DEFAULT_ONEBOT11_WS_PATHS: tuple[str, ...] = (
    "/OneBotv11",
    "/onebot/v11/ws",
)

DEFAULT_NAPCAT_WS_PATH = "/OneBotv11"


def normalize_ws_path(path: str) -> str:
    p = (path or "").split("?", 1)[0].strip()
    if not p.startswith("/"):
        p = f"/{p}"
    return p


def is_onebot11_ws_path(path: str) -> bool:
    p = normalize_ws_path(path)
    if p in DEFAULT_ONEBOT11_WS_PATHS:
        return True
    return p.startswith("/onebot/")


def merge_ws_paths(configured: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in (*configured, *DEFAULT_ONEBOT11_WS_PATHS):
        norm = normalize_ws_path(item)
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    if DEFAULT_NAPCAT_WS_PATH in out:
        out.remove(DEFAULT_NAPCAT_WS_PATH)
        out.insert(0, DEFAULT_NAPCAT_WS_PATH)
    return tuple(out)
