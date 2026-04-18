import logging

from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.connectors.bookmap import BookmapConnector
from market_bridge.connectors.thinkorswim import ThinkorswimConnector
from market_bridge.connectors.tradovate import TradovateConnector
from market_bridge.tools.heatmap import register_heatmap_tools
from market_bridge.tools.levels import register_levels_tools
from market_bridge.tools.market_state import register_market_state_tools
from market_bridge.tools.order_flow import register_order_flow_tools
from market_bridge.tools.price import register_price_tools
from market_bridge.tools.volume import register_volume_tools

logger = logging.getLogger(__name__)


def _create_server() -> FastMCP:
    """Create and configure the MCP server with all tools and connectors."""
    from market_bridge.config import settings

    server = FastMCP("Market Bridge")

    cache = TTLCache(
        default_ttl=settings.cache.default_ttl,
        max_entries=settings.cache.max_entries,
    )

    tradovate = TradovateConnector(settings.tradovate)
    bookmap = BookmapConnector(settings.bookmap)
    thinkorswim = ThinkorswimConnector(settings.thinkorswim)

    register_price_tools(server, tradovate, thinkorswim, cache)
    register_volume_tools(server, tradovate, bookmap, thinkorswim, cache)
    register_order_flow_tools(server, tradovate, cache)
    register_levels_tools(server, tradovate, cache)
    register_heatmap_tools(server, tradovate, bookmap, cache)
    register_market_state_tools(server, cache)

    return server


try:
    mcp = _create_server()
except Exception as e:
    logger.error("Failed to initialize Market Bridge: %s", e)
    # Create a bare server so the module still imports (for tests with bad env)
    mcp = FastMCP("Market Bridge")


def main():
    mcp.run()
