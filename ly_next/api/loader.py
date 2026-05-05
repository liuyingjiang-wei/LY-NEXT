"""API Loader."""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from ly_next.api.base import APIRegistry, BaseAPI, create_api_from_dict
from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class APILoader:
    """API Loader for auto-discovering and loading APIs."""

    def __init__(self):
        self._loaded_modules: dict[str, Any] = {}
        self.registry = APIRegistry()

    def _get_api_dir(self) -> Path:
        """Get API directory from config.

        If the configured path is missing but ``ly_next/apis`` exists (built-in samples),
        use that path so legacy ``api_dir: apis`` installs still load modules.
        """
        api_dir = config.get("api.api_dir", "ly_next/apis")
        primary = get_project_root() / api_dir
        if primary.is_dir():
            return primary
        fallback = get_project_root() / "ly_next/apis"
        if fallback.is_dir() and fallback.resolve() != primary.resolve():
            logger.info(
                f"[APILoader] API directory not found: {primary}, falling back to {fallback}"
            )
            return fallback
        return primary

    def _discover_modules(self, api_dir: Path) -> list[Path]:
        """Discover API modules in directory."""
        if not api_dir.exists():
            logger.info(f"[APILoader] API directory not found: {api_dir}")
            return []

        modules = []

        for item in api_dir.iterdir():
            if item.is_file() and item.suffix == ".py":
                if item.name.startswith("_"):
                    continue
                modules.append(item)
            elif item.is_dir():
                init_file = item / "__init__.py"
                if init_file.exists():
                    modules.append(init_file)

        return sorted(modules, key=lambda x: x.name)

    def _load_module_from_file(self, file_path: Path) -> Any | None:
        """Load module from Python file."""
        module_name = file_path.stem

        if file_path.suffix == ".py":
            spec = importlib.util.spec_from_file_location(module_name, file_path)
        else:
            spec = importlib.util.spec_from_file_location(f"{module_name}.__init__", file_path)

        if not spec or not spec.loader:
            return None

        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self._loaded_modules[module_name] = module
            return module
        except Exception as e:
            logger.error(f"[APILoader] Failed to load module {module_name}: {e}")
            return None

    def _extract_api_from_module(self, module: Any) -> list[BaseAPI]:
        """Extract API instances from module."""
        apis: list[BaseAPI] = []
        seen: set[int] = set()

        if hasattr(module, "default"):
            api_def = module.default
            if isinstance(api_def, dict):
                api = create_api_from_dict(api_def)
                apis.append(api)
                seen.add(id(api))
            elif isinstance(api_def, BaseAPI):
                apis.append(api_def)
                seen.add(id(api_def))

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            if attr_name == "default":
                continue
            attr = getattr(module, attr_name)
            if isinstance(attr, BaseAPI):
                if id(attr) in seen:
                    continue
                apis.append(attr)
                seen.add(id(attr))

        return apis

    def load_from_directory(self, directory: str | Path) -> APIRegistry:
        """Load APIs from a specific directory."""
        api_dir = Path(directory)
        if not api_dir.is_absolute():
            api_dir = get_project_root() / api_dir

        logger.info(f"[APILoader] Loading APIs from: {api_dir}")

        modules = self._discover_modules(api_dir)
        logger.info(f"[APILoader] Found {len(modules)} potential API modules")

        for module_path in modules:
            module = self._load_module_from_file(module_path)
            if module:
                apis = self._extract_api_from_module(module)
                for api in apis:
                    self.registry.register(api)
                    logger.debug(f"[APILoader] Registered API: {api.name}")

        return self.registry

    def load_apis(self) -> APIRegistry:
        """Load APIs from configured directory."""
        if not config.get("api.auto_load", True):
            logger.info("[APILoader] Auto-load disabled")
            return self.registry

        api_dir = self._get_api_dir()
        return self.load_from_directory(api_dir)

    def reload(self) -> APIRegistry:
        """Reload all APIs."""
        self._loaded_modules.clear()
        self.registry = APIRegistry()
        return self.load_apis()

    def get_registry(self) -> APIRegistry:
        """Get the API registry."""
        return self.registry
