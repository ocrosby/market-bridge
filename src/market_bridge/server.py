from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.config import settings
from market_bridge.connectors.bookmap import BookmapConnector
from market_bridge.connectors.thinkorswim import ThinkorswimConnector
from market_bridge.connectors.tradovate import TradovateConnector
from market_bridge.tools.heatmap import register_heatmap_tools
from market_bridge.tools.levels import register_levels_tools
from market_bridge.tools.market_state import register_market_state_tools
from market_bridge.tools.order_flow import register_order_flow_tools
from market_bridge.tools.price import register_price_tools
from market_bridge.tools.volume import register_volume_tools

mcp = FastMCP("Market Bridge")

# Shared infrastructure
cache = TTLCache(
    default_ttl=settings.cache.default_ttl,
    max_entries=settings.cache.max_entries,
)

# Connectors
tradovate = TradovateConnector(settings.tradovate)
bookmap = BookmapConnector(settings.bookmap)
thinkorswim = ThinkorswimConnector(settings.thinkorswim)

# Register tools with access to connectors and cache
register_price_tools(mcp, tradovate, thinkorswim, cache)
register_volume_tools(mcp, tradovate, bookmap, thinkorswim, cache)
register_order_flow_tools(mcp, tradovate, cache)
register_levels_tools(mcp, tradovate, cache)
register_heatmap_tools(mcp, tradovate, bookmap, cache)
register_market_state_tools(mcp, cache)


def main():
    mcp.run()
