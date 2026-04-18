from fastmcp import FastMCP


def register_market_state_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def get_market_state(
        symbol: str = "/ES",
    ) -> dict:
        """Get current market session info and context.

        Returns whether market is in RTH, overnight/globex session,
        pre-market, or closed. Includes session open/close times.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL)
        """
        # TODO: implement session awareness
        return {
            "symbol": symbol,
            "session": "unknown",
            "is_open": None,
            "rth_open": "09:30 ET",
            "rth_close": "16:00 ET",
            "globex_open": "18:00 ET",
            "globex_close": "17:00 ET",
            "source": "not_connected",
        }
