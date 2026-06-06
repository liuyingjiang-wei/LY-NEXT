"""CLI diagnostics (`ly doctor`) — readiness, security, config, and NapCat hints."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ly_next import __version__
from ly_next.core.config import config, get_data_root, get_project_root
from ly_next.core.security_health import gather_security_health
from ly_next.core.server_port import is_port_in_use
from ly_next.core.system_readiness import gather_readiness

MATURITY = "Alpha"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _config_path() -> Path:
    return Path(config.config_file)


def _napcat_check() -> dict[str, Any]:
    enabled = bool(config.get("bridge.onebot11.enabled", False))
    paths = config.get("bridge.onebot11.ws_paths") or []
    if not isinstance(paths, list):
        paths = []
    paths = [str(p) for p in paths if str(p).strip()]
    host = str(config.get("server.host", "0.0.0.0") or "0.0.0.0").strip()
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    port = int(config.get("server.port", 8000) or 8000)
    primary = paths[0] if paths else "/OneBotv11"
    url = f"ws://{display_host}:{port}{primary}"
    ok = enabled and bool(paths)
    hint = None
    if not enabled:
        hint = "bridge.onebot11.enabled 为 false，NapCat 不会连接"
    elif not paths:
        hint = "ws_paths 为空，请在配置或工作台 QQ 页填写"
    else:
        hint = f"NapCat WebSocket 客户端 URL：{url}"
    return {
        "id": "napcat_config",
        "ok": ok,
        "label": "NapCat 桥接配置",
        "hint": hint,
        "napcat_ws_url": url,
        "ws_paths": paths,
    }


def _port_check() -> dict[str, Any]:
    host = str(config.get("server.host", "0.0.0.0") or "0.0.0.0").strip()
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    port = int(config.get("server.port", 8000) or 8000)
    busy = is_port_in_use(bind_host, port)
    return {
        "id": "listen_port",
        "ok": not busy,
        "label": f"监听端口 {port}",
        "hint": None if not busy else f"端口 {port} 已被占用，启动可能失败",
        "host": host,
        "port": port,
    }


def _static_checks() -> list[dict[str, Any]]:
    cfg = _config_path()
    www = get_project_root() / "www" / "app.html"
    first_run = get_data_root() / "FIRST_RUN.txt"
    checks: list[dict[str, Any]] = [
        {
            "id": "config_file",
            "ok": cfg.is_file(),
            "label": "用户配置文件",
            "hint": None if cfg.is_file() else f"未找到 {cfg}，首次启动 ly 会自动生成",
        },
        {
            "id": "workbench_static",
            "ok": www.is_file(),
            "label": "工作台静态资源 (www/)",
            "hint": None if www.is_file() else "缺少 www/，请执行 pnpm run build:workbench",
        },
    ]
    if first_run.is_file():
        checks.append(
            {
                "id": "first_run",
                "ok": True,
                "label": "首次运行说明",
                "hint": f"API 密钥见 {first_run}",
            }
        )
    checks.append(_port_check())
    checks.append(_napcat_check())
    return checks


async def gather_doctor_report() -> dict[str, Any]:
    readiness, security = await asyncio.gather(
        gather_readiness(),
        asyncio.to_thread(gather_security_health),
    )
    static_checks = _static_checks()
    all_static_ok = all(c["ok"] for c in static_checks if c["id"] != "napcat_config")
    napcat = next(c for c in static_checks if c["id"] == "napcat_config")

    suggestions: list[str] = list(readiness.get("suggestions") or [])
    for s in security.get("suggestions") or []:
        if s not in suggestions:
            suggestions.append(str(s))
    for c in static_checks:
        if not c.get("ok") and c.get("hint") and c["id"] != "napcat_config":
            msg = str(c["hint"])
            if msg not in suggestions:
                suggestions.append(msg)

    ready_for_chat = bool(readiness.get("ready_for_chat"))
    critical = int(security.get("critical_count") or 0)
    ok_to_run = ready_for_chat and critical == 0 and all_static_ok

    return {
        "generated_at": _utcnow_iso(),
        "version": __version__,
        "maturity": MATURITY,
        "ready_for_chat": ready_for_chat,
        "ok_to_run": ok_to_run,
        "config_path": str(_config_path()),
        "readiness": readiness,
        "security": security,
        "checks": static_checks,
        "napcat_ws_url": napcat.get("napcat_ws_url"),
        "suggestions": suggestions,
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"LY-NEXT doctor · v{report.get('version')} · {report.get('maturity')}")
    lines.append(f"时间: {report.get('generated_at')}")
    lines.append(f"配置: {report.get('config_path')}")
    lines.append("")

    readiness = report.get("readiness") or {}
    checks = readiness.get("checks") or {}
    lines.append("── 依赖就绪 ──")
    llm = checks.get("llm") or {}
    lines.append(f"  LLM: {'✓' if llm.get('ok') else '✗'} ({llm.get('provider', '—')})")
    if llm.get("hint"):
        lines.append(f"       {llm['hint']}")
    pg = checks.get("postgres") or {}
    lines.append(f"  PostgreSQL: {'✓' if pg.get('ok') else '✗'}")
    if pg.get("hint"):
        lines.append(f"       {pg['hint']}")
    rd = checks.get("redis") or {}
    lines.append(f"  Redis: {'✓' if rd.get('ok') else '✗'}")
    if rd.get("hint"):
        lines.append(f"       {rd['hint']}")
    lines.append(f"  可对话: {'是' if readiness.get('ready_for_chat') else '否'}")
    lines.append("")

    lines.append("── 本地检查 ──")
    for c in report.get("checks") or []:
        mark = "✓" if c.get("ok") else "✗"
        lines.append(f"  {mark} {c.get('label')}")
        if c.get("hint"):
            lines.append(f"       {c['hint']}")
    lines.append("")

    security = report.get("security") or {}
    lines.append("── 安全体检 ──")
    for c in security.get("checks") or []:
        if c.get("ok"):
            mark = "✓"
        elif c.get("severity") == "critical":
            mark = "!"
        else:
            mark = "✗"
        lines.append(f"  {mark} {c.get('label')}")
        if c.get("hint"):
            lines.append(f"       {c['hint']}")
    lines.append("")

    suggestions = report.get("suggestions") or []
    if suggestions:
        lines.append("── 建议 ──")
        for i, s in enumerate(suggestions, 1):
            lines.append(f"  {i}. {s}")
        lines.append("")

    if report.get("ok_to_run"):
        lines.append("结论: 可以启动服务并尝试对话（uv run ly --no-prompt）")
    else:
        lines.append("结论: 存在阻塞项，请先处理上述建议后再启动")
    lines.append("")
    lines.append("Alpha 阶段不建议公网裸奔；生产部署见 SECURITY.md")
    return "\n".join(lines)


def run_doctor_cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="ly doctor", description="LY-NEXT 环境诊断")
    parser.add_argument("--json", action="store_true", help="输出 JSON（便于复制/自动化）")
    parser.add_argument("-o", "--output", help="将报告写入文件")
    args = parser.parse_args(argv)
    report = asyncio.run(gather_doctor_report())

    if args.json:
        text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        text = format_doctor_report(report)

    if args.output:
        Path(args.output).write_text(
            text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8"
        )
        print(f"已写入 {args.output}", file=sys.stderr)
    else:
        print(text)

    return 0 if report.get("ok_to_run") else 1
