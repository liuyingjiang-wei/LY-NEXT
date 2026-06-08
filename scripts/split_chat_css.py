#!/usr/bin/env python3
"""Extract workbench chat + bridge API styles from app.css."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".workbench-src" / "src"
APP = ROOT / "app.css"
OUT_CHAT = ROOT / "styles" / "chat-workbench.css"
OUT_SETTINGS = ROOT / "styles" / "settings.css"

# contiguous blocks (1-based inclusive)
CHAT_RANGES = [(642, 646), (1072, 2690), (3728, 3832)]
BRIDGE_API_RANGE = (2693, 2798)
MODEL_REGISTRY_RANGE = (3834, 3950)  # until next major section

MOBILE_CHAT_SNIPPETS = """
@media (max-width: 980px) {
  .ly-chat-panel-root {
    min-height: min(calc(var(--wb-vh-fill, 100dvh) - 7rem), 900px);
    max-height: calc(var(--wb-vh-fill, 100dvh) - 5.5rem);
  }
  .ly-chat-container {
    flex-direction: column;
    max-height: none;
    min-height: min(calc(var(--wb-vh-fill, 100dvh) * 0.72), 820px);
  }
  .ly-chat-panel-root {
    border-radius: var(--wb-mobile-radius);
  }
  .ly-chat-sidebar {
    width: 100%;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    border-right: none;
    border-bottom: 1px solid color-mix(in srgb, var(--wb-glass-border) 85%, transparent);
    padding: 12px 14px;
    background: color-mix(in srgb, var(--wb-main-panel) 90%, transparent);
  }
  .ly-chat-conv-panel { flex: 1 1 100%; min-width: 0; }
  .ly-chat-conv-list { max-height: 100px; }
  .ly-chat-main { display: flex; flex-direction: column; min-height: 0; flex: 1 1 auto; }
  .ly-chat-messages {
    flex: 1 1 auto;
    min-height: 120px;
    padding: 10px 8px;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .ly-chat-msg--user { margin-left: 8px; max-width: 94%; }
  .ly-chat-msg--assistant { margin-right: 8px; max-width: 94%; }
  .ly-chat-input-area {
    flex-shrink: 0;
    position: sticky;
    bottom: 0;
    z-index: 5;
    padding: 10px max(8px, var(--wb-safe-right)) max(10px, var(--wb-safe-bottom)) max(8px, var(--wb-safe-left));
    background: var(--wb-main-panel);
  }
  .ly-chat-input-row textarea,
  .ly-chat-input { font-size: 16px; line-height: 1.45; }
  .ly-chat-trace,
  .ly-chat-telemetry {
    font-size: 12px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .ly-chat-new-btn { min-height: 44px; touch-action: manipulation; }
  :root[data-theme="dark"] .ly-chat-sidebar { border-bottom-color: rgba(51, 65, 85, 0.9); }
  :root[data-theme="dark"] .ly-chat-input-area {
    background: color-mix(in srgb, var(--wb-main-panel) 94%, transparent);
  }
}

@media (max-width: 980px) and (orientation: landscape) {
  .ly-chat-conv-list { max-height: 72px; }
  .ly-chat-panel-root {
    min-height: min(calc(var(--wb-vh-fill, 100dvh) - 4.5rem), 520px);
    max-height: calc(var(--wb-vh-fill, 100dvh) - 3.5rem);
  }
}

@media (max-width: 980px) and (max-height: 420px) {
  .ly-chat-conv-list { max-height: 56px; }
}

@media (max-width: 480px) {
  .ly-chat-conv-list { max-height: 88px; }
}
"""


def slice_lines(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def drop_ranges(lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    drop = set()
    for s, e in ranges:
        drop.update(range(s, e + 1))
    return [ln for i, ln in enumerate(lines, start=1) if i not in drop]


def strip_ly_chat_from_media(css: str) -> str:
    """Remove rules whose selector lines mention ly-chat inside @media blocks."""
    return re.sub(
        r"^[ \t]*(?:\.ly-chat[^{]*|:root\[data-theme[^\n]*\.ly-chat[^{]*)\{[^}]*\}\s*\n?",
        "",
        css,
        flags=re.MULTILINE,
    )


def main() -> None:
    lines = APP.read_text(encoding="utf-8").splitlines(keepends=True)
    chat_body = "/* Workbench chat UI — split from app.css */\n\n"
    for s, e in CHAT_RANGES:
        chat_body += slice_lines(lines, s, e)
    chat_body += "\n" + MOBILE_CHAT_SNIPPETS.strip() + "\n"
    OUT_CHAT.write_text(chat_body, encoding="utf-8")
    print(f"wrote {OUT_CHAT}")

    bridge = slice_lines(lines, *BRIDGE_API_RANGE)
    model = slice_lines(lines, *MODEL_REGISTRY_RANGE)
    settings = OUT_SETTINGS.read_text(encoding="utf-8")
    settings += "\n\n/* --- bridge / model registry from app.css --- */\n\n" + bridge + "\n" + model
    OUT_SETTINGS.write_text(settings, encoding="utf-8")
    print(f"appended bridge/model to {OUT_SETTINGS}")

    all_ranges = CHAT_RANGES + [BRIDGE_API_RANGE, MODEL_REGISTRY_RANGE]
    shrunk = drop_ranges(lines, all_ranges)
    shrunk_css = strip_ly_chat_from_media("".join(shrunk))
    while "\n\n\n\n" in shrunk_css:
        shrunk_css = shrunk_css.replace("\n\n\n\n", "\n\n\n")
    APP.write_text(shrunk_css, encoding="utf-8")
    print(f"trimmed {APP}")


if __name__ == "__main__":
    main()
