from fastmcp import FastMCP


def register_order_flow_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def get_order_flow(
        symbol: str = "/ES",
        timeframe: str = "5m",
        bars: int = 20,
    ) -> dict:
        """Get order flow data including delta and cumulative delta.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            timeframe: Candle timeframe for delta aggregation
            bars: Number of bars to return
        """
        # TODO: implement via Tradovate connector
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": bars,
            "deltas": [],
            "cumulative_delta": None,
            "source": "not_connected",
        }
