"""Redis cache (async)."""

import asyncio
import json
import os
import platform
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

import redis.asyncio as redis

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


REDIS_CONFIG = {
    "MAX_RETRIES": 3,
    "CONNECT_TIMEOUT": 10000,
    "MAX_COMMAND_QUEUE": 5000,
    "MIN_POOL_SIZE": 3,
    "MAX_POOL_SIZE": 50,
    "HEALTH_CHECK_INTERVAL": 30000,
}


class Cache:
    _instance: "Cache | None" = None

    def __new__(cls) -> "Cache":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._client: redis.Redis | None = None
        self._initialized = True
        self._is_docker = os.getenv("DOCKER_CONTAINER") == "1"
        self._is_production = (
            os.getenv("ENV") == "production" or os.getenv("NODE_ENV") == "production"
        )
        self._health_check_task: asyncio.Task | None = None

    def _should_auto_start(self) -> bool:
        return not self._is_docker and not self._is_production

    def _get_optimal_pool_size(self) -> int:
        cpu_count = os.cpu_count() or 1
        memory_gb = 4
        try:
            import psutil

            memory_gb = psutil.virtual_memory().total / (1024**3)
        except ImportError:
            pass
        base_pool_size = cpu_count * 3
        memory_limit = 5 if memory_gb < 2 else 10 if memory_gb < 4 else 20 if memory_gb < 8 else 50
        pool_size = min(base_pool_size, memory_limit)
        return max(REDIS_CONFIG["MIN_POOL_SIZE"], min(pool_size, REDIS_CONFIG["MAX_POOL_SIZE"]))

    def _mask_redis_url(self, url: str) -> str:
        if not url:
            return url
        return url.replace(r":([^@:]+)@", ":******@")

    async def connect(self) -> None:
        if self._client is not None:
            return

        redis_url = config.redis_url
        pool_size = self._get_optimal_pool_size()

        logger.info(f"Connecting to Redis (pool size: {pool_size})...")
        logger.debug(f"Redis URL: {self._mask_redis_url(redis_url)}")

        self._client = redis.from_url(
            redis_url,
            max_connections=pool_size,
            socket_connect_timeout=REDIS_CONFIG["CONNECT_TIMEOUT"] / 1000.0,
            socket_timeout=REDIS_CONFIG["CONNECT_TIMEOUT"] / 1000.0,
            health_check_interval=REDIS_CONFIG["HEALTH_CHECK_INTERVAL"] / 1000.0,
            retry_on_timeout=True,
        )
        await self._attempt_connection()

    async def _attempt_connection(self, retries: int = 0) -> None:
        while retries < REDIS_CONFIG["MAX_RETRIES"]:
            try:
                await self._client.ping()
                logger.info("Redis connected successfully")
                self._start_health_check()
                return
            except Exception as e:
                retries += 1
                error_msg = str(e)
                logger.warning(
                    f"Redis connection attempt {retries}/{REDIS_CONFIG['MAX_RETRIES']} failed: {error_msg}"
                )

                if retries < REDIS_CONFIG["MAX_RETRIES"]:
                    if "Connection refused" in error_msg or "ECONNREFUSED" in error_msg:
                        if self._should_auto_start():
                            logger.info("Attempting to start local Redis service...")
                            started = await self._start_local_redis()
                            if started:
                                wait_time = 2 + retries * 1
                                logger.info(f"Waiting {wait_time}s for Redis to start...")
                                await asyncio.sleep(wait_time)
                                continue
                    else:
                        break
                else:
                    self._handle_connection_failure(e)

    async def _start_local_redis(self) -> bool:
        if not self._should_auto_start():
            return False

        is_windows = platform.system() == "Windows"
        redis_data_dir = config.project_root / "data" / "redis"
        redis_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            if is_windows:
                redis_candidates = [
                    "redis-server",
                    r"C:\Program Files\Redis\redis-server.exe",
                    r"C:\Redis\redis-server.exe",
                ]
                for candidate in redis_candidates:
                    exe: str | None = None
                    if "\\" in candidate or "/" in candidate:
                        p = Path(candidate)
                        if p.is_file():
                            exe = str(p)
                    if exe is None:
                        w = shutil.which(candidate)
                        exe = w if w else None
                    if not exe:
                        continue

                    args = [
                        exe,
                        "--port",
                        "6379",
                        "--save",
                        "900",
                        "1",
                        "--save",
                        "300",
                        "10",
                        "--daemonize",
                        "yes",
                    ]
                    logger.info("Starting Redis: %s", " ".join(args))
                    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    if hasattr(subprocess, "DETACHED_PROCESS"):
                        flags |= subprocess.DETACHED_PROCESS
                    if hasattr(subprocess, "CREATE_NO_WINDOW"):
                        flags |= subprocess.CREATE_NO_WINDOW
                    subprocess.Popen(args, close_fds=False, creationflags=flags)
                    return True
                logger.warning("Redis not found in system. Please install Redis.")
                return False
            else:
                cmd = [
                    "redis-server",
                    "--port",
                    "6379",
                    "--daemonize",
                    "yes",
                    "--dir",
                    str(redis_data_dir),
                    "--save",
                    "900",
                    "1",
                    "--save",
                    "300",
                    "10",
                ]
                arch_options = (await self._get_architecture_options()).strip()
                if arch_options:
                    cmd.extend(arch_options.split())
                logger.info("Starting Redis: %s", " ".join(cmd))
                subprocess.run(cmd, check=True)
                return True
        except Exception as e:
            logger.error(f"Failed to start Redis: {e}")
            return False

    async def _get_architecture_options(self) -> str:
        if platform.system() == "Windows":
            return ""
        try:
            result = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=5)
            arch = result.stdout.strip()
            if "aarch64" not in arch and "arm64" not in arch:
                return ""
            result = subprocess.run(
                ["redis-server", "-v"], capture_output=True, text=True, timeout=5
            )
            version_output = result.stdout
            import re

            version_match = version_output and re.search(r"v=(\d+)\.(\d+)", version_output)
            if not version_match:
                return ""
            major, minor = int(version_match[1]), int(version_match[2])
            if major > 6 or (major == 6 and minor >= 0):
                return " --ignore-warnings ARM64-COW-BUG"
        except Exception:
            pass
        return ""

    def _start_health_check(self) -> None:
        if self._health_check_task is not None:
            return
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def _health_check_loop(self) -> None:
        while True:
            await asyncio.sleep(REDIS_CONFIG["HEALTH_CHECK_INTERVAL"])
            if self._client is None:
                continue
            try:
                await self._client.ping()
            except Exception as e:
                logger.warning(f"Redis health check failed: {e}")

    async def disconnect(self) -> None:
        if self._health_check_task:
            self._health_check_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._health_check_task
            self._health_check_task = None

        if self._client:
            with suppress(Exception):
                await self._client.aclose()
            self._client = None
            logger.info("Redis disconnected")

    def _handle_connection_failure(self, error: Exception) -> None:
        logger.error(f"Redis connection failed: {error}")
        logger.error(
            "Please check: 1) Service running 2) Config correct 3) Port available 4) Network OK"
        )
        if not self._is_production:
            logger.error("Manual start: redis-server --daemonize yes")

    async def get(self, key: str) -> Any | None:
        if self._client is None:
            await self.connect()
        try:
            value = await self._client.get(key)
            if value is None:
                return None
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if self._client is None:
            await self.connect()
        try:
            ttl = ttl or config.get("redis.cache_ttl", 3600)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            await self._client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        if self._client is None:
            await self.connect()
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False

    async def exists(self, key: str) -> bool:
        if self._client is None:
            await self.connect()
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists error: {e}")
            return False

    async def incr(self, key: str, amount: int = 1) -> int:
        if self._client is None:
            await self.connect()
        try:
            return await self._client.incrby(key, amount)
        except Exception as e:
            logger.error(f"Cache incr error: {e}")
            return 0

    async def keys(self, pattern: str = "*") -> list[str]:
        if self._client is None:
            await self.connect()
        try:
            return await self._client.keys(pattern)
        except Exception as e:
            logger.error(f"Cache keys error: {e}")
            return []

    async def flush(self) -> bool:
        if self._client is None:
            await self.connect()
        try:
            await self._client.flushdb()
            return True
        except Exception as e:
            logger.error(f"Cache flush error: {e}")
            return False


cache = Cache()
