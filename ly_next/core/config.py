import copy
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from ly_next.core.config_merge import merge_config_dicts
from ly_next.core.data_bootstrap import bootstrap_data_assets
from ly_next.core.postgres_port import resolve_database_password, resolve_database_port


def get_project_root() -> Path:
    env = os.environ.get("LY_NEXT_PROJECT_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent


def get_data_root() -> Path:
    return get_project_root() / "data" / "ly_next"


def _subst_env_placeholders(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        default = m.group(2)
        raw = os.environ.get(key)
        if default is not None:
            return raw if raw else default
        return raw if raw is not None else ""

    return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", repl, s)


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        return _subst_env_placeholders(value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _packaged_default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "default_config.yaml"


def _load_yaml_defaults() -> dict[str, Any]:
    packaged = _packaged_default_config_path()
    if packaged.is_file():
        try:
            with open(packaged, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    repo_default = get_project_root() / "config" / "default_config.yaml"
    if repo_default.is_file():
        try:
            with open(repo_default, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return _minimal_fallback_defaults()


UNSAFE_WORKBENCH_WHITELIST = frozenset({"/ly", "/ly/"})
UNSAFE_DOCS_WHITELIST = frozenset({"/docs", "/openapi.json", "/redoc"})
REQUIRED_AUTH_WHITELIST = frozenset(
    {
        "/api/health",
        "/api/info",
        "/api/auth/login",
        "/api/auth/config",
    }
)


def _minimal_fallback_defaults() -> dict[str, Any]:
    return {
        "server": {"host": "0.0.0.0", "port": 8000, "reload": False, "log_level": "info"},
        "cors": {
            "origins": ["http://localhost:8000", "http://127.0.0.1:8000"],
        },
        "api": {
            "auto_load": False,
            "api_dir": "ly_next/apis",
            "security_profile": "production",
            "trusted_module_hashes": {},
        },
        "plugins": {
            "enabled": True,
            "dir": "plugins",
            "extra_dirs": ["plugins/local"],
            "modules": [],
            "entry_points": True,
            "security_profile": "development",
            "trusted_module_hashes": {},
        },
        "auth": {
            "enabled": True,
            "mode": "api_key",
            "api_key": "",
            "header_name": "X-API-Key",
            "cookie_name": "ly_api_key",
            "allow_api_key_in_query": False,
            "cookie_secure": False,
            "jwt": {
                "enabled": False,
                "secret": "",
                "algorithm": "HS256",
                "access_ttl_minutes": 60,
                "issuer": "ly-next",
                "cookie_name": "ly_session",
            },
            "users": [],
            "whitelist": [
                "/api/health",
                "/api/info",
                "/api/auth/login",
                "/api/auth/config",
                "/",
                "/ly/login",
                "/ly/static/*",
                "/onebot/v11/ws",
                "/OneBotv11",
            ],
        },
        "bridge": {
            "onebot11": {
                "enabled": True,
                "access_token": "",
                "ws_paths": ["/OneBotv11", "/onebot/v11/ws"],
                "auto_reply": {
                    "enabled": True,
                    "mode": "react",
                },
            },
        },
        "llm": {
            "default_provider": "openai",
            "request_timeout": 120,
            "agent_request_timeout": 300,
        },
        "openai_llm": {"model": "gpt-4o-mini", "api_key": "", "base_url": ""},
        "anthropic_llm": {"model": "claude-3-5-haiku-20241022", "api_key": "", "base_url": ""},
        "ollama_llm": {"model": "qwen2.5", "base_url": "http://localhost:11434"},
        "openai_compat_llm": {
            "model": "qwen2.5",
            "api_key": "not-needed",
            "base_url": "http://localhost:8000/v1",
            "auth_mode": "bearer",
        },
        "rag_embedding_llm": {
            "model": "text-embedding-3-small",
            "api_key": "",
            "base_url": "",
            "auth_mode": "bearer",
        },
        "rag_rerank_llm": {
            "provider": "cohere",
            "model": "rerank-v3.5",
            "api_key": "",
            "base_url": "",
            "auth_mode": "bearer",
        },
        "agent": {
            "enabled": True,
            "max_steps": 6,
            "max_tools": 40,
            "verbose": False,
            "reasoning_mode": "react",
            "stream_output": True,
            "tool_policy": {
                "max_tier": "network",
                "deny_tools": ["web_scrape"],
                "semantic_select": False,
                "semantic_method": "embedding",
                "semantic_top_k": 15,
                "semantic_min_score": 0.32,
                "semantic_relative_factor": 0.92,
                "semantic_min_pool": 8,
                "semantic_fallback": "pins_only",
                "pin_tools": ["list_tools", "describe_tool"],
                "allow_categories": [],
                "allow_tools": None,
            },
            "scratchpad": {
                "max_chars": 12000,
                "compress_enabled": True,
                "compress_target_chars": 4500,
                "compress_max_tokens": 1024,
            },
            "loop_guard": {
                "max_repeat_same_tool": 3,
                "max_consecutive_tool_failures": 4,
            },
            "context": {
                "enabled": True,
                "examples_path": "",
                "top_k": 3,
                "min_similarity": 0.15,
                "use_embeddings": True,
            },
            "rag": {
                "enabled": False,
                "mode": "both",
                "documents_path": "",
                "chunk_strategy": "markdown",
                "top_k": 5,
                "chunk_size": 512,
                "chunk_overlap": 64,
                "min_similarity": 0.20,
                "use_embeddings": True,
                "hybrid_enabled": True,
                "rrf_k": 60,
                "mmr_enabled": True,
                "mmr_lambda": 0.6,
                "retrieve_multiplier": 10,
                "embedding": {"model": "text-embedding-3-small", "config_ref": "rag_embedding_llm"},
                "rerank": {
                    "enabled": False,
                    "provider": "cohere",
                    "model": "rerank-v3.5",
                    "config_ref": "rag_rerank_llm",
                    "top_n": 50,
                },
            },
        },
        "tools": {
            "security_profile": "production",
            "host": {
                "enabled": False,
                "roots": ["~"],
                "deny_paths": [],
                "max_read_bytes": 2_097_152,
                "max_write_bytes": 4_194_304,
                "max_list_entries": 500,
                "exec": {
                    "enabled": True,
                    "default_cwd": "~",
                    "timeout_seconds": 300,
                    "max_output_chars": 120_000,
                    "minimal_env": True,
                    "hard_block_patterns": [],
                },
            },
            "built_in": [
                "calculator",
                "format_json",
                "text_process",
                "regex_extract",
                "get_current_time",
                "url_parse",
                "http_fetch",
                "web_fetch",
                "web_search",
                "remember_fact",
            ],
            "web_search": {"provider": "duckduckgo", "api_key": ""},
            "web_fetch": {
                "provider": "jina",
                "api_key": "",
                "jina_proxy": "",
                "base_url": "",
                "extract_depth": "basic",
                "output_format": "txt",
                "favor_recall": True,
                "include_tables": True,
                "timeout_seconds": 30,
                "default_max_length": 8000,
                "max_response_bytes": 2_000_000,
                "user_agent": "",
            },
            "mcp": {
                "enabled": True,
                "transport": "sse",
                "path": "/mcp",
                "remote": {"enabled": False, "mcpServers": []},
            },
        },
        "database": {
            "host": "${DATABASE_HOST:-localhost}",
            "port": 5432,
            "username": "postgres",
            "password": "",
            "database": "ly_next",
            "try_unix_socket": True,
            "pool_size": 10,
            "max_overflow": 20,
            "sql_echo": False,
        },
        "redis": {
            "host": "${REDIS_HOST:-localhost}",
            "port": 6379,
            "password": "",
            "db": 0,
            "cache_ttl": 3600,
        },
        "services": {"stop_managed_on_exit": True},
        "logging": {
            "level": "info",
            "file": "logs/app.log",
            "max_bytes": 10485760,
            "backup_count": 5,
        },
        "security": {
            "audit": {
                "enabled": True,
                "file": "logs/security_audit.log",
                "log_tool_calls": True,
                "log_auth_events": True,
            },
            "headers": {
                "enabled": True,
                "hsts": True,
                "hsts_max_age": 31_536_000,
                "hsts_include_subdomains": False,
                "frame_options": "DENY",
                "content_type_options": True,
                "referrer_policy": "strict-origin-when-cross-origin",
                "content_security_policy": "default",
            },
            "rate_limit": {
                "enabled": False,
            },
            "agent_policy": {
                "enabled": True,
                "block_sensitive_tools_when_untrusted": True,
                "block_mutating_http_when_untrusted": True,
                "untrusted_channels": ["qq", "telegram"],
                "untrusted_tools": [
                    "web_fetch",
                    "web_search",
                    "web_scrape",
                    "http_fetch",
                ],
                "sensitive_tools": [
                    "host_read_file",
                    "host_write_file",
                    "host_delete_path",
                    "host_list_dir",
                    "host_run_command",
                    "host_search",
                ],
            },
        },
    }


class Config:
    _instance: "Config | None" = None

    def __new__(cls, config_file: str = "config.yaml") -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_file: str = "config.yaml"):
        if self._initialized:
            return

        self.project_root = get_project_root()
        self.default_config_file = self.project_root / "config" / "default_config.yaml"

        cfg_dir = os.environ.get("LY_NEXT_CONFIG_DIR", "").strip()
        if cfg_dir:
            dr = Path(cfg_dir).expanduser().resolve()
            dr.mkdir(parents=True, exist_ok=True)
            self.data_root = dr
            self.config_file = dr / config_file
        else:
            self.data_root = get_data_root()
            self.config_file = self.data_root / config_file

        self._config: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}
        self._bootstrap_user_config_file()
        self.load()
        self._bootstrap_data_assets()
        self._initialized = True

    def _bootstrap_user_config_file(self) -> bool:
        """Create ``config.yaml`` from template if missing. Returns True if a new file was written."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        if self.config_file.exists():
            return False
        if self.default_config_file.is_file():
            shutil.copy2(self.default_config_file, self.config_file)
            return True
        packaged = _packaged_default_config_path()
        if packaged.is_file():
            shutil.copy2(packaged, self.config_file)
            return True
        self._config = copy.deepcopy(_load_yaml_defaults())
        self.save()
        return True

    def _bootstrap_data_assets(self) -> dict[str, int]:
        prompts_cfg = self.get("agent.prompts", {}) or {}
        sub = "prompts"
        if isinstance(prompts_cfg, dict):
            sub = str(prompts_cfg.get("prompts_dir") or "prompts").strip() or "prompts"
        return bootstrap_data_assets(self.data_root, prompts_subdir=sub)

    def ensure_initialized(self) -> dict[str, Any]:
        """Ensure config file exists on disk and reload. Safe to call multiple times."""
        created = self._bootstrap_user_config_file()
        self.load()
        data_assets = self._bootstrap_data_assets()
        try:
            resolved = self.config_file.resolve()
            exists = resolved.is_file()
        except Exception:
            resolved = self.config_file
            exists = self.config_file.exists()
        return {
            "created": created,
            "exists": exists,
            "path": str(resolved),
            "parent_writable": os.access(self.config_file.parent, os.W_OK),
            "data_assets": data_assets,
        }

    def load(self) -> None:
        try:
            if self.config_file.exists():
                with open(self.config_file, encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
            else:
                self._config = copy.deepcopy(_load_yaml_defaults())
                self.save()
        except Exception:
            self._config = copy.deepcopy(_load_yaml_defaults())
            self.save()

        default_config = _resolve_env_vars(copy.deepcopy(_load_yaml_defaults()))
        self._config = _resolve_env_vars(self._config)
        self._config = self._merge_config(default_config, self._config)
        self._config = _resolve_env_vars(self._config)
        self._migrate_legacy_server_bind()
        self._migrate_auth_whitelist()
        self._migrate_onebot11_config()
        self._migrate_telegram_config()
        self._migrate_plugins_security_profile()
        self._cache.clear()

    def _plugins_local_has_candidates(self) -> bool:
        local = self.project_root / "plugins" / "local"
        if not local.is_dir():
            return False
        try:
            for item in local.iterdir():
                if item.name.startswith("."):
                    continue
                if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
                    return True
                if item.is_dir() and (item / "__init__.py").is_file():
                    return True
        except OSError:
            return False
        return False

    def _migrate_plugins_security_profile(self) -> None:
        """Earlier releases defaulted to production, which disables plugins/local scanning."""
        plugins = self._config.get("plugins")
        if not isinstance(plugins, dict):
            return
        if plugins.get("directory_scan_auto_migrated"):
            return
        profile = str(plugins.get("security_profile") or "").strip().lower()
        modules = plugins.get("modules") or []
        if profile != "production" or (isinstance(modules, list) and modules):
            return
        if not self._plugins_local_has_candidates():
            return
        plugins["security_profile"] = "development"
        plugins["directory_scan_auto_migrated"] = True
        self._config["plugins"] = plugins
        try:
            from ly_next.core.logger import get_logger

            get_logger(__name__).warning(
                "plugins.security_profile was production while plugins/local contains "
                "plugins; switched to development so directory plugins load. To keep "
                "production, set plugins.modules explicitly and remove local plugins."
            )
        except Exception:
            pass
        self.save()

    def _migrate_telegram_config(self) -> None:
        bridge = self._config.get("bridge")
        if not isinstance(bridge, dict):
            return
        tg = bridge.get("telegram")
        if not isinstance(tg, dict):
            return
        changed = False
        allow_raw = tg.get("allow_from")
        if allow_raw is None:
            allow_raw = tg.get("allowed_user_ids")
        ids: list[int] = []
        try:
            from telegram_bot.allowlist import parse_allow_from

            ids, _ = parse_allow_from(allow_raw)
            if ids and list(tg.get("allowed_user_ids") or []) != ids:
                tg["allowed_user_ids"] = ids
                changed = True
            if ids and list(tg.get("allow_from") or []) != ids:
                tg["allow_from"] = ids
                changed = True
        except Exception:
            pass
        policy = str(tg.get("dm_policy") or "").strip().lower()
        if policy not in ("pairing", "allowlist", "open", "disabled"):
            if ids:
                tg["dm_policy"] = "allowlist"
            else:
                tg["dm_policy"] = "pairing"
            changed = True
        if changed:
            bridge["telegram"] = tg
            self._config["bridge"] = bridge
            self.save()

    def sanitize_auth_whitelist(self) -> list[str]:
        """移除放行工作台的不安全白名单项，若有变更则写回配置。"""
        auth = self._config.get("auth")
        if not isinstance(auth, dict):
            return []
        wl = auth.get("whitelist")
        if not isinstance(wl, list):
            return []
        unsafe = UNSAFE_WORKBENCH_WHITELIST | UNSAFE_DOCS_WHITELIST
        removed = [str(r) for r in wl if r in unsafe]
        if not removed:
            return []
        auth["whitelist"] = [r for r in wl if r not in unsafe]
        self.save()
        return removed

    def ensure_required_auth_whitelist(self) -> list[str]:
        """Ensure auth bootstrap endpoints remain reachable without API key."""
        auth = self._config.get("auth")
        if not isinstance(auth, dict):
            return []
        wl = auth.get("whitelist")
        if not isinstance(wl, list):
            wl = []
        added: list[str] = []
        seen = {str(r) for r in wl}
        for path in REQUIRED_AUTH_WHITELIST:
            if path not in seen:
                wl.append(path)
                added.append(path)
                seen.add(path)
        if added:
            auth["whitelist"] = wl
            self.save()
        return added

    def _migrate_auth_whitelist(self) -> None:
        self.sanitize_auth_whitelist()
        self.ensure_required_auth_whitelist()

    def _migrate_onebot11_config(self) -> None:
        default_onebot11_ws_paths: tuple[str, ...]
        try:
            from ly_next.core.plugin.loader import _ensure_plugins_import_path

            _ensure_plugins_import_path()
            from qq_onebot.bridge.paths import DEFAULT_ONEBOT11_WS_PATHS, merge_ws_paths

            default_onebot11_ws_paths = DEFAULT_ONEBOT11_WS_PATHS
        except ImportError:
            default_onebot11_ws_paths = ("/OneBotv11", "/onebot/v11/ws")

            def merge_ws_paths(configured: tuple[str, ...]) -> tuple[str, ...]:
                seen: set[str] = set()
                out: list[str] = []
                for item in (*configured, *default_onebot11_ws_paths):
                    norm = item if item.startswith("/") else f"/{item}"
                    if norm in seen:
                        continue
                    seen.add(norm)
                    out.append(norm)
                return tuple(out)

        bridge = self._config.get("bridge")
        if not isinstance(bridge, dict):
            bridge = {}
            self._config["bridge"] = bridge
        ob = bridge.get("onebot11")
        if not isinstance(ob, dict):
            ob = {}
            bridge["onebot11"] = ob

        legacy = self._config.get("onebotv11")
        changed = False
        if isinstance(legacy, dict) and legacy.get("access_token") and not ob.get("access_token"):
            ob["access_token"] = legacy["access_token"]
            changed = True

        raw_paths = ob.get("ws_paths")
        if isinstance(raw_paths, list):
            merged = list(merge_ws_paths(tuple(str(p) for p in raw_paths)))
            if merged != raw_paths:
                ob["ws_paths"] = merged
                changed = True
        elif not raw_paths:
            ob["ws_paths"] = list(default_onebot11_ws_paths)
            changed = True

        auth = self._config.get("auth")
        if isinstance(auth, dict):
            wl = auth.get("whitelist")
            if not isinstance(wl, list):
                wl = []
            existing = {str(x) for x in wl}
            for p in default_onebot11_ws_paths:
                if p not in existing:
                    wl.append(p)
                    changed = True
            auth["whitelist"] = wl

        if changed:
            self.save()

    def _migrate_legacy_server_bind(self) -> None:
        server = self._config.get("server")
        if not isinstance(server, dict):
            return
        if server.get("host") == "127.0.0.1":
            server["host"] = "0.0.0.0"
            self.save()

    def _merge_config(self, default: dict, user: dict) -> dict:
        return merge_config_dicts(default, user)

    def save(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            yaml.dump(
                self._config, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._cache:
            return self._cache[key]
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                self._cache[key] = default
                return default
        self._cache[key] = value
        return value

    def set(self, key: str, value: Any, save: bool = False) -> None:
        keys = key.split(".")
        cfg = self._config
        for k in keys[:-1]:
            cfg = cfg.setdefault(k, {})
        cfg[keys[-1]] = value
        self._cache.clear()
        if save:
            self.save()

    def to_dict(self) -> dict:
        return copy.deepcopy(self._config)

    def iter_database_urls(self) -> list[str]:
        db = self.get("database", {})
        user = quote(str(db.get("username", "postgres")), safe="")
        db_dict = db if isinstance(db, dict) else {}
        pw = resolve_database_password(db_dict)
        host = str(db.get("host", "localhost"))
        port = resolve_database_port(db_dict)
        dbname = quote(str(db.get("database", "ly_next")), safe="")

        urls: list[str] = []
        if pw:
            urls.append(f"postgresql+asyncpg://{user}:{quote(pw, safe='')}@{host}:{port}/{dbname}")
        else:
            urls.append(f"postgresql+asyncpg://{user}@{host}:{port}/{dbname}")

        try_unix = bool(db.get("try_unix_socket", True))
        if (
            try_unix
            and platform.system() != "Windows"
            and not pw
            and host in ("localhost", "127.0.0.1", "::1")
        ):
            sockets = ["/var/run/postgresql", "/tmp"]
            if platform.system() == "Darwin":
                sockets = ["/tmp", "/var/run/postgresql"]
            seen_sk = set()
            for sock in sockets:
                if sock in seen_sk:
                    continue
                seen_sk.add(sock)
                urls.append(f"postgresql+asyncpg://{user}@/{dbname}?host={quote(sock, safe='')}")

        out: list[str] = []
        seen: set[str] = set()
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def iter_asyncpg_dsn(self) -> list[str]:
        return [
            u.replace("postgresql+asyncpg://", "postgresql://", 1)
            for u in self.iter_database_urls()
        ]

    @property
    def database_url(self) -> str:
        urls = self.iter_database_urls()
        return urls[0] if urls else "postgresql+asyncpg://postgres@localhost:5432/ly_next"

    @property
    def redis_url(self) -> str:
        redis = self.get("redis", {})
        password = redis.get("password", "")
        host = redis.get("host", "localhost")
        port = redis.get("port", 6379)
        db = redis.get("db", 0)
        return (
            f"redis://:{password}@{host}:{port}/{db}" if password else f"redis://{host}:{port}/{db}"
        )

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None


config = Config()
