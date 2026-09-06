"""KiraAI BiliBili Direct Message adapter plugin.

Registers the BiliDM adapter bundled in the ``adapter/`` subdirectory
through the plugin adapter registration API.
"""

from core.plugin import BasePlugin, logger


class BiliDMPlugin(BasePlugin):
    """Plugin that exposes the BiliBili Direct Message adapter."""

    async def initialize(self):
        platform = await self.ctx.register_adapter("adapter")
        logger.info(f"BiliDM plugin registered adapter platform: {platform}")

    async def terminate(self):
        # Adapter instances are stopped and unregistered by the plugin manager.
        pass


plugin_class = BiliDMPlugin
