from fastmcp import FastMCP


def register_levels_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def get_levels(
        symbol: str = "/ES",
        session: str = "rth",
    ) -> dict:
        """Get key support/resistance levels including POC, VAH, VAL, and HVNs.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            session: Session type (rth, globex, full)
        """
        # TODO: implement via Tradovate/Bookmap connector
        return {
            "symbol": symbol,
            "session": session,
            "poc": None,
            "vah": None,
            "val": None,
            "high_volume_nodes": [],
            "low_volume_nodes": [],
            "source": "not_connected",
        }
