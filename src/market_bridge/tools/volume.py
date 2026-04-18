from __future__ import annotations

import logging

from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.connectors.bookmap import BookmapConnector
from market_bridge.connectors.tradovate import TradovateConnector
from market_bridge.connectors.thinkorswim import ThinkorswimConnector

logger = logging.getLogger(__name__)


def register_volume_tools(
    mcp: FastMCP,
    tradovate: TradovateConnector,
    bookmap: BookmapConnector,
    thinkorswim: ThinkorswimConnector,
    cache: TTLCache,
) -> None:
    @mcp.tool
    async def get_volume_profile(
        symbol: str = "/ES",
        session: str = "rth",
        lookback_days: int = 1,
    ) -> dict:
        """Get volume-at-price profile for a futures instrument.

        Returns the volume distribution across price levels, including
        POC (Point of Control), VAH (Value Area High), and VAL (Value Area Low).

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            session: Session type (rth, globex, full)
            lookback_days: Number of days to include (1-5)
        """
        lookback_days = max(1, min(lookback_days, 5))
        cache_key = cache.make_key("volume", symbol, session, str(lookback_days))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Try Bookmap first (best volume data)
        if bookmap.is_configured:
            try:
                profile = bookmap.get_volume_profile(symbol, session, lookback_days)
                if profile.nodes:
                    result = {**profile.to_dict(), "source": "bookmap"}
                    cache.set(cache_key, result)
                    return result
            except Exception as e:
                logger.warning("Bookmap volume profile failed: %s", e)

        # Try Tradovate (computed from bars)
        if tradovate.is_configured:
            try:
                nodes, poc, vah, val = await tradovate.compute_volume_profile(
                    symbol, session, lookback_days
                )
                if nodes:
                    result = {
                        "symbol": symbol,
                        "session": session,
                        "lookback_days": lookback_days,
                        "poc": poc,
                        "vah": vah,
                        "val": val,
                        "nodes": [n.to_dict() for n in nodes],
                        "source": "tradovate",
                    }
                    cache.set(cache_key, result)
                    return result
            except Exception as e:
                logger.warning("Tradovate volume profile failed: %s", e)

        # Fall back to TOS CSV
        if thinkorswim.is_configured:
            try:
                profile = thinkorswim.get_volume_profile(symbol, session, lookback_days)
                if profile.nodes:
                    result = {**profile.to_dict(), "source": "thinkorswim"}
                    cache.set(cache_key, result)
                    return result
            except Exception as e:
                logger.warning("TOS volume profile failed: %s", e)

        return {
            "symbol": symbol,
            "session": session,
            "lookback_days": lookback_days,
            "poc": None,
            "vah": None,
            "val": None,
            "nodes": [],
            "source": "none",
            "error": "No data source configured. Set TRADOVATE_*, BOOKMAP_EXPORT_DIR, or TOS_EXPORT_DIR.",
        }
