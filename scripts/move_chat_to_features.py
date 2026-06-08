#!/usr/bin/env python3
"""Move chat modules into features/chat/ and write root re-export stubs."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".workbench-src" / "src"
CHAT = ROOT / "features" / "chat"

FILES = [
    "ChatComposer.jsx",
    "ChatToolTimeline.jsx",
    "MessageActions.jsx",
    "chatStorage.js",
    "chatThreadSync.js",
    "chatTransport.js",
    "chatToolTimeline.js",
    "chatScenarioPresets.js",
    "chatMessageImages.js",
    "chatTranslate.js",
]

STUB_TEMPLATE = 'export {{ export_line }} from "@/features/chat/{name}";\n'


def main() -> None:
    CHAT.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        src = ROOT / name
        dst = CHAT / name
        if not src.exists():
            print(f"skip missing {src}")
            continue
        text = src.read_text(encoding="utf-8")
        text = text.replace('from "./chatScenarioPresets.js"', 'from "./chatScenarioPresets.js"')
        text = text.replace('from "./chatToolTimeline.js"', 'from "./chatToolTimeline.js"')
        text = text.replace('from "./chatStorage.js"', 'from "./chatStorage.js"')
        text = text.replace('from "./chatTranslate.js"', 'from "./chatTranslate.js"')
        dst.write_text(text, encoding="utf-8")
        export_line = "{ default }" if name.endswith(".jsx") else "*"
        if name.endswith(".js") and not name.endswith(".jsx"):
            # named exports only files
            if name == "chatTranslate.js":
                stub = 'export * from "@/features/chat/chatTranslate.js";\n'
            elif name == "chatStorage.js":
                stub = 'export * from "@/features/chat/chatStorage.js";\n'
            else:
                stub = f'export * from "@/features/chat/{name}";\n'
        else:
            stub = f'export {{ default }} from "@/features/chat/{name}";\n'
        src.write_text(stub, encoding="utf-8")
        print(f"moved {name}")

    # ChatPanel relative imports
    panel = CHAT / "ChatPanel.jsx"
    if panel.exists():
        t = panel.read_text(encoding="utf-8")
        replacements = {
            '@/chatTransport.js': './chatTransport.js',
            '@/chatMessageImages.js': './chatMessageImages.js',
            '@/ChatToolTimeline.jsx': './ChatToolTimeline.jsx',
            '@/chatStorage.js': './chatStorage.js',
            '@/chatThreadSync.js': './chatThreadSync.js',
            '@/MessageActions.jsx': './MessageActions.jsx',
            '@/chatTranslate.js': './chatTranslate.js',
            '@/ChatComposer.jsx': './ChatComposer.jsx',
            '@/chatScenarioPresets.js': './chatScenarioPresets.js',
        }
        for old, new in replacements.items():
            t = t.replace(f'from "{old}"', f'from "{new}"')
        panel.write_text(t, encoding="utf-8")
        print("updated ChatPanel imports")


if __name__ == "__main__":
    main()
