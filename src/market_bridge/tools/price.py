from __future__ import annotations

import logging

from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.connectors.tradovate import TradovateConnector
from market_bridge.connectors.thinkorswim import ThinkorswimConnector

logger = logging.getLogger(__name__)


def register_price_tools(
    mcp: FastMCP,
    tradovate: TradovateConnector,
    thinkorswim: ThinkorswimConnector,
    cache: TTLCache,
) -> None:
    @mcp.tool
    async def get_price_data(
        symbol: str = "/ES",
        timeframe: str = "1h",
        bars: int = 50,
    ) -> dict:
        """Get OHLCV price data for a futures instrument.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            timeframe: Candle timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            bars: Number of bars to return (max 500)
        """
        bars = min(bars, 500)
        cache_key = cache.make_key("price", symbol, timeframe, str(bars))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Try Tradovate first (real-time API)
        if tradovate.is_configured:
            try:
                result_bars = await tradovate.get_bars(symbol, timeframe, bars)
                result = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "bars": len(result_bars),
                    "data": [b.to_dict() for b in result_bars],
                    "source": "tradovate",
                }
                cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning("Tradovate price fetch failed: %s", e)

        # Fall back to TOS CSV exports
        if thinkorswim.is_configured:
            try:
                result_bars = thinkorswim.get_price_bars(symbol, bars)
                if result_bars:
                    result = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "bars": len(result_bars),
                        "data": [b.to_dict() for b in result_bars],
                        "source": "thinkorswim",
                    }
                    cache.set(cache_key, result)
                    return result
            except Exception as e:
                logger.warning("TOS price fetch failed: %s", e)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": 0,
            "data": [],
            "source": "none",
            "error": "No data source configured. Set TRADOVATE_* or TOS_EXPORT_DIR environment variables.",
        }
