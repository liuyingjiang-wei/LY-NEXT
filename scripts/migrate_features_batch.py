#!/usr/bin/env python3
"""Migrate SettingsPanel, bridge panels, RunsHistory, ChatPanel to features/."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".workbench-src" / "src"

SECTION_OPEN = re.compile(
    r'<SettingsCard className="panel(?:[^"]*)?">\s*'
    r'<h4 className="settings-section-title">([^<]+)</h4>\s*'
    r'(?:<p className="settings-hint">([\s\S]*?)</p>\s*)?',
    re.MULTILINE,
)


def convert_section_cards(content: str) -> str:
    content = SECTION_OPEN.sub(
        lambda m: (
            f'<SettingsSection title="{m.group(1)}"'
            + (f" hint={m.group(2).strip()} " if m.group(2) else " ")
            + ">"
        ),
        content,
    )
    return content.replace("</SettingsCard>", "</SettingsSection>")


def wrap_settings_page_layout(
    content: str,
    *,
    title: str,
    description: str,
    layout: str = "sections",
    save_label: str = "保存设置",
    on_save_fn: str = "onSave",
    on_reset: bool = True,
    extra: str | None = None,
) -> str:
    """Replace loading gate + form/fragment return with SettingsPageLayout."""
    content = re.sub(
        r"\s*if \(loading\) \{[\s\S]*?\}\s*\n",
        "\n",
        content,
        count=1,
    )
    content = re.sub(
        r"async function (\w+)\(e\) \{\s*e\.preventDefault\(\);\s*",
        r"async function \1() {\n    ",
        content,
    )
    content = re.sub(r"<form onSubmit=\{(\w+)\}>\s*", "", content)
    content = re.sub(r"</form>\s*", "", content)
    content = re.sub(
        r'<div className="settings-(?:actions settings-actions--foot|submit-wrap)">[\s\S]*?</div>\s*',
        "",
        content,
    )

    # Remove legacy top meta card (SettingsPanel / bridges)
    content = re.sub(
        r"<SettingsCard className=\"panel settings-top\">[\s\S]*?</SettingsCard>\s*",
        "",
        content,
        count=1,
    )

    reset_prop = "onReset={load}\n      " if on_reset else ""
    extra_prop = f"extra={{{extra}}}\n      " if extra else ""

    layout_block = f"""return (
    <SettingsPageLayout
      layout="{layout}"
      title="{title}"
      description="{description}"
      loading={{loading}}
      saving={{saving}}
      error={{err}}
      message={{msg}}
      onSave={{{on_save_fn}}}
      {reset_prop}saveLabel="{save_label}"
      {extra_prop}meta={{<SettingsConfigMeta meta={{meta}} onReload={{load}} saving={{saving}} loading={{loading}} />}}
    >
"""

    content = re.sub(
        r"return \(\s*(?:<Fragment>\s*)?",
        layout_block,
        content,
        count=1,
    )
    content = re.sub(r"</Fragment>\s*\);\s*\}", "    </SettingsPageLayout>\n  );\n}", content)
    content = re.sub(r"\);\s*\}\s*$", "    </SettingsPageLayout>\n  );\n}", content, count=1)

    return content


def patch_imports_settings_panel(text: str) -> str:
    text = text.replace("import { Fragment, useCallback", "import { useCallback")
    text = text.replace('from "./agentPresets.js"', 'from "@/agentPresets.js"')
    text = text.replace('from "./settingsShared.js"', 'from "@/settingsShared.js"')
    insert = (
        'import { SettingsConfigMeta } from "@/components/patterns/SettingsConfigMeta";\n'
        'import { SettingsPageLayout } from "@/components/patterns/SettingsPageLayout";\n'
        'import { SettingsSection } from "@/components/patterns/SettingsSection";\n'
    )
    text = text.replace(
        'import { SettingsCard } from "@/components/patterns/SettingsCard";\n',
        insert,
    )
    return text


def patch_imports_bridge(text: str, explorer_import: str | None = None) -> str:
    text = text.replace('from "./settingsForm.jsx"', 'from "@/settingsForm.jsx"')
    text = text.replace('from "./settingsShared.js"', 'from "@/settingsShared.js"')
    if explorer_import:
        text = text.replace('from "./OneBotApiExplorer.jsx"', explorer_import)
    insert = (
        'import { Button, Space } from "antd";\n'
        'import { SettingsConfigMeta } from "@/components/patterns/SettingsConfigMeta";\n'
        'import { SettingsPageLayout } from "@/components/patterns/SettingsPageLayout";\n'
        'import { SettingsSection } from "@/components/patterns/SettingsSection";\n'
    )
    text = text.replace(
        'import { SettingsCard } from "@/components/patterns/SettingsCard";\n',
        insert,
    )
    return text


def migrate_settings_panel() -> None:
    src = (ROOT / "SettingsPanel.jsx").read_text(encoding="utf-8")
    text = patch_imports_settings_panel(src)
    text = re.sub(
        r"async function onSave\(e\) \{\s*e\.preventDefault\(\);\s*",
        "async function onSave() {\n    ",
        text,
    )
    text = re.sub(
        r"\s*if \(loading\) \{[\s\S]*?\}\s*\n",
        "\n",
        text,
        count=1,
    )
    text = re.sub(
        r"return \(\s*<Fragment>\s*<SettingsCard className=\"panel settings-top\">[\s\S]*?</SettingsCard>\s*<form onSubmit=\{onSave\}>\s*",
        """return (
    <SettingsPageLayout
      layout="sections"
      title="应用设置"
      description="日志、Agent 行为、工具策略与 web_search / web_fetch 提供商。"
      loading={loading}
      saving={saving}
      error={err}
      message={msg}
      onSave={onSave}
      onReset={load}
      saveLabel="保存应用配置"
      meta={<SettingsConfigMeta meta={meta} onReload={load} saving={saving} loading={loading} />}
    >
""",
        text,
        count=1,
    )
    text = text.replace(
        """        <div className="settings-submit-wrap">
          <button type="submit" className="btn-save-settings" disabled={saving}>
            {saving ? "保存中…" : "保存应用配置"}
          </button>
        </div>
      </form>
    </Fragment>
  );""",
        "    </SettingsPageLayout>\n  );",
    )
    text = convert_section_cards(text)
    dest = ROOT / "features" / "settings" / "SettingsPanel.jsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    stub = ROOT / "SettingsPanel.jsx"
    stub.write_text(
        'export { default } from "@/features/settings/SettingsPanel.jsx";\n', encoding="utf-8"
    )
    print(f"wrote {dest}")


def migrate_qq_bridge() -> None:
    src = (ROOT / "QqBridgeSettingsPanel.jsx").read_text(encoding="utf-8")
    text = patch_imports_bridge(src, 'from "@/OneBotApiExplorer.jsx"')
    text = wrap_settings_page_layout(
        text,
        title="QQ 桥接",
        description="OneBot v11 / NapCat WebSocket 桥接与自动回复。",
        save_label="保存 QQ 配置",
        extra=(
            "<Space wrap>\n"
            "          <Button onClick={refreshStatus} disabled={saving}>刷新连接状态</Button>\n"
            "          <Button onClick={refreshDiagnostics} disabled={saving}>刷新诊断</Button>\n"
            "          <Button onClick={copyUrl} disabled={saving}>复制 NapCat URL</Button>\n"
            "        </Space>"
        ),
    )
    if "{copyMsg}" in text:
        text = text.replace(
            "message={msg}",
            "message={[msg, copyMsg].filter(Boolean).join(' · ') || undefined}",
        )
    text = convert_section_cards(text)
    dest = ROOT / "features" / "bridges" / "QqBridgeSettingsPanel.jsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    (ROOT / "QqBridgeSettingsPanel.jsx").write_text(
        'export { default } from "@/features/bridges/QqBridgeSettingsPanel.jsx";\n',
        encoding="utf-8",
    )
    print(f"wrote {dest}")


def migrate_telegram_bridge() -> None:
    src = (ROOT / "TelegramBridgeSettingsPanel.jsx").read_text(encoding="utf-8")
    text = patch_imports_bridge(src)
    text = text.replace("async function onSubmit(e) {", "async function onSubmit() {")
    text = text.replace("e.preventDefault();", "", 1)
    text = wrap_settings_page_layout(
        text,
        title="Telegram 桥接",
        description="Bot 长轮询、配对与白名单；保存后若提示需重启请重新执行 uv run ly。",
        save_label="保存 Telegram 配置",
        on_save_fn="onSubmit",
        extra=(
            "<Space wrap>\n"
            "          <Button onClick={refreshAll} disabled={saving}>刷新状态</Button>\n"
            "        </Space>"
        ),
    )
    text = convert_section_cards(text)
    dest = ROOT / "features" / "bridges" / "TelegramBridgeSettingsPanel.jsx"
    dest.write_text(text, encoding="utf-8")
    (ROOT / "TelegramBridgeSettingsPanel.jsx").write_text(
        'export { default } from "@/features/bridges/TelegramBridgeSettingsPanel.jsx";\n',
        encoding="utf-8",
    )
    print(f"wrote {dest}")


def migrate_runs_history() -> None:
    src = (ROOT / "RunsHistoryPanel.jsx").read_text(encoding="utf-8")
    text = src.replace('from "./apiClient.js"', 'from "@/apiClient.js"')
    text = text.replace('from "./settingsShared.js"', 'from "@/settingsShared.js"')
    text = text.replace(
        'import { SettingsCard } from "@/components/patterns/SettingsCard";\n',
        'import { SettingsCard } from "@/components/patterns/SettingsCard";\n'
        'import { SettingsPageLayout } from "@/components/patterns/SettingsPageLayout";\n'
        'import { SettingsSection } from "@/components/patterns/SettingsSection";\n'
        'import { Alert } from "antd";\n',
    )
    text = text.replace(
        'return (\n    <div className="runs-panel">',
        """return (
    <SettingsPageLayout
      title="执行轨迹"
      description="Agent Run 列表与事件时间线；需在「可观测」中开启 agent.observability.enabled。"
      layout="sections"
    >
      <div className="runs-panel">""",
    )
    text = text.replace(
        """      {listErr ? (
        <div className="settings-banner settings-banner--err" role="alert">
          {listErr}
        </div>
      ) : null}""",
        '{listErr ? <Alert type="error" message={listErr} showIcon style={{ marginBottom: 16 }} /> : null}',
    )
    text = text.replace(
        '<SettingsCard className="panel runs-list-panel">',
        '<SettingsSection title="Run 列表" className="runs-list-panel">',
    )
    text = text.replace(
        "</SettingsCard>\n\n      {selectedId",
        "</SettingsSection>\n\n      {selectedId",
    )
    text = text.replace(
        '<SettingsCard className="panel runs-detail-panel">',
        '<SettingsSection title="Run 详情" className="runs-detail-panel">',
    )
    text = text.replace(
        """        </SettingsCard>
      ) : null}
    </div>
  );""",
        """        </SettingsSection>
      ) : null}
    </div>
    </SettingsPageLayout>
  );""",
    )
    dest = ROOT / "features" / "runs" / "RunsHistoryPanel.jsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    (ROOT / "RunsHistoryPanel.jsx").write_text(
        'export { default } from "@/features/runs/RunsHistoryPanel.jsx";\n',
        encoding="utf-8",
    )
    print(f"wrote {dest}")


def migrate_chat_panel() -> None:
    src = (ROOT / "ChatPanel.jsx").read_text(encoding="utf-8")
    replacements = {
        "./apiClient.js": "@/apiClient.js",
        "./chatTransport.js": "@/chatTransport.js",
        "./safeNavPath.js": "@/safeNavPath.js",
        "./chatMessageImages.js": "@/chatMessageImages.js",
        "./ChatToolTimeline.jsx": "@/ChatToolTimeline.jsx",
        "./chatStorage.js": "@/chatStorage.js",
        "./chatThreadSync.js": "@/chatThreadSync.js",
        "./MessageActions.jsx": "@/MessageActions.jsx",
        "./chatTranslate.js": "@/chatTranslate.js",
        "./ChatComposer.jsx": "@/ChatComposer.jsx",
        "./chatScenarioPresets.js": "@/chatScenarioPresets.js",
    }
    for old, new in replacements.items():
        src = src.replace(f'from "{old}"', f'from "{new}"')
    dest = ROOT / "features" / "chat" / "ChatPanel.jsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src, encoding="utf-8")
    (ROOT / "ChatPanel.jsx").write_text(
        'export { default } from "@/features/chat/ChatPanel.jsx";\n',
        encoding="utf-8",
    )
    print(f"wrote {dest}")


def main() -> None:
    migrate_settings_panel()
    migrate_qq_bridge()
    migrate_telegram_bridge()
    migrate_runs_history()
    migrate_chat_panel()
    print("done")


if __name__ == "__main__":
    main()
