from fastmcp import FastMCP


def register_price_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def get_price_data(
        symbol: str = "/ES",
        timeframe: str = "1h",
        bars: int = 50,
    ) -> dict:
        """Get OHLCV price data for a futures instrument.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            timeframe: Candle timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            bars: Number of bars to return
        """
        # TODO: implement via Tradovate connector
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": bars,
            "data": [],
            "source": "not_connected",
        }
