from __future__ import annotations

from typing import Any


def merge_config_dicts(default: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    result = default.copy()
    for key, value in user.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config_dicts(result[key], value)
        else:
            result[key] = value
    return result
