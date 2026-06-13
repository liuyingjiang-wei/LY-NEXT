"""Settings apply-mode guide for workbench hot-reload matrix."""

from __future__ import annotations

from typing import Any

APPLY_IMMEDIATE = "immediate"
APPLY_NEXT_TURN = "next_turn"
APPLY_RESTART = "restart"

APPLY_MODE_LABELS: dict[str, str] = {
    APPLY_IMMEDIATE: "立即生效",
    APPLY_NEXT_TURN: "下轮对话生效",
    APPLY_RESTART: "需重启进程",
}

_SETTINGS_RESTART_ROOTS = frozenset({"server", "database", "redis", "services", "bridge"})

ROOT_APPLY_MODES: dict[str, str] = {
    "llm": APPLY_NEXT_TURN,
    "agent": APPLY_NEXT_TURN,
    "tools": APPLY_NEXT_TURN,
    "logging": APPLY_IMMEDIATE,
    "auth": APPLY_NEXT_TURN,
    "api": APPLY_NEXT_TURN,
    "plugins": APPLY_NEXT_TURN,
    "server": APPLY_RESTART,
    "database": APPLY_RESTART,
    "redis": APPLY_RESTART,
    "services": APPLY_RESTART,
    "bridge": APPLY_RESTART,
    "openai_llm": APPLY_NEXT_TURN,
    "anthropic_llm": APPLY_NEXT_TURN,
    "ollama_llm": APPLY_NEXT_TURN,
    "openai_compat_llm": APPLY_NEXT_TURN,
    "rag_embedding_llm": APPLY_NEXT_TURN,
    "rag_rerank_llm": APPLY_NEXT_TURN,
}

SECTION_APPLY_GUIDE: list[dict[str, str]] = [
    {
        "id": "llm",
        "title": "模型配置",
        "mode": APPLY_NEXT_TURN,
        "detail": "保存后刷新模型注册表；当前进行中的对话仍用旧模型，新开或下一条消息使用新配置。",
    },
    {
        "id": "agent",
        "title": "Agent / 工具策略",
        "mode": APPLY_NEXT_TURN,
        "detail": "reasoning_mode、tool_policy、max_steps 等在下一条用户消息生效。",
    },
    {
        "id": "tools_mcp",
        "title": "MCP / 内置工具",
        "mode": APPLY_NEXT_TURN,
        "detail": "保存后尝试热重载 MCP；stdio 型（npx/uvx）首次对话才拉起子进程。",
    },
    {
        "id": "logging",
        "title": "日志级别",
        "mode": APPLY_IMMEDIATE,
        "detail": "logging.level 保存后立即应用到当前进程日志。",
    },
    {
        "id": "auth",
        "title": "访问控制",
        "mode": APPLY_NEXT_TURN,
        "detail": "鉴权开关与 API Key 保存后立即生效；已登录 Cookie 可能需要重新登录。",
    },
    {
        "id": "infra",
        "title": "基础设施（server/database/redis）",
        "mode": APPLY_RESTART,
        "detail": "连接参数变更需重新执行 uv run ly。",
    },
    {
        "id": "bridge",
        "title": "消息桥接",
        "mode": APPLY_RESTART,
        "detail": "QQ/Telegram 连接参数变更通常需重启；Telegram 白名单等部分字段可热更新。",
    },
    {
        "id": "plugins",
        "title": "插件 / Git 克隆",
        "mode": APPLY_NEXT_TURN,
        "detail": "Git 代理与仓库地址立即影响克隆命令；security_profile 变更需重启。",
    },
]


def apply_mode_for_root(root: str) -> str:
    return ROOT_APPLY_MODES.get(str(root).strip(), APPLY_NEXT_TURN)


def apply_by_root_from_patch(patch: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in patch:
        if isinstance(root, str):
            out[root] = apply_mode_for_root(root)
    return out


def settings_apply_guide_payload() -> dict[str, Any]:
    return {
        "modes": APPLY_MODE_LABELS,
        "roots": ROOT_APPLY_MODES,
        "sections": SECTION_APPLY_GUIDE,
    }
