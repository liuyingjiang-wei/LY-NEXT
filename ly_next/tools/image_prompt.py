"""Prompt normalization for image generation APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_SENTENCE_END = re.compile(r"[.!?。！？…]\s+")
_SIZE_TOKEN = re.compile(
    r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b",
    re.IGNORECASE,
)
_ASPECT_RATIO = re.compile(
    r"(?:aspect\s*ratio|比例|宽高比)\s*[:：]?\s*(\d{1,2})\s*[:：/]\s*(\d{1,2})",
    re.IGNORECASE,
)
# Strip redundant size tokens from prompt after extraction (keep descriptive text).
_SIZE_LINE = re.compile(
    r"^\s*[-•]?\s*(\d{3,4}\s*[x×]\s*\d{3,4}|"
    r"\d{1,2}\s*[:：/]\s*\d{1,2}\s*(?:aspect\s*ratio|比例)?)\s*[,.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_ASPECT_HINTS: tuple[tuple[tuple[str, ...], tuple[int, int]], ...] = (
    (("ultra-wide", "ultrawide", "21:9", "超宽"), (1536, 864)),
    (("16:10", "2560x1600", "宽屏壁纸", "desktop wallpaper"), (1536, 960)),
    (("landscape", "横图", "横屏", "wide"), (1536, 1024)),
    (("portrait", "竖图", "竖屏"), (1024, 1536)),
    (("square", "方图"), (1024, 1024)),
)


@dataclass(frozen=True)
class ImageGenerationInput:
    prompt: str
    size: str | None
    negative_prompt_field: str | None
    truncated: bool
    size_source: str  # config | prompt | hint | auto


def image_max_prompt_chars() -> int:
    raw = config.get("tools.image.max_prompt_chars", 2000)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 2000
    return max(200, min(n, 8000))


def default_negative_prompt_text() -> str:
    raw = config.get("tools.image.negative_prompt", "")
    return str(raw or "").strip()


def negative_prompt_mode() -> str:
    mode = str(config.get("tools.image.negative_prompt_mode", "prompt") or "prompt").strip().lower()
    if mode in ("field", "both", "prompt"):
        return mode
    return "prompt"


def _snap_dimension(n: int) -> int:
    n = max(256, min(n, 3840))
    return max(256, (n // 16) * 16)


def _size_string(w: int, h: int) -> str:
    return f"{_snap_dimension(w)}x{_snap_dimension(h)}"


def _ratio_size(w_ratio: int, h_ratio: int, *, long_edge: int = 1536) -> str:
    if w_ratio <= 0 or h_ratio <= 0:
        return ""
    if w_ratio >= h_ratio:
        w = long_edge
        h = int(round(long_edge * h_ratio / w_ratio))
    else:
        h = long_edge
        w = int(round(long_edge * w_ratio / h_ratio))
    return _size_string(w, h)


def extract_size_from_prompt(prompt: str) -> tuple[str, str | None, str]:
    text = (prompt or "").strip()
    if not text:
        return "", None, "auto"

    m = _SIZE_TOKEN.search(text)
    if m:
        size = _size_string(int(m.group(1)), int(m.group(2)))
        cleaned = _SIZE_TOKEN.sub("", text, count=1)
        cleaned = _SIZE_LINE.sub("", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned or text, size, "prompt"

    m = _ASPECT_RATIO.search(text)
    if m:
        size = _ratio_size(int(m.group(1)), int(m.group(2)))
        if size:
            return text, size, "prompt"

    low = text.lower()
    for keys, wh in _ASPECT_HINTS:
        if any(k in low for k in keys):
            return text, _size_string(wh[0], wh[1]), "hint"

    return text, None, "auto"


def _merge_negative_text(*parts: str) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for raw in parts:
        for chunk in re.split(r"[,，;；\n]+", str(raw or "")):
            item = chunk.strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return ", ".join(out)


def apply_negative_prompt(positive: str, negative: str, *, mode: str) -> tuple[str, str | None]:
    """Return (api_prompt, negative_prompt_field)."""
    pos = (positive or "").strip()
    neg = (negative or "").strip()
    if not neg:
        return pos, None
    if mode == "field":
        return pos, neg
    if mode == "both":
        return f"{pos}\n\nAvoid: {neg}", neg
    # OpenAI / ChatGPT style: natural-language exclusions in the main prompt.
    return f"{pos}\n\nDo not include: {neg}.", None


def prepare_image_prompt(prompt: str) -> tuple[str, bool]:
    """Return (prompt_for_api, was_truncated). Legacy helper."""
    built = build_image_generation_input(prompt)
    return built.prompt, built.truncated


def build_image_generation_input(
    prompt: str,
    *,
    negative_override: str | None = None,
    config_size: str | None = None,
) -> ImageGenerationInput:
    cfg_size = str(config_size or "").strip().lower()
    cleaned, parsed_size, parse_source = extract_size_from_prompt(prompt)

    size: str | None = None
    size_source = "auto"
    if cfg_size and cfg_size not in ("auto", "prompt", "none", ""):
        size = cfg_size if "x" in cfg_size else None
        size_source = "config"
    elif parsed_size:
        size = parsed_size
        size_source = parse_source

    neg = _merge_negative_text(default_negative_prompt_text(), negative_override or "")
    mode = negative_prompt_mode()
    api_prompt, neg_field = apply_negative_prompt(cleaned, neg, mode=mode)

    limit = image_max_prompt_chars()
    truncated = False
    if len(api_prompt) > limit:
        cut = api_prompt[:limit]
        window = cut[max(0, limit - 320) :]
        matches = list(_SENTENCE_END.finditer(window))
        if matches:
            end = max(0, limit - 320) + matches[-1].end()
            cut = api_prompt[:end].rstrip()
        else:
            cut = cut.rstrip()
        api_prompt = cut or api_prompt[:limit].rstrip()
        truncated = True
        logger.info(
            "[generate_image] prompt truncated %s -> %s chars (max_prompt_chars=%s)",
            len(prompt),
            len(api_prompt),
            limit,
        )

    return ImageGenerationInput(
        prompt=api_prompt,
        size=size,
        negative_prompt_field=neg_field,
        truncated=truncated,
        size_source=size_source,
    )
