from __future__ import annotations

import logging

from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.connectors.bookmap import BookmapConnector
from market_bridge.connectors.tradovate import TradovateConnector

logger = logging.getLogger(__name__)


def register_heatmap_tools(
    mcp: FastMCP,
    tradovate: TradovateConnector,
    bookmap: BookmapConnector,
    cache: TTLCache,
) -> None:
    @mcp.tool
    async def get_heatmap(
        symbol: str = "/ES",
        depth: int = 10,
    ) -> dict:
        """Get liquidity heatmap data showing bid/ask depth.

        Shows resting limit orders at each price level — large clusters
        indicate potential support/resistance zones.

        Bookmap export data is preferred when available. Falls back to
        Tradovate DOM (depth of market) data.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            depth: Number of price levels on each side (max 20)
        """
        depth = min(depth, 20)
        cache_key = cache.make_key("heatmap", symbol, str(depth))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Try Bookmap first (best heatmap data)
        if bookmap.is_configured:
            try:
                heatmap = bookmap.get_heatmap(symbol, depth)
                if heatmap.bids or heatmap.asks:
                    result = {**heatmap.to_dict(), "source": "bookmap"}
                    cache.set(cache_key, result)
                    return result
            except Exception as e:
                logger.warning("Bookmap heatmap failed: %s", e)

        # Fall back to Tradovate DOM
        if tradovate.is_configured:
            try:
                dom = await tradovate.get_dom(symbol, depth)
                result = {
                    "symbol": symbol,
                    "bids": [b.to_dict() for b in dom["bids"]],
                    "asks": [a.to_dict() for a in dom["asks"]],
                    "source": "tradovate_dom",
                }
                cache.set(cache_key, result, ttl=5)
                return result
            except Exception as e:
                logger.warning("Tradovate DOM fetch failed: %s", e)

        return {
            "symbol": symbol,
            "bids": [],
            "asks": [],
            "source": "none",
            "error": "Heatmap requires Bookmap exports or Tradovate. Set BOOKMAP_EXPORT_DIR or TRADOVATE_* variables.",
        }
