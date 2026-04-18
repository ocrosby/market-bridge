from __future__ import annotations

import logging

from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.connectors.tradovate import TradovateConnector

logger = logging.getLogger(__name__)


def register_levels_tools(
    mcp: FastMCP,
    tradovate: TradovateConnector,
    cache: TTLCache,
) -> None:
    @mcp.tool
    async def get_levels(
        symbol: str = "/ES",
        session: str = "rth",
    ) -> dict:
        """Get key support/resistance levels including POC, VAH, VAL, and HVNs.

        Returns the Point of Control, Value Area High/Low, session
        high/low, and high/low volume nodes computed from volume profile.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            session: Session type (rth, globex, full)
        """
        cache_key = cache.make_key("levels", symbol, session)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if tradovate.is_configured:
            try:
                levels = await tradovate.compute_levels(symbol, session)
                result = {**levels.to_dict(), "source": "tradovate"}
                cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning("Tradovate levels computation failed: %s", e)

        return {
            "symbol": symbol,
            "session": session,
            "poc": None,
            "vah": None,
            "val": None,
            "session_high": None,
            "session_low": None,
            "high_volume_nodes": [],
            "low_volume_nodes": [],
            "source": "none",
            "error": "Levels require Tradovate. Set TRADOVATE_* environment variables.",
        }
