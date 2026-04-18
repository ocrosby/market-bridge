from fastmcp import FastMCP


def register_volume_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def get_volume_profile(
        symbol: str = "/ES",
        session: str = "rth",
        lookback_days: int = 1,
    ) -> dict:
        """Get volume-at-price profile for a futures instrument.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
            session: Session type (rth, globex, full)
            lookback_days: Number of days to include
        """
        # TODO: implement via Bookmap/Tradovate connector
        return {
            "symbol": symbol,
            "session": session,
            "lookback_days": lookback_days,
            "profile": [],
            "source": "not_connected",
        }
