"""Auto-start Redis/PostgreSQL when possible; optional GitHub download proxy."""

import asyncio
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

# GitHub proxy for China network
GITHUB_PROXY = "https://gh-proxy.com/"


def get_github_url(url: str) -> str:
    """Get GitHub URL with proxy if needed.

    Args:
        url: Original GitHub URL

    Returns:
        Proxied URL if it's a GitHub URL, otherwise original
    """
    if "github.com" in url or "githubusercontent.com" in url:
        return f"{GITHUB_PROXY}{url}"
    return url


class ServiceStatus(Enum):
    """Service connection status."""

    RUNNING = "running"
    STOPPED = "stopped"
    UNAVAILABLE = "unavailable"


class InstallStatus(Enum):
    """Service installation status."""

    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """Service information container."""

    name: str
    status: ServiceStatus
    message: str
    port: int | None = None
    install_status: InstallStatus | None = None
    install_guide: str | None = None


class ServiceManager:
    """Manages external services (Redis, PostgreSQL) with auto-start capability.

    Features:
    - Auto-start services in development mode
    - Retry with exponential backoff
    - Support for Windows/Linux/macOS
    - Docker-aware (respects DOCKER_CONTAINER env var)
    """

    # Default connection retry settings
    MAX_RETRIES = 3
    BASE_DELAY = 2  # seconds
    MAX_DELAY = 10  # seconds

    def __init__(self):
        self._is_docker = os.getenv("DOCKER_CONTAINER") == "1"
        self._is_production = (
            os.getenv("NODE_ENV") == "production" or os.getenv("ENV") == "production"
        )
        self._is_windows = platform.system() == "Windows"
        self._is_tty = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False

        self._redis_server_proc: subprocess.Popen | None = None
        self._postgres_started_by_us = False

    @property
    def data_dir(self) -> Path:
        """Get data directory for service data."""
        return get_project_root() / "data"

    @property
    def logs_dir(self) -> Path:
        """Get logs directory."""
        return get_project_root() / "logs"

    def _should_auto_start(self) -> bool:
        """Check if services should be auto-started.

        Auto-start is enabled when:
        - Not in Docker container
        - Not in production mode
        - Running in TTY (interactive terminal)
        """
        return not self._is_docker and not self._is_production

    def _check_service_installed(self, service_name: str) -> InstallStatus:
        """Check if a service is installed on the system.

        Args:
            service_name: Name of the service (redis, postgresql)

        Returns:
            InstallStatus indicating if service is installed
        """
        commands = {
            "redis": ["redis-server", "redis-cli"],
            "postgresql": ["pg_ctl", "psql", "postgres"],
        }

        service_commands = commands.get(service_name, [service_name])
        for cmd in service_commands:
            if shutil.which(cmd):
                return InstallStatus.INSTALLED

        return InstallStatus.NOT_INSTALLED

    def _get_service_info(self, service_name: str) -> dict:
        """Get detailed information about installed service.

        Args:
            service_name: Name of the service (redis, postgresql)

        Returns:
            Dictionary with service information
        """
        info = {"installed": False, "version": None, "path": None, "data_dir": None}

        if service_name == "redis":
            cmd = shutil.which("redis-server")
            if cmd:
                info["installed"] = True
                info["path"] = cmd
                try:
                    result = subprocess.run(
                        [cmd, "--version"], capture_output=True, text=True, timeout=5
                    )
                    # Redis server v=7.2.3
                    if "v=" in result.stdout:
                        info["version"] = result.stdout.split("v=")[1].split(" ")[0]
                except Exception:
                    pass

        elif service_name == "postgresql":
            cmd = shutil.which("pg_ctl")
            if cmd:
                info["installed"] = True
                info["path"] = cmd
                try:
                    result = subprocess.run(
                        [cmd, "--version"], capture_output=True, text=True, timeout=5
                    )
                    # pg_ctl (PostgreSQL) 17.0
                    if "PostgreSQL" in result.stdout:
                        version_str = result.stdout.split("PostgreSQL")[1].strip()
                        info["version"] = version_str.split(" ")[0]
                except Exception:
                    pass

                # Try to find data directory
                for data_dir in [
                    Path.home() / "AppData" / "Local" / "PostgreSQL" / "data",
                    Path("C:/Program Files/PostgreSQL") / (info["version"] or "17") / "data",
                    Path("/var/lib/postgresql") / (info["version"] or "17") / "main",
                    Path("/usr/local/var/postgres"),
                ]:
                    if data_dir.exists():
                        info["data_dir"] = str(data_dir)
                        break

        return info

    def _detect_postgres_config(self) -> dict:
        """Detect PostgreSQL configuration from installed instance.

        Returns:
            Dictionary with detected configuration
        """
        config = {
            "host": "localhost",
            "port": 5432,
            "username": "postgres",
            "password": "",
            "database": "ly_next",
        }

        # Try to detect from pg_service.conf or postgresql.conf
        pg_ctl = shutil.which("pg_ctl")
        if not pg_ctl:
            return config

        # Common PostgreSQL config locations on Windows
        if self._is_windows:
            possible_paths = [
                Path.home() / "AppData" / "Local" / "PostgreSQL",
                Path("C:/Program Files/PostgreSQL"),
                Path("C:/PostgreSQL"),
            ]
            for base_path in possible_paths:
                if base_path.exists():
                    # Find version directory
                    for version_dir in sorted(base_path.iterdir(), reverse=True):
                        if version_dir.is_dir() and version_dir.name[0].isdigit():
                            data_dir = version_dir / "data"
                            if data_dir.exists():
                                # Read postgresql.conf
                                conf_file = data_dir / "postgresql.conf"
                                if conf_file.exists():
                                    try:
                                        with open(conf_file) as f:
                                            for line in f:
                                                line = line.strip()
                                                if line.startswith("port") and "=" in line:
                                                    port = line.split("=")[1].strip().strip("'\"")
                                                    if port.isdigit():
                                                        config["port"] = int(port)
                                    except Exception:
                                        pass
                                break

        return config

    def _detect_redis_requirepass_live(self, host: str, port: int) -> str:
        """Read requirepass from a running Redis via CONFIG GET (matches runtime, not only redis.conf)."""
        candidates = [
            ["redis-cli", "-h", host, "-p", str(port), "CONFIG", "GET", "requirepass"],
            ["redis-cli", "CONFIG", "GET", "requirepass"],
        ]
        for cmd in candidates:
            try:
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if r.returncode != 0:
                    continue
                lines = [x.strip() for x in r.stdout.strip().splitlines() if x.strip()]
                if len(lines) >= 2 and lines[0].lower() == "requirepass":
                    val = lines[1].strip().strip('"').strip("'")
                    if val and val not in ("(nil)", "nil"):
                        return val
            except Exception:
                continue
        return ""

    def _detect_redis_config(self) -> dict:
        """Detect Redis host/port/password from config file + live CONFIG GET."""
        out = {"host": "127.0.0.1", "port": 6379, "password": "", "db": 0}

        redis_server = shutil.which("redis-server")
        if not redis_server:
            return out

        possible_paths = [
            Path("C:/Redis/redis.windows.conf"),
            Path("C:/Program Files/Redis/redis.windows.conf"),
            Path("/etc/redis/redis.conf"),
            Path("/usr/local/etc/redis.conf"),
        ]

        for conf_file in possible_paths:
            if conf_file.exists():
                try:
                    with open(conf_file) as f:
                        for line in f:
                            raw = line.strip()
                            if raw.startswith("#"):
                                continue
                            if raw.startswith("bind"):
                                parts = raw.split()
                                if len(parts) >= 2 and parts[1] not in ("", "*", "::"):
                                    out["host"] = parts[1].split(",")[0].strip()
                            elif raw.startswith("port"):
                                parts = raw.split()
                                if len(parts) >= 2 and parts[1].isdigit():
                                    out["port"] = int(parts[1])
                            elif raw.startswith("requirepass"):
                                parts = raw.split(maxsplit=1)
                                if len(parts) >= 2:
                                    out["password"] = parts[1].strip().strip('"').strip("'")
                except Exception:
                    pass
                break

        live_pw = self._detect_redis_requirepass_live(out["host"], out["port"])
        if live_pw:
            out["password"] = live_pw
        return out

    def _sync_detected_redis_to_config(self, detected: dict[str, str | int]) -> bool:
        """If config has empty redis.password but Redis uses requirepass, persist detected values."""
        if not isinstance(detected, dict):
            return False
        cur = config.get("redis", {})
        if not isinstance(cur, dict):
            cur = {}

        pw = str(cur.get("password", "") or "").strip()
        changed = False
        if not pw and detected.get("password"):
            config.set("redis.password", str(detected["password"]), save=False)
            changed = True
            logger.info("已将检测到的 Redis requirepass 写入 redis.password（本地配置文件）。")

        cfg_port = cur.get("port", 6379)
        det_port = detected.get("port")
        if det_port is not None and cfg_port == 6379 and int(det_port) != int(cfg_port):
            config.set("redis.port", int(det_port), save=False)
            changed = True

        if changed:
            config.save()
            config.load()
        return changed

    def _redis_error_needs_auth(self, msg: str) -> bool:
        m = msg.lower()
        return (
            "noauth" in m
            or "authentication required" in m
            or "wrongpass" in m
            or "invalid password" in m
        )

    async def auto_configure_services(self) -> dict:
        """Auto-configure services based on installed instances.

        Returns:
            Dictionary with configuration results
        """
        results = {"redis": False, "postgresql": False}

        # Check and configure Redis
        redis_info = self._get_service_info("redis")
        if redis_info["installed"]:
            logger.info(
                f"Found Redis {redis_info.get('version', 'unknown')} at {redis_info['path']}"
            )
            redis_config = self._detect_redis_config()
            logger.info(
                f"Detected Redis: host={redis_config.get('host')} port={redis_config.get('port')} "
                f"has_password={'yes' if redis_config.get('password') else 'no'}"
            )
            self._sync_detected_redis_to_config(redis_config)
            results["redis"] = True

        # Check and configure PostgreSQL
        pg_info = self._get_service_info("postgresql")
        if pg_info["installed"]:
            logger.info(
                f"Found PostgreSQL {pg_info.get('version', 'unknown')} at {pg_info['path']}"
            )
            pg_config = self._detect_postgres_config()
            logger.info(f"Detected PostgreSQL config: port={pg_config['port']}")
            results["postgresql"] = True

        return results

    def _get_install_guide(self, service_name: str) -> str:
        """Get installation guide for a service.

        Args:
            service_name: Name of the service (redis, postgresql)

        Returns:
            Installation guide string
        """
        # GitHub proxy for China network
        gh_proxy = "https://gh-proxy.com/"

        if self._is_windows:
            guides = {
                "redis": f"""
Redis Installation Guide (Windows):
1. Download Redis for Windows (with GitHub proxy):
   {gh_proxy}https://github.com/tporadowski/redis/releases
2. Or use Chocolatey: choco install redis-64
3. Or use winget: winget install Redis.Redis
4. After installation, add Redis to PATH or use full path
""",
                "postgresql": """
PostgreSQL Installation Guide (Windows):
1. Download PostgreSQL from: https://www.postgresql.org/download/windows/
2. Run the installer and follow the setup wizard
3. Remember the password for postgres user
4. Or use Chocolatey: choco install postgresql
5. Or use winget: winget install PostgreSQL.PostgreSQL.17
""",
            }
        else:  # Linux/macOS
            guides = {
                "redis": """
Redis Installation Guide (Linux/macOS):
- Ubuntu/Debian: sudo apt update && sudo apt install redis-server
- CentOS/RHEL: sudo yum install redis
- macOS: brew install redis
- Arch Linux: sudo pacman -S redis
""",
                "postgresql": """
PostgreSQL Installation Guide (Linux/macOS):
- Ubuntu/Debian: sudo apt update && sudo apt install postgresql postgresql-contrib
- CentOS/RHEL: sudo yum install postgresql-server postgresql-contrib
- macOS: brew install postgresql@17
- Arch Linux: sudo pacman -S postgresql
""",
            }

        return guides.get(service_name, f"Please install {service_name} manually.")

    async def check_redis(self) -> ServiceInfo:
        """Check if Redis is available.

        Returns:
            ServiceInfo with current Redis status
        """
        import redis.asyncio as redis

        redis_config = config.get("redis", {})
        host = redis_config.get("host", "localhost")
        port = redis_config.get("port", 6379)
        password = redis_config.get("password", "")

        # Check installation status
        install_status = self._check_service_installed("redis")
        install_guide = (
            self._get_install_guide("redis")
            if install_status == InstallStatus.NOT_INSTALLED
            else None
        )

        async def _ping(pw: str) -> None:
            cl = redis.Redis(
                host=host,
                port=port,
                password=pw or None,
                decode_responses=True,
            )
            try:
                await cl.ping()
            finally:
                await cl.close()

        try:
            await _ping(password)

            return ServiceInfo(
                name="Redis",
                status=ServiceStatus.RUNNING,
                message=f"Connected to {host}:{port}",
                port=port,
                install_status=install_status,
                install_guide=install_guide,
            )
        except Exception as e:
            error_msg = str(e)
            if (not password) and self._redis_error_needs_auth(error_msg):
                det = self._detect_redis_config()
                det_pw = str(det.get("password") or "").strip()
                if det_pw:
                    try:
                        await _ping(det_pw)
                        config.set("redis.password", det_pw, save=True)
                        config.load()
                        logger.info("已根据 Redis requirepass 自动同步 redis.password。")
                        return ServiceInfo(
                            name="Redis",
                            status=ServiceStatus.RUNNING,
                            message=f"Connected to {host}:{port} (password synced from Redis)",
                            port=port,
                            install_status=install_status,
                            install_guide=install_guide,
                        )
                    except Exception as e2:
                        error_msg = str(e2)

            if "Connection refused" in error_msg or "ECONNREFUSED" in error_msg:
                return ServiceInfo(
                    name="Redis",
                    status=ServiceStatus.STOPPED,
                    message=f"Redis not running at {host}:{port}",
                    port=port,
                    install_status=install_status,
                    install_guide=install_guide,
                )
            return ServiceInfo(
                name="Redis",
                status=ServiceStatus.UNAVAILABLE,
                message=f"Redis error: {error_msg}",
                port=port,
                install_status=install_status,
                install_guide=install_guide,
            )

    async def check_postgres(self) -> ServiceInfo:
        """Check if PostgreSQL is available."""
        import asyncpg

        db_config = config.get("database", {})
        host = db_config.get("host", "localhost")
        port = db_config.get("port", 5432)
        database = db_config.get("database", "ly_next")

        install_status = self._check_service_installed("postgresql")
        install_guide = (
            self._get_install_guide("postgresql")
            if install_status == InstallStatus.NOT_INSTALLED
            else None
        )

        last_err: Exception | None = None
        for dsn in config.iter_asyncpg_dsn():
            try:
                conn = await asyncpg.connect(dsn=dsn)
                await conn.close()
                return ServiceInfo(
                    name="PostgreSQL",
                    status=ServiceStatus.RUNNING,
                    message=f"Connected to {host}:{port}/{database}",
                    port=port,
                    install_status=install_status,
                    install_guide=install_guide,
                )
            except Exception as e:
                last_err = e

        error_msg = str(last_err) if last_err else "PostgreSQL connection failed"
        if "Connection refused" in error_msg or "ECONNREFUSED" in error_msg:
            return ServiceInfo(
                name="PostgreSQL",
                status=ServiceStatus.STOPPED,
                message=f"PostgreSQL not running at {host}:{port}",
                port=port,
                install_status=install_status,
                install_guide=install_guide,
            )
        return ServiceInfo(
            name="PostgreSQL",
            status=ServiceStatus.UNAVAILABLE,
            message=f"PostgreSQL error: {error_msg}",
            port=port,
            install_status=install_status,
            install_guide=install_guide,
        )

    async def _start_redis(self) -> bool:
        """Attempt to start Redis server (like Yunzai).

        Returns:
            True if Redis was started successfully, False otherwise
        """
        if not self._should_auto_start():
            logger.debug("Skipping Redis auto-start (production or Docker mode)")
            return False

        # Check if Redis is installed
        install_status = self._check_service_installed("redis")
        if install_status == InstallStatus.NOT_INSTALLED:
            logger.error("Redis is not installed on this system.")
            logger.info(self._get_install_guide("redis"))
            return False

        redis_config = config.get("redis", {})
        host = redis_config.get("host", "127.0.0.1")
        port = redis_config.get("port", 6379)

        # Only auto-start if host is localhost
        if host not in ("127.0.0.1", "localhost"):
            logger.error(f"Redis connection failed at {host}:{port}")
            logger.error(
                "Please check: 1) Service is running 2) Config is correct 3) Port is available"
            )
            return False

        # Ensure data directory exists
        redis_data_dir = self.data_dir / "redis"
        redis_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Start Redis like Yunzai: spawn redis-server process
            cmd = ["redis-server", "--port", str(port), "--save", "900", "1", "--save", "300", "10"]
            logger.info(f"Starting Redis: {' '.join(cmd)}")

            if self._is_windows:
                # Windows: start in new process group
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                # Unix: start in background
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            for _ in range(10):
                await asyncio.sleep(1)
                if process.poll() is not None:
                    stderr = process.stderr.read().decode() if process.stderr else ""
                    logger.error(f"Redis process exited with code {process.returncode}")
                    if stderr:
                        logger.error(f"Error: {stderr[:500]}")
                    return False

                try:
                    import redis.asyncio as redis

                    client = redis.Redis(host=host, port=port, decode_responses=True)
                    await client.ping()
                    await client.close()
                    self._redis_server_proc = process
                    logger.success(f"Redis started successfully on {host}:{port}")
                    return True
                except Exception:
                    continue

            logger.error("Redis start timeout (10 seconds)")
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
            except Exception:
                pass
            return False

        except FileNotFoundError:
            logger.error("redis-server command not found. Please install Redis first.")
            logger.info(self._get_install_guide("redis"))
            return False
        except Exception as e:
            logger.error(f"Failed to start Redis: {e}")
            return False

    async def _start_postgres(self) -> bool:
        """Attempt to start PostgreSQL server (like Yunzai).

        Returns:
            True if PostgreSQL was started successfully, False otherwise
        """
        if not self._should_auto_start():
            logger.debug("Skipping PostgreSQL auto-start (production or Docker mode)")
            return False

        # Check if PostgreSQL is installed
        install_status = self._check_service_installed("postgresql")
        if install_status == InstallStatus.NOT_INSTALLED:
            logger.error("PostgreSQL is not installed on this system.")
            logger.info(self._get_install_guide("postgresql"))
            return False

        db_config = config.get("database", {})
        host = db_config.get("host", "localhost")
        port = db_config.get("port", 5432)

        # Only auto-start if host is localhost
        if host not in ("127.0.0.1", "localhost"):
            logger.error(f"PostgreSQL connection failed at {host}:{port}")
            logger.error(
                "Please check: 1) Service is running 2) Config is correct 3) Port is available"
            )
            return False

        # Ensure data directory exists
        pg_data_dir = self.data_dir / "postgres"
        pg_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Initialize PostgreSQL if needed
            await self._init_postgres()

            # Start PostgreSQL using pg_ctl
            cmd = ["pg_ctl", "start", "-D", str(pg_data_dir), "-o", f"-p {port}"]
            logger.info(f"Starting PostgreSQL: {' '.join(cmd)}")

            if self._is_windows:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            for _ in range(15):
                await asyncio.sleep(1)
                if process.poll() is not None:
                    stderr = process.stderr.read().decode() if process.stderr else ""
                    if process.returncode != 0:
                        logger.error(f"PostgreSQL start failed (exit code {process.returncode})")
                        if stderr:
                            logger.error(f"Error: {stderr[:500]}")
                        return False

                try:
                    import asyncpg

                    conn = await asyncpg.connect(
                        host=host,
                        port=port,
                        user=db_config.get("username", "postgres"),
                        password=db_config.get("password", ""),
                        database="postgres",
                    )
                    await conn.close()
                    self._postgres_started_by_us = True
                    logger.success(f"PostgreSQL started successfully on {host}:{port}")
                    return True
                except Exception:
                    continue

            logger.error("PostgreSQL start timeout (15 seconds)")
            return False

        except FileNotFoundError:
            logger.error("pg_ctl command not found. Please install PostgreSQL first.")
            logger.info(self._get_install_guide("postgresql"))
            return False
        except Exception as e:
            logger.error(f"Failed to start PostgreSQL: {e}")
            return False

    async def ensure_redis(self, retries: int = MAX_RETRIES) -> ServiceInfo:
        """Ensure Redis is running, attempting auto-start if needed.

        Args:
            retries: Number of connection retries

        Returns:
            ServiceInfo with final Redis status
        """
        for attempt in range(retries):
            info = await self.check_redis()

            if info.status == ServiceStatus.RUNNING:
                return info

            im = (info.message or "").lower()
            if info.status == ServiceStatus.UNAVAILABLE and any(
                x in im
                for x in ("noauth", "wrongpass", "authentication required", "invalid password")
            ):
                return info

            # Try to start if stopped or unavailable (not installed)
            if attempt < retries - 1 and info.status in (
                ServiceStatus.STOPPED,
                ServiceStatus.UNAVAILABLE,
            ):
                if info.install_status == InstallStatus.NOT_INSTALLED:
                    logger.info(
                        f"Redis not installed, attempting auto-install ({attempt + 1}/{retries})..."
                    )
                else:
                    logger.info(f"Attempting to start Redis ({attempt + 1}/{retries})...")

                started = await self._start_redis()
                if started:
                    delay = min(self.BASE_DELAY * (2**attempt), self.MAX_DELAY)
                    await asyncio.sleep(delay)
                    continue
                else:
                    # If start failed, provide installation guide if available
                    if info.install_status == InstallStatus.NOT_INSTALLED and info.install_guide:
                        logger.warning("Redis auto-start failed. Service is not installed.")
                        logger.info(info.install_guide)
                    break

            return info

        return await self.check_redis()

    async def ensure_postgres(self, retries: int = MAX_RETRIES) -> ServiceInfo:
        """Ensure PostgreSQL is running, attempting auto-start if needed.

        Args:
            retries: Number of connection retries

        Returns:
            ServiceInfo with final PostgreSQL status
        """
        for attempt in range(retries):
            info = await self.check_postgres()

            if info.status == ServiceStatus.RUNNING:
                return info

            # Try to start if stopped or unavailable (not installed)
            if attempt < retries - 1 and info.status in (
                ServiceStatus.STOPPED,
                ServiceStatus.UNAVAILABLE,
            ):
                if info.install_status == InstallStatus.NOT_INSTALLED:
                    logger.info(
                        f"PostgreSQL not installed, attempting auto-install ({attempt + 1}/{retries})..."
                    )
                else:
                    logger.info(f"Attempting to start PostgreSQL ({attempt + 1}/{retries})...")

                started = await self._start_postgres()
                if started:
                    delay = min(self.BASE_DELAY * (2**attempt), self.MAX_DELAY)
                    await asyncio.sleep(delay)
                    continue
                else:
                    # If start failed, provide installation guide if available
                    if info.install_status == InstallStatus.NOT_INSTALLED and info.install_guide:
                        logger.warning("PostgreSQL auto-start failed. Service is not installed.")
                        logger.info(info.install_guide)
                    break

            return info

        return await self.check_postgres()

    async def check_all_services(self) -> dict[str, ServiceInfo]:
        """Check all managed services.

        Returns:
            Dictionary of service name -> ServiceInfo
        """
        redis_info = await self.check_redis()
        postgres_info = await self.check_postgres()

        return {
            "redis": redis_info,
            "postgresql": postgres_info,
        }

    async def ensure_all_services(
        self, required_services: list[str] | None = None
    ) -> dict[str, ServiceInfo]:
        """Ensure all required services are running.

        Args:
            required_services: List of service names that must be running.
                              If None, all services are checked but not required.

        Returns:
            Dictionary of service name -> ServiceInfo
        """
        results = {}

        # Check and start Redis
        redis_info = await self.ensure_redis()
        results["redis"] = redis_info

        # Check and start PostgreSQL
        postgres_info = await self.ensure_postgres()
        results["postgresql"] = postgres_info

        # Check if required services are available
        if required_services:
            unavailable = [
                name
                for name, info in results.items()
                if name in required_services and info.status != ServiceStatus.RUNNING
            ]
            if unavailable:
                service_names = ", ".join(unavailable)
                raise RuntimeError(f"Required services unavailable: {service_names}")

        return results

    async def shutdown_managed_services(self) -> None:
        """Stop Redis/PostgreSQL if this process started them (dev auto-start).

        Does not stop instances that were already running or remote services.
        Controlled by ``services.stop_managed_on_exit`` (default True).
        """
        if not config.get("services.stop_managed_on_exit", True):
            return
        await self._stop_managed_redis()
        await self._stop_managed_postgres()

    async def _stop_managed_redis(self) -> None:
        proc = self._redis_server_proc
        self._redis_server_proc = None
        if proc is None or proc.poll() is not None:
            return
        logger.info("Stopping Redis instance started by LY-NEXT...")
        try:
            proc.terminate()
            await asyncio.to_thread(proc.wait, 8)
        except Exception as e:
            logger.warning(f"Redis graceful stop: {e}")
        if proc.poll() is None:
            try:
                proc.kill()
                await asyncio.to_thread(proc.wait, 3)
            except Exception as e:
                logger.warning(f"Redis force stop: {e}")

    async def _stop_managed_postgres(self) -> None:
        if not self._postgres_started_by_us:
            return
        self._postgres_started_by_us = False
        pg_data_dir = self.data_dir / "postgres"
        if not pg_data_dir.is_dir():
            return
        cmd = ["pg_ctl", "stop", "-D", str(pg_data_dir), "-m", "fast", "-w"]
        logger.info("Stopping PostgreSQL instance started by LY-NEXT...")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=45)
        except asyncio.TimeoutError:
            logger.warning("PostgreSQL pg_ctl stop timed out")
        except FileNotFoundError:
            logger.warning("pg_ctl not found; skip PostgreSQL shutdown")
        except Exception as e:
            logger.warning(f"PostgreSQL stop: {e}")


# Singleton instance
_service_manager: ServiceManager | None = None


def get_service_manager() -> ServiceManager:
    """Get the global ServiceManager instance."""
    global _service_manager
    if _service_manager is None:
        _service_manager = ServiceManager()
    return _service_manager
