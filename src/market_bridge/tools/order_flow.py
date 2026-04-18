from __future__ import annotations

import logging

from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.connectors.tradovate import TradovateConnector

logger = logging.getLogger(__name__)


def register_order_flow_tools(
    mcp: FastMCP,
    tradovate: TradovateConnector,
    cache: TTLCache,
) -> None:
    @mcp.tool
    async def get_order_flow(
        symbol: str = "/ES",
        timeframe: str = "5m",
        bars: int = 20,
    ) -> dict:
        """Get order flow data including delta and cumulative delta.

        Shows buying vs selling pressure per bar. Positive delta means
        more aggressive buying; negative means more aggressive selling.

        Note: Delta is approximated from OHLCV data. True tick-level
        delta requires streaming tick data from Tradovate.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            timeframe: Candle timeframe for delta aggregation (1m, 5m, 15m, 30m, 1h)
            bars: Number of bars to return (max 200)
        """
        bars = min(bars, 200)
        cache_key = cache.make_key("orderflow", symbol, timeframe, str(bars))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if tradovate.is_configured:
            try:
                deltas = await tradovate.compute_order_flow(symbol, timeframe, bars)
                if deltas:
                    last = deltas[-1]
                    result = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "bars": len(deltas),
                        "deltas": [d.to_dict() for d in deltas],
                        "cumulative_delta": last.cumulative_delta,
                        "net_bias": "bullish" if last.cumulative_delta > 0 else "bearish",
                        "approximated": True,
                        "source": "tradovate",
                    }
                    cache.set(cache_key, result, ttl=15)
                    return result
            except Exception as e:
                logger.warning("Tradovate order flow failed: %s", e)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": 0,
            "deltas": [],
            "cumulative_delta": None,
            "net_bias": None,
            "source": "none",
            "error": "Order flow requires Tradovate. Set TRADOVATE_* environment variables.",
        }
