"""Example drop-in plugin — copy to ``plugins/`` or reference via ``plugins.modules``."""

from ly_next.core.plugin.protocol import LyNextPlugin


class HelloPlugin(LyNextPlugin):
    name = "hello-example"
    version = "0.1.0"
    description = "Example plugin stub for documentation and tests"


plugin = HelloPlugin()
