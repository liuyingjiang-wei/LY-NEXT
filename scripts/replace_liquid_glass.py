"""Replace LiquidGlass with Ant Design SettingsCard in workbench panels."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / ".workbench-src" / "src"

IMPORT_OLD = 'import LiquidGlass from "./LiquidGlass.jsx";\n'
IMPORT_NEW = 'import { SettingsCard } from "@/components/patterns/SettingsCard";\n'

for path in SRC.rglob("*.jsx"):
    if path.name == "LiquidGlass.jsx":
        continue
    text = path.read_text(encoding="utf-8")
    if "LiquidGlass" not in text:
        continue
    text = text.replace(IMPORT_OLD, IMPORT_NEW)
    text = text.replace("<LiquidGlass", "<SettingsCard")
    text = text.replace("</LiquidGlass>", "</SettingsCard>")
    text = re.sub(r"\s+interactive=\{false\}", "", text)
    text = re.sub(r"\s+interactive=\{true\}", "", text)
    text = re.sub(r'\s+accent="[^"]*"', "", text)
    text = re.sub(r"\s+accent=\{[^}]+\}", "", text)
    path.write_text(text, encoding="utf-8")
    print("updated", path.relative_to(SRC.parent.parent))
