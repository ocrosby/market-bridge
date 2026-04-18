from fastmcp import FastMCP


def register_heatmap_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def get_heatmap(
        symbol: str = "/ES",
        depth: int = 10,
    ) -> dict:
        """Get liquidity heatmap data showing bid/ask depth.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            depth: Number of price levels on each side
        """
        # TODO: implement via Bookmap connector
        return {
            "symbol": symbol,
            "depth": depth,
            "bids": [],
            "asks": [],
            "source": "not_connected",
        }
