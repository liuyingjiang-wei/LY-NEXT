"""Loads HTTP API plugins from api.api_dir via APILoader."""

from __future__ import annotations

from ly_next.api.base import APIRegistry
from ly_next.api.loader import APILoader
from ly_next.core.app_context import AppContext
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.plugin.protocol import LyNextPlugin

logger = get_logger(__name__)


class DirectoryAPIPlugin(LyNextPlugin):
    name = "ly-next-directory-api"
    version = "1.0.0"
    description = "Scans api.api_dir for user HTTP API modules"

    def register_apis(self, api_registry: APIRegistry, ctx: AppContext) -> None:
        if not config.get("api.auto_load", True):
            logger.info("[DirectoryAPIPlugin] api.auto_load disabled")
            return
        loader = APILoader()
        loader.registry = api_registry
        loader.load_apis()
        ctx.extras["directory_api_count"] = len(api_registry.list_apis())
