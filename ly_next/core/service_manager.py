import asyncio
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger
from ly_next.core.postgres_port import (
    resolve_database_password,
    resolve_database_port,
    sync_database_port_from_install,
)

logger = get_logger(__name__)

GITHUB_PROXY = "https://gh-proxy.com/"


def get_github_url(url: str) -> str:
    if "github.com" in url or "githubusercontent.com" in url:
        return f"{GITHUB_PROXY}{url}"
    return url


class ServiceStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNAVAILABLE = "unavailable"


class InstallStatus(Enum):
    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    name: str
    status: ServiceStatus
    message: str
    port: int | None = None
    install_status: InstallStatus | None = None
    install_guide: str | None = None


class ServiceManager:
    MAX_RETRIES = 3
    BASE_DELAY = 2
    MAX_DELAY = 10

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
        return get_project_root() / "data"

    @property
    def logs_dir(self) -> Path:
        return get_project_root() / "logs"

    def _should_auto_start(self) -> bool:
        return not self._is_docker and not self._is_production

    def _postgres_bin_dirs(self) -> list[Path]:
        seen: set[str] = set()
        dirs: list[Path] = []

        def add(p: Path) -> None:
            key = str(p.resolve()).lower()
            if key not in seen and p.is_dir():
                seen.add(key)
                dirs.append(p)

        for name in ("psql", "pg_ctl"):
            found = shutil.which(name)
            if found:
                add(Path(found).parent)

        if self._is_windows:
            for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
                root = os.environ.get(env_key)
                if not root:
                    continue
                base = Path(root) / "PostgreSQL"
                if not base.is_dir():
                    continue
                for ver_dir in sorted(base.iterdir(), reverse=True):
                    if ver_dir.is_dir():
                        add(ver_dir / "bin")

        return dirs

    def _postgres_executable(self, name: str) -> str | None:
        suffix = ".exe" if self._is_windows else ""
        for bin_dir in self._postgres_bin_dirs():
            candidate = bin_dir / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
        return shutil.which(name)

    def _list_windows_postgres_services(self) -> list[str]:
        if not self._is_windows:
            return []
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | "
                    "Select-Object -ExpandProperty Name",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    def _format_pg_error(self, err: Exception | None) -> str:
        if err is None:
            return "unknown error"
        msg = str(err).strip()
        if msg:
            return msg
        name = type(err).__name__
        if name == "NotImplementedError":
            return (
                "Unix socket not supported on this platform "
                "(use TCP: database.host=127.0.0.1, try_unix_socket=false)"
            )
        return name + (f": {err.args[0]!r}" if err.args else "")

    def _windows_is_admin(self) -> bool:
        if not self._is_windows:
            return True
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _windows_service_state(self, service_name: str) -> str | None:
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            text_out = (result.stdout or "") + (result.stderr or "")
            for line in text_out.splitlines():
                if "STATE" in line:
                    parts = line.split(":", 1)[-1].strip().split()
                    if len(parts) >= 2:
                        return parts[1]
        except Exception:
            pass
        return None

    def _resolve_postgres_port(self, db_config: dict[str, Any]) -> int:
        return resolve_database_port(db_config)

    async def _probe_postgres_tcp(
        self, *, database: str | None = None, timeout: float = 5.0
    ) -> tuple[bool, Exception | None]:
        import asyncpg

        db_config = config.get("database", {})
        if not isinstance(db_config, dict):
            db_config = {}
        host = str(db_config.get("host", "localhost") or "localhost")
        hosts = [host]
        if host in ("localhost", "127.0.0.1", "::1"):
            hosts = ["127.0.0.1", "localhost"]
        port = self._resolve_postgres_port(db_config)
        user = str(db_config.get("username", "postgres") or "postgres")
        password = resolve_database_password(db_config) or None
        dbname = database or str(db_config.get("database", "ly_next") or "ly_next")

        last_err: Exception | None = None
        for h in hosts:
            try:
                conn = await asyncpg.connect(
                    host=h,
                    port=port,
                    user=user,
                    password=password,
                    database=dbname,
                    timeout=timeout,
                )
                await conn.close()
                return True, None
            except Exception as e:
                last_err = e
        return False, last_err

    def _check_service_installed(self, service_name: str) -> InstallStatus:
        if service_name == "postgresql":
            if self._postgres_executable("psql") or self._postgres_executable("pg_ctl"):
                return InstallStatus.INSTALLED
            if self._list_windows_postgres_services():
                return InstallStatus.INSTALLED
            return InstallStatus.NOT_INSTALLED

        commands = {
            "redis": ["redis-server", "redis-cli"],
        }
        service_commands = commands.get(service_name, [service_name])
        for cmd in service_commands:
            if shutil.which(cmd):
                return InstallStatus.INSTALLED

        return InstallStatus.NOT_INSTALLED

    def _get_service_info(self, service_name: str) -> dict:
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
                    if "v=" in result.stdout:
                        info["version"] = result.stdout.split("v=")[1].split(" ")[0]
                except Exception:
                    pass

        elif service_name == "postgresql":
            cmd = self._postgres_executable("pg_ctl") or self._postgres_executable("psql")
            services = self._list_windows_postgres_services()
            if cmd or services:
                info["installed"] = True
                info["path"] = cmd or (services[0] if services else None)
            if cmd:
                try:
                    result = subprocess.run(
                        [cmd, "--version"], capture_output=True, text=True, timeout=5
                    )
                    out = result.stdout or result.stderr or ""
                    if "PostgreSQL" in out:
                        version_str = out.split("PostgreSQL", 1)[1].strip()
                        info["version"] = version_str.split(" ")[0]
                except Exception:
                    pass

            candidates: list[Path] = [
                Path.home() / "AppData" / "Local" / "PostgreSQL" / "data",
                Path("/var/lib/postgresql") / (info["version"] or "17") / "main",
                Path("/usr/local/var/postgres"),
            ]
            if self._is_windows:
                for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
                    root = os.environ.get(env_key)
                    if not root:
                        continue
                    base = Path(root) / "PostgreSQL"
                    if not base.is_dir():
                        continue
                    for ver_dir in sorted(base.iterdir(), reverse=True):
                        if ver_dir.is_dir():
                            candidates.append(ver_dir / "data")
            for data_dir in candidates:
                if data_dir.exists():
                    info["data_dir"] = str(data_dir)
                    break

        return info

    def _detect_postgres_config(self) -> dict:
        config = {
            "host": "localhost",
            "port": 5432,
            "username": "postgres",
            "password": "",
            "database": "ly_next",
        }

        if self._is_windows:
            possible_paths = [
                Path.home() / "AppData" / "Local" / "PostgreSQL",
                Path("C:/Program Files/PostgreSQL"),
                Path("C:/PostgreSQL"),
            ]
            for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
                root = os.environ.get(env_key)
                if root:
                    possible_paths.append(Path(root) / "PostgreSQL")
            for base_path in possible_paths:
                if base_path.exists():
                    for version_dir in sorted(base_path.iterdir(), reverse=True):
                        if version_dir.is_dir() and version_dir.name[0].isdigit():
                            data_dir = version_dir / "data"
                            if data_dir.exists():
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
        elif not self._is_windows:
            pg_ctl = self._postgres_executable("pg_ctl")
            if not pg_ctl:
                return config

        return config

    def _detect_redis_requirepass_live(self, host: str, port: int) -> str:
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
        results = {"redis": False, "postgresql": False}

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
6. Or run (admin): .\\install.ps1 -PostgreSQL
""",
            }
        else:
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
- Windows (project script): .\\install.ps1 -PostgreSQL
- Arch Linux: sudo pacman -S postgresql
""",
            }

        return guides.get(service_name, f"Please install {service_name} manually.")

    async def check_redis(self) -> ServiceInfo:
        import redis.asyncio as redis

        redis_config = config.get("redis", {})
        host = redis_config.get("host", "localhost")
        port = redis_config.get("port", 6379)
        password = redis_config.get("password", "")

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
        db_config = config.get("database", {})
        if not isinstance(db_config, dict):
            db_config = {}
        host = str(db_config.get("host", "localhost") or "localhost")
        port = self._resolve_postgres_port(db_config)
        database = str(db_config.get("database", "ly_next") or "ly_next")

        install_status = self._check_service_installed("postgresql")
        install_guide = (
            self._get_install_guide("postgresql")
            if install_status == InstallStatus.NOT_INSTALLED
            else None
        )

        ok, last_err = await self._probe_postgres_tcp(database=database)
        if not ok and not self._is_windows:
            import asyncpg

            for dsn in config.iter_asyncpg_dsn():
                try:
                    conn = await asyncpg.connect(dsn=dsn)
                    await conn.close()
                    ok = True
                    last_err = None
                    break
                except Exception as e:
                    last_err = e

        if ok:
            return ServiceInfo(
                name="PostgreSQL",
                status=ServiceStatus.RUNNING,
                message=f"Connected to {host}:{port}/{database}",
                port=port,
                install_status=install_status,
                install_guide=install_guide,
            )

        error_msg = self._format_pg_error(last_err)
        low = error_msg.lower()
        if "Connection refused" in error_msg or "ECONNREFUSED" in error_msg:
            return ServiceInfo(
                name="PostgreSQL",
                status=ServiceStatus.STOPPED,
                message=f"PostgreSQL not running at {host}:{port}",
                port=port,
                install_status=install_status,
                install_guide=install_guide,
            )
        hint = ""
        pw_cfg = str(db_config.get("password", "") or "").strip()
        if any(
            x in low
            for x in (
                "password",
                "authentication",
                "no password supplied",
                "connection was closed in the middle",
            )
        ) or (not pw_cfg and not resolve_database_password(db_config)):
            hint = (
                " — 请在 data/ly_next/config.yaml 设置 database.password"
                "（安装 PostgreSQL 时设置的 postgres 用户密码），"
                "或设置环境变量 POSTGRES_PASSWORD"
            )
        elif "does not exist" in low and "database" in low:
            hint = " — 请先创建数据库 ly_next，或修正 database.database"
        return ServiceInfo(
            name="PostgreSQL",
            status=ServiceStatus.UNAVAILABLE,
            message=f"PostgreSQL error: {error_msg}{hint}",
            port=port,
            install_status=install_status,
            install_guide=install_guide,
        )

    async def _start_redis(self) -> bool:
        if not self._should_auto_start():
            logger.debug("Skipping Redis auto-start (production or Docker mode)")
            return False

        install_status = self._check_service_installed("redis")
        if install_status == InstallStatus.NOT_INSTALLED:
            logger.error("Redis is not installed on this system.")
            logger.info(self._get_install_guide("redis"))
            return False

        redis_config = config.get("redis", {})
        host = redis_config.get("host", "127.0.0.1")
        port = redis_config.get("port", 6379)

        if host not in ("127.0.0.1", "localhost"):
            logger.error(f"Redis connection failed at {host}:{port}")
            logger.error(
                "Please check: 1) Service is running 2) Config is correct 3) Port is available"
            )
            return False

        redis_data_dir = self.data_dir / "redis"
        redis_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            cmd = ["redis-server", "--port", str(port), "--save", "900", "1", "--save", "300", "10"]
            logger.info(f"Starting Redis: {' '.join(cmd)}")

            if self._is_windows:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
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

    async def _try_start_windows_postgres_service(self) -> bool:
        services = self._list_windows_postgres_services()
        if not services:
            return False

        running = [s for s in services if self._windows_service_state(s) == "RUNNING"]
        if running:
            logger.debug("PostgreSQL Windows service already running: %s", ", ".join(running))
            return True

        if not self._windows_is_admin():
            logger.warning(
                "无法启动 PostgreSQL 服务：当前进程没有管理员权限。"
                "请以管理员打开终端执行 Start-Service %s，"
                "或在「服务」中启动 PostgreSQL Server 17，或运行: .\\install.ps1 -PostgreSQL",
                services[0],
            )
            return False

        started_any = False
        for svc in services:
            logger.info(f"Starting Windows PostgreSQL service: {svc}")
            try:
                completed = await asyncio.to_thread(
                    subprocess.run,
                    ["sc", "start", svc],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    check=False,
                )
                out = ((completed.stdout or "") + (completed.stderr or "")).lower()
                if completed.returncode == 0 or "already been started" in out or "running" in out:
                    started_any = True
                else:
                    logger.warning(
                        "sc start %s failed (code %s): %s",
                        svc,
                        completed.returncode,
                        (completed.stderr or completed.stdout or "")[:300],
                    )
            except Exception as e:
                logger.warning(f"sc start {svc} failed: {e}")
        return started_any

    async def _init_postgres(self) -> None:
        pg_data_dir = self.data_dir / "postgres"
        if (pg_data_dir / "PG_VERSION").exists():
            return
        initdb = self._postgres_executable("initdb")
        if not initdb:
            logger.error("initdb not found in PATH; cannot initialize PostgreSQL data directory.")
            raise FileNotFoundError("initdb")

        cmd = [initdb, "-D", str(pg_data_dir), "--encoding=UTF8", "--locale=C"]
        logger.info(f"Initializing PostgreSQL data directory: {' '.join(cmd)}")

        def _run_initdb() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

        completed = await asyncio.to_thread(_run_initdb)
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "")[:800]
            logger.error(f"initdb failed (exit {completed.returncode}): {err}")
            raise RuntimeError("initdb failed")

    async def _start_postgres(self) -> bool:
        if not self._should_auto_start():
            logger.debug("Skipping PostgreSQL auto-start (production or Docker mode)")
            return False

        install_status = self._check_service_installed("postgresql")
        if install_status == InstallStatus.NOT_INSTALLED:
            logger.error("PostgreSQL is not installed on this system.")
            logger.info(self._get_install_guide("postgresql"))
            return False

        db_config = config.get("database", {})
        host = db_config.get("host", "localhost")
        port = db_config.get("port", 5432)

        if host not in ("127.0.0.1", "localhost"):
            logger.error(f"PostgreSQL connection failed at {host}:{port}")
            logger.error(
                "Please check: 1) Service is running 2) Config is correct 3) Port is available"
            )
            return False

        pg_data_dir = self.data_dir / "postgres"
        pg_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            if self._is_windows and self._list_windows_postgres_services():
                port = self._resolve_postgres_port(db_config if isinstance(db_config, dict) else {})
                await self._try_start_windows_postgres_service()
                for _ in range(15):
                    await asyncio.sleep(1)
                    ok, _ = await self._probe_postgres_tcp(database="postgres")
                    if ok:
                        sync_database_port_from_install()
                        logger.success(f"PostgreSQL service reachable at 127.0.0.1:{port}")
                        return True
                logger.warning(
                    "PostgreSQL 服务未响应 TCP 连接；请检查服务是否运行、"
                    "database.password 与 data/ly_next/config.yaml 中的 database.port（当前探测端口 %s）",
                    port,
                )
                return False

            await self._init_postgres()

            pg_ctl = self._postgres_executable("pg_ctl")
            if not pg_ctl:
                logger.error("pg_ctl not found in PATH or Program Files/PostgreSQL")
                logger.info(self._get_install_guide("postgresql"))
                return False

            cmd = [pg_ctl, "start", "-D", str(pg_data_dir), "-o", f"-p {port}"]
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
                    if info.install_status == InstallStatus.NOT_INSTALLED and info.install_guide:
                        logger.warning("Redis auto-start failed. Service is not installed.")
                        logger.info(info.install_guide)
                    break

            return info

        return await self.check_redis()

    async def ensure_postgres(self, retries: int = MAX_RETRIES) -> ServiceInfo:
        for attempt in range(retries):
            info = await self.check_postgres()

            if info.status == ServiceStatus.RUNNING:
                return info

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
                    if info.install_status == InstallStatus.NOT_INSTALLED and info.install_guide:
                        logger.warning("PostgreSQL auto-start failed. Service is not installed.")
                        logger.info(info.install_guide)
                    break

            return info

        return await self.check_postgres()

    async def check_all_services(self) -> dict[str, ServiceInfo]:
        redis_info = await self.check_redis()
        postgres_info = await self.check_postgres()

        return {
            "redis": redis_info,
            "postgresql": postgres_info,
        }

    async def ensure_all_services(
        self, required_services: list[str] | None = None
    ) -> dict[str, ServiceInfo]:
        results = {}

        redis_info = await self.ensure_redis()
        results["redis"] = redis_info

        postgres_info = await self.ensure_postgres()
        results["postgresql"] = postgres_info

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
        pg_ctl = self._postgres_executable("pg_ctl") or "pg_ctl"
        cmd = [pg_ctl, "stop", "-D", str(pg_data_dir), "-m", "fast", "-w"]
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


_service_manager: ServiceManager | None = None


def get_service_manager() -> ServiceManager:
    global _service_manager
    if _service_manager is None:
        _service_manager = ServiceManager()
    return _service_manager
