"""LY-NEXT plugin system."""

from ly_next.core.plugin.protocol import LyNextPlugin

__all__ = [
    "BridgeRegistry",
    "BuiltinPlugin",
    "LyNextPlugin",
    "MessageBridge",
    "PluginLoader",
    "PluginRegistry",
]


def __getattr__(name: str):
    if name == "BridgeRegistry":
        from ly_next.core.plugin.bridge_registry import BridgeRegistry

        return BridgeRegistry
    if name == "MessageBridge":
        from ly_next.core.plugin.bridge_registry import MessageBridge

        return MessageBridge
    if name == "BuiltinPlugin":
        from ly_next.core.plugin.builtin_plugin import BuiltinPlugin

        return BuiltinPlugin
    if name == "PluginLoader":
        from ly_next.core.plugin.loader import PluginLoader

        return PluginLoader
    if name == "PluginRegistry":
        from ly_next.core.plugin.registry import PluginRegistry

        return PluginRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
