#!/usr/bin/env python3
"""Fix broken migrations from migrate_features_batch.py."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".workbench-src" / "src"

USE_EFFECT_BROKEN = """    return (
    <SettingsPageLayout
      layout="sections"
      title="QQ 桥接"
      description="OneBot v11 / NapCat WebSocket 桥接与自动回复。"
      loading={loading}
      saving={saving}
      error={err}
      message={msg}
      onSave={onSave}
      onReset={load}
      saveLabel="保存 QQ 配置"
      extra={<Space wrap>
          <Button onClick={refreshStatus} disabled={saving}>刷新连接状态</Button>
          <Button onClick={refreshDiagnostics} disabled={saving}>刷新诊断</Button>
          <Button onClick={copyUrl} disabled={saving}>复制 NapCat URL</Button>
        </Space>}
      meta={<SettingsConfigMeta meta={meta} onReload={load} saving={saving} loading={loading} />}
    >
) => window.clearInterval(id);"""

USE_EFFECT_FIXED = "    return () => window.clearInterval(id);"

TG_USE_EFFECT_BROKEN = """    return (
    <SettingsPageLayout
      layout="sections"
      title="Telegram 桥接"
      description="Bot 长轮询、配对与白名单；保存后若提示需重启请重新执行 uv run ly。"
      loading={loading}
      saving={saving}
      error={err}
      message={msg}
      onSave={onSubmit}
      onReset={load}
      saveLabel="保存 Telegram 配置"
      extra={<Space wrap>
          <Button onClick={refreshAll} disabled={saving}>刷新状态</Button>
        </Space>}
      meta={<SettingsConfigMeta meta={meta} onReload={load} saving={saving} loading={loading} />}
    >
) => window.clearInterval(id);"""

QQ_RETURN_BROKEN = """  return (
    <SettingsSection title="QQ / NapCat（OneBot v11）" hint=access_token 建议与环境变量 <code>ONEBOT11_ACCESS_TOKEN</code> 一致；运行时配置在{" "}
          <code>data/ly_next/config.yaml</code>（仓库已忽略，勿提交密钥）。 ></SettingsSection>

      <SettingsSection title="QQ 连接状态" >"""

QQ_RETURN_FIXED = """  return (
    <SettingsPageLayout
      layout="sections"
      title="QQ 桥接"
      description="OneBot v11 / NapCat WebSocket 桥接与自动回复。"
      loading={loading}
      saving={saving}
      error={err}
      message={[msg, copyMsg].filter(Boolean).join(" · ") || undefined}
      onSave={onSave}
      onReset={load}
      saveLabel="保存 QQ 配置"
      extra={
        <Space wrap>
          <Button onClick={refreshStatus} disabled={saving}>
            刷新连接状态
          </Button>
          <Button onClick={refreshDiagnostics} disabled={saving}>
            刷新诊断
          </Button>
          <Button onClick={copyUrl} disabled={saving}>
            复制 NapCat URL
          </Button>
        </Space>
      }
      meta={<SettingsConfigMeta meta={meta} onReload={load} saving={saving} loading={loading} />}
    >
      <SettingsSection title="QQ / NapCat（OneBot v11）">
        <p className="settings-hint">
          access_token 建议与环境变量 <code>ONEBOT11_ACCESS_TOKEN</code> 一致；运行时配置在{" "}
          <code>data/ly_next/config.yaml</code>（仓库已忽略，勿提交密钥）。
        </p>
      </SettingsSection>

      <SettingsSection title="QQ 连接状态">"""

TG_RETURN_START = """  return (
    <SettingsSection title="连接状态" >"""

TG_RETURN_FIXED = """  const statusMessage = [msg, pairingMsg].filter(Boolean).join(" · ") || undefined;
  const statusError = [err, pairingErr].filter(Boolean).join(" · ") || undefined;

  return (
    <SettingsPageLayout
      layout="sections"
      title="Telegram 桥接"
      description="Bot 长轮询、配对与白名单；保存后若提示需重启请重新执行 uv run ly。"
      loading={loading}
      saving={saving}
      error={statusError}
      message={statusMessage}
      onSave={onSubmit}
      onReset={load}
      saveLabel="保存 Telegram 配置"
      extra={
        <Space wrap>
          <Button onClick={refreshAll} disabled={saving}>
            刷新状态
          </Button>
        </Space>
      }
      meta={<SettingsConfigMeta meta={meta} onReload={load} saving={saving} loading={loading} />}
    >
      <SettingsSection title="Telegram Bot">
        <p className="settings-hint">
          在 @BotFather 创建 Bot 并填入 <code>bot_token</code>（不是 LY-NEXT 的 auth.api_key）。私聊策略
          <code>dm_policy</code> 与 allowlist 控制谁可以和 Bot 对话。
        </p>
      </SettingsSection>

      <SettingsSection title="连接状态">"""

TG_PENDING_BROKEN = """      <SettingsSection title="待批准配对码" hint=用户私聊 Bot 后会收到配对码；点击下方按钮批准或拒绝。 >"""

TG_PENDING_FIXED = """      <SettingsSection title="待批准配对码">
        <p className="settings-hint">用户私聊 Bot 后会收到配对码；点击下方按钮批准或拒绝。</p>"""

TG_ALLOW_BROKEN = """      <SettingsSection title="用户白名单 allow_from" hint=每行一个数字 user_id（个人资料 → 用户 ID 下方那串数字）。也支持{" "}
          <code>telegram:6537629878</code>；不要填 <code>@用户名</code>。 ><textarea"""

TG_ALLOW_FIXED = """      <SettingsSection title="用户白名单 allow_from">
        <p className="settings-hint">
          每行一个数字 user_id（个人资料 → 用户 ID 下方那串数字）。也支持{" "}
          <code>telegram:6537629878</code>；不要填 <code>@用户名</code>。
        </p>
        <textarea"""


def fix_settings_panel() -> None:
    path = ROOT / "features" / "settings" / "SettingsPanel.jsx"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '<SettingsSection title="场景预设" hint=一键填充 Agent 与工具策略，应用后仍需点击保存。 >',
        '<SettingsSection title="场景预设" hint="一键填充 Agent 与工具策略，应用后仍需点击保存。">',
    )
    text = text.replace(
        '<SettingsSection title="Agent 工具可见性" hint=全选 = 不限制（allow_tools 为 null）。 >',
        '<SettingsSection title="Agent 工具可见性" hint="全选 = 不限制（allow_tools 为 null）。">',
    )
    path.write_text(text, encoding="utf-8")
    print("fixed settings panel hints")


def fix_qq() -> None:
    path = ROOT / "features" / "bridges" / "QqBridgeSettingsPanel.jsx"
    text = path.read_text(encoding="utf-8")
    text = text.replace(USE_EFFECT_BROKEN, USE_EFFECT_FIXED)
    text = text.replace(QQ_RETURN_BROKEN, QQ_RETURN_FIXED)
    path.write_text(text, encoding="utf-8")
    print("fixed qq bridge")


def fix_telegram() -> None:
    path = ROOT / "features" / "bridges" / "TelegramBridgeSettingsPanel.jsx"
    text = path.read_text(encoding="utf-8")
    text = text.replace(TG_USE_EFFECT_BROKEN, USE_EFFECT_FIXED)
    text = text.replace(TG_RETURN_START, TG_RETURN_FIXED)
    text = text.replace(TG_PENDING_BROKEN, TG_PENDING_FIXED)
    text = text.replace(TG_ALLOW_BROKEN, TG_ALLOW_FIXED)
    path.write_text(text, encoding="utf-8")
    print("fixed telegram bridge")


def main() -> None:
    fix_settings_panel()
    fix_qq()
    fix_telegram()


if __name__ == "__main__":
    main()
