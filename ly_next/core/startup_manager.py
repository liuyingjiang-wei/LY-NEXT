"""First-run setup and dependency checks."""

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class DependencyStatus(Enum):
    """Dependency installation status."""

    INSTALLED = "installed"
    MISSING = "missing"
    NEEDS_UPDATE = "needs_update"


@dataclass
class DependencyInfo:
    """Dependency information container."""

    name: str
    status: DependencyStatus
    version: str | None = None
    required_version: str | None = None
    message: str = ""


class StartupManager:
    """Manages first-run setup and dependency checking."""

    REQUIRED_PACKAGES = [
        "fastapi",
        "redis",
        "asyncpg",
        "sqlalchemy",
    ]

    OPTIONAL_PACKAGES = [
        "langchain",
        "langgraph",
        "duckduckgo",
    ]

    REQUIRED_SERVICES = [
        "postgresql",
    ]

    OPTIONAL_SERVICES = [
        "redis",
    ]

    def __init__(self):
        self._project_root = get_project_root()
        self._is_first_run = self._check_first_run()
        self._platform = platform.system()

        self._using_uv = (
            self._check_command_available("uv") and (self._project_root / "uv.lock").exists()
        )
        self._packages_checked = False

    def _check_first_run(self) -> bool:
        """Check if this is the first time running the application.

        Returns:
            True if first run, False otherwise
        """
        marker_file = self._project_root / ".ly_next_initialized"
        return not marker_file.exists()

    def _mark_initialized(self) -> None:
        """Mark the application as initialized."""
        marker_file = self._project_root / ".ly_next_initialized"
        marker_file.touch()

    def _check_command_available(self, command: str) -> bool:
        """Check if a command is available in PATH.

        Args:
            command: Command name to check

        Returns:
            True if command is available, False otherwise
        """
        return shutil.which(command) is not None

    def _run_command(self, command: list[str], check: bool = True) -> tuple[int, str, str]:
        """Run a shell command and return the result.

        Args:
            command: Command and arguments as list
            check: Whether to raise exception on non-zero exit

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)

    async def check_python_package(self, package: str) -> DependencyInfo:
        """Check if a Python package is installed.

        Args:
            package: Package name to check

        Returns:
            DependencyInfo with package status
        """
        # If we're in a uv-managed environment with uv.lock, packages should be installed
        # We use a simple import check instead of pip show
        if self._using_uv:
            try:
                # Try to import the package to verify it's available
                import importlib

                # Handle special cases for package names
                import_name = package.replace("-", "_")
                importlib.import_module(import_name)
                return DependencyInfo(
                    name=package,
                    status=DependencyStatus.INSTALLED,
                    version="uv-managed",
                    message="Available via uv environment",
                )
            except ImportError:
                return DependencyInfo(
                    name=package,
                    status=DependencyStatus.MISSING,
                    message="Not installed in uv environment",
                )
        else:
            # Fall back to pip show for non-uv environments
            if self._check_command_available("uv"):
                code, stdout, stderr = self._run_command(["uv", "pip", "show", package])
            else:
                code, stdout, stderr = self._run_command(
                    [sys.executable, "-m", "pip", "show", package]
                )

        if code == 0:
            # Parse version from output
            version = None
            for line in stdout.split("\n"):
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                    break
            return DependencyInfo(
                name=package,
                status=DependencyStatus.INSTALLED,
                version=version,
                message=f"Installed: {version}",
            )
        else:
            return DependencyInfo(
                name=package, status=DependencyStatus.MISSING, message="Not installed"
            )

    def check_external_service(self, service: str) -> DependencyInfo:
        """Check if an external service command is available.

        Args:
            service: Service name (postgresql, redis, etc.)

        Returns:
            DependencyInfo with service status
        """
        # Map service names to their commands
        commands = {
            "postgresql": ["psql", "pg_ctl", "postgres"],
            "redis": ["redis-server", "redis-cli"],
            "mongodb": ["mongod", "mongo"],
        }

        service_commands = commands.get(service, [service])

        for cmd in service_commands:
            if self._check_command_available(cmd):
                return DependencyInfo(
                    name=service, status=DependencyStatus.INSTALLED, message=f"Found: {cmd}"
                )

        return DependencyInfo(
            name=service, status=DependencyStatus.MISSING, message="Not found in PATH"
        )

    async def check_all_dependencies(self) -> dict[str, DependencyInfo]:
        """Check all Python package dependencies.

        Returns:
            Dictionary of package name -> DependencyInfo
        """
        results = {}

        for package in self.REQUIRED_PACKAGES + self.OPTIONAL_PACKAGES:
            info = await self.check_python_package(package)
            results[package] = info

        return results

    def check_all_services(self) -> dict[str, DependencyInfo]:
        """Check all external service dependencies.

        Returns:
            Dictionary of service name -> DependencyInfo
        """
        results = {}

        for service in self.REQUIRED_SERVICES + self.OPTIONAL_SERVICES:
            info = self.check_external_service(service)
            results[service] = info

        return results

    async def install_missing_packages(self, packages: list[str]) -> bool:
        """Install missing Python packages using uv or pip.

        Args:
            packages: List of package names to install

        Returns:
            True if installation succeeded, False otherwise
        """
        if not packages:
            return True

        logger.info(f"Installing missing packages: {', '.join(packages)}")

        # Try uv first (preferred), fall back to pip
        if self._check_command_available("uv"):
            # Use uv directly as a command, not as Python module
            cmd = ["uv", "pip", "install"] + packages
            logger.info(f"Running: {' '.join(cmd)}")
        elif self._check_command_available("pip"):
            cmd = ["pip", "install"] + packages
            logger.info(f"Running: {' '.join(cmd)}")
        else:
            logger.error("Neither uv nor pip found in PATH")
            return False

        code, stdout, stderr = self._run_command(cmd)

        if code == 0:
            logger.info(f"Successfully installed: {', '.join(packages)}")
            return True
        else:
            logger.error(f"Failed to install packages: {stderr}")
            return False

    async def run_first_time_setup(self) -> None:
        """Perform first-time setup tasks.

        This method is called on first run and handles:
        - Environment validation
        - Creating necessary directories
        - Initial configuration
        """
        if not self._is_first_run:
            return

        logger.info("=" * 60)
        logger.info("First-time setup detected")
        logger.info("=" * 60)

        cfg_init = config.ensure_initialized()
        if cfg_init.get("created"):
            logger.info("First-run: created config at %s", cfg_init.get("path"))

        # Create necessary directories
        dirs_to_create = [
            self._project_root / "data" / "ly_next",
            self._project_root / "logs",
            self._project_root / "data" / "redis",
            self._project_root / "data" / "postgres",
        ]

        for directory in dirs_to_create:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")

        # In uv-managed environment, packages are pre-installed
        # Only check packages in non-uv environments
        if not self._using_uv:
            # Check for required packages
            missing_required = []
            for package in self.REQUIRED_PACKAGES:
                info = await self.check_python_package(package)
                if info.status == DependencyStatus.MISSING:
                    missing_required.append(package)

            if missing_required:
                logger.warning(f"Missing required packages: {', '.join(missing_required)}")
                logger.info("Installing missing packages...")
                success = await self.install_missing_packages(missing_required)
                if not success:
                    logger.error("Failed to install some required packages")
        else:
            logger.info("Using uv-managed environment - packages pre-installed")

        # Check external services
        for service in self.REQUIRED_SERVICES:
            info = self.check_external_service(service)
            if info.status == DependencyStatus.MISSING:
                logger.warning(
                    f"Required service '{service}' not found. Install to enable full functionality."
                )

        for service in self.OPTIONAL_SERVICES:
            info = self.check_external_service(service)
            if info.status == DependencyStatus.MISSING:
                logger.info(
                    f"Optional service '{service}' not found. LY-Next will run with reduced functionality."
                )

        # Mark as initialized
        self._mark_initialized()
        logger.info("First-time setup complete")
        logger.info("=" * 60)

    async def validate_environment(self) -> list[str]:
        """Validate the runtime environment.

        Returns:
            List of validation warnings/errors
        """
        issues = []

        # Check uv or pip
        if not self._check_command_available("uv") and not self._check_command_available("pip"):
            issues.append("Neither uv nor pip found in PATH")

        # Check project directory is writable
        if not os.access(self._project_root, os.W_OK):
            issues.append(f"Project directory is not writable: {self._project_root}")

        return issues

    def get_system_info(self) -> dict:
        """Get system information for debugging.

        Returns:
            Dictionary with system details
        """
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "cwd": os.getcwd(),
            "is_docker": os.getenv("DOCKER_CONTAINER") == "1",
            "is_production": os.getenv("ENV") == "production"
            or os.getenv("NODE_ENV") == "production",
        }


# Singleton instance
_startup_manager: StartupManager | None = None


def get_startup_manager() -> StartupManager:
    """Get the global StartupManager instance."""
    global _startup_manager
    if _startup_manager is None:
        _startup_manager = StartupManager()
    return _startup_manager
