import logging
import sys

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
    from market_bridge.config import get_settings
    settings = get_settings()

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


# Configure logging before server init so errors are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

try:
    mcp = _create_server()
except Exception as e:
    logger.critical("Failed to initialize Market Bridge: %s", e, exc_info=True)
    sys.exit(1)


def main() -> None:
    mcp.run()
