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


def _minimal_fallback_defaults() -> dict[str, Any]:
    return {
        "server": {"host": "127.0.0.1", "port": 8000, "reload": False, "log_level": "info"},
        "cors": {"origins": ["*"]},
        "api": {
            "auto_load": True,
            "api_dir": "ly_next/apis",
            "security_profile": "development",
            "trusted_module_hashes": {},
        },
        "auth": {
            "enabled": True,
            "api_key": "",
            "header_name": "X-API-Key",
            "cookie_name": "ly_api_key",
            "allow_api_key_in_query": False,
            "cookie_secure": False,
            "whitelist": [
                "/docs",
                "/openapi.json",
                "/redoc",
                "/api/health",
                "/api/info",
                "/ly/login",
                "/ly/static/*",
            ],
        },
        "llm": {"default_provider": "openai", "request_timeout": 60},
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
        "agent": {
            "enabled": True,
            "max_steps": 6,
            "max_tools": 40,
            "verbose": False,
            "reasoning_mode": "react",
            "stream_output": True,
            "tool_policy": {
                "max_tier": "network",
                "allow_categories": [],
                "deny_tools": [],
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
                "documents_path": "",
                "top_k": 5,
                "chunk_size": 900,
                "chunk_overlap": 120,
                "min_similarity": 0.12,
                "use_embeddings": True,
                "embedding": {"model": "text-embedding-3-small", "config_ref": "rag_embedding_llm"},
            },
        },
        "tools": {
            "built_in": [
                "calculator",
                "format_json",
                "text_process",
                "regex_extract",
                "get_current_time",
                "url_parse",
                "http_fetch",
                "web_search",
                "web_scrape",
            ],
            "web_search": {"provider": "duckduckgo", "api_key": ""},
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

    def ensure_initialized(self) -> dict[str, Any]:
        """Ensure config file exists on disk and reload. Safe to call multiple times."""
        created = self._bootstrap_user_config_file()
        self.load()
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

        self._config = _resolve_env_vars(self._config)
        default_config = copy.deepcopy(_load_yaml_defaults())
        self._config = self._merge_config(default_config, self._config)
        self._cache.clear()

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
        pw = str(db.get("password", "") or "")
        host = str(db.get("host", "localhost"))
        port = int(db.get("port", 5432))
        dbname = quote(str(db.get("database", "ly_next")), safe="")

        urls: list[str] = []
        if pw:
            urls.append(f"postgresql+asyncpg://{user}:{quote(pw, safe='')}@{host}:{port}/{dbname}")
        else:
            urls.append(f"postgresql+asyncpg://{user}@{host}:{port}/{dbname}")

        try_unix = bool(db.get("try_unix_socket", True))
        if try_unix and not pw and host in ("localhost", "127.0.0.1", "::1"):
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
