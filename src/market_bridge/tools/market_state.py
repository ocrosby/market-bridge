from __future__ import annotations

from datetime import datetime, timedelta

import pytz
from fastmcp import FastMCP

from market_bridge.cache import TTLCache
from market_bridge.models import FUTURES_SESSIONS, MarketSession, MarketStateInfo


def register_market_state_tools(mcp: FastMCP, cache: TTLCache) -> None:
    @mcp.tool
    def get_market_state(
        symbol: str = "/ES",
    ) -> dict:
        """Get current market session info and context.

        Returns whether the market is in RTH (Regular Trading Hours),
        globex/overnight session, or closed. Includes session
        open/close times and time until next session change.

        Args:
            symbol: Futures symbol (e.g. /ES, /NQ, /CL, /GC)
        """
        cache_key = cache.make_key("market_state", symbol)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        state = compute_market_state(symbol)
        result = {**state.to_dict(), "source": "computed"}
        cache.set(cache_key, result, ttl=10)
        return result


def compute_market_state(symbol: str) -> MarketStateInfo:
    """Determine current market session based on US Eastern time."""
    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)

    spec = FUTURES_SESSIONS.get(symbol)
    if not spec:
        return MarketStateInfo(
            symbol=symbol,
            session=MarketSession.CLOSED,
            is_open=False,
            current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
        )

    rth_open_h, rth_open_m = spec["rth_open"]
    rth_close_h, rth_close_m = spec["rth_close"]
    globex_open_h, globex_open_m = spec["globex_open"]
    globex_close_h, globex_close_m = spec["globex_close"]

    weekday = now.weekday()  # Mon=0, Sun=6
    hour = now.hour
    minute = now.minute
    time_val = hour * 60 + minute

    rth_open_val = rth_open_h * 60 + rth_open_m
    rth_close_val = rth_close_h * 60 + rth_close_m
    globex_open_val = globex_open_h * 60 + globex_open_m
    globex_close_val = globex_close_h * 60 + globex_close_m

    rth_open_str = f"{rth_open_h:02d}:{rth_open_m:02d} ET"
    rth_close_str = f"{rth_close_h:02d}:{rth_close_m:02d} ET"
    globex_open_str = f"{globex_open_h:02d}:{globex_open_m:02d} ET"
    globex_close_str = f"{globex_close_h:02d}:{globex_close_m:02d} ET"

    # Weekend: market closed from Friday 17:00 to Sunday 18:00 ET
    if weekday == 5:  # Saturday
        next_open = _next_weekday(now, 6).replace(hour=globex_open_h, minute=globex_open_m, second=0)
        return MarketStateInfo(
            symbol=symbol,
            session=MarketSession.CLOSED,
            is_open=False,
            current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
            rth_open=rth_open_str,
            rth_close=rth_close_str,
            globex_open=globex_open_str,
            globex_close=globex_close_str,
            next_session_change=next_open.strftime("%Y-%m-%d %H:%M ET") + " (Globex opens)",
        )

    if weekday == 6:  # Sunday
        if time_val < globex_open_val:
            next_open = now.replace(hour=globex_open_h, minute=globex_open_m, second=0)
            return MarketStateInfo(
                symbol=symbol,
                session=MarketSession.CLOSED,
                is_open=False,
                current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
                rth_open=rth_open_str,
                rth_close=rth_close_str,
                globex_open=globex_open_str,
                globex_close=globex_close_str,
                next_session_change=next_open.strftime("%Y-%m-%d %H:%M ET") + " (Globex opens)",
            )
        else:
            # Sunday evening, globex is open
            next_change = _next_weekday(now, 0).replace(hour=rth_open_h, minute=rth_open_m, second=0)
            return MarketStateInfo(
                symbol=symbol,
                session=MarketSession.GLOBEX,
                is_open=True,
                current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
                rth_open=rth_open_str,
                rth_close=rth_close_str,
                globex_open=globex_open_str,
                globex_close=globex_close_str,
                next_session_change=next_change.strftime("%Y-%m-%d %H:%M ET") + " (RTH opens)",
            )

    # Friday after globex close (17:00) -> closed for weekend
    if weekday == 4 and time_val >= globex_close_val:
        next_open = _next_weekday(now, 6).replace(hour=globex_open_h, minute=globex_open_m, second=0)
        return MarketStateInfo(
            symbol=symbol,
            session=MarketSession.CLOSED,
            is_open=False,
            current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
            rth_open=rth_open_str,
            rth_close=rth_close_str,
            globex_open=globex_open_str,
            globex_close=globex_close_str,
            next_session_change=next_open.strftime("%Y-%m-%d %H:%M ET") + " (Globex opens Sunday)",
        )

    # Weekday logic (Mon-Fri)
    # Daily maintenance halt: 17:00 - 18:00 ET
    if time_val >= globex_close_val and time_val < globex_open_val:
        next_open = now.replace(hour=globex_open_h, minute=globex_open_m, second=0)
        return MarketStateInfo(
            symbol=symbol,
            session=MarketSession.CLOSED,
            is_open=False,
            current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
            rth_open=rth_open_str,
            rth_close=rth_close_str,
            globex_open=globex_open_str,
            globex_close=globex_close_str,
            next_session_change=next_open.strftime("%Y-%m-%d %H:%M ET") + " (Globex opens)",
        )

    # RTH session
    if rth_open_val <= time_val < rth_close_val:
        next_change = now.replace(hour=rth_close_h, minute=rth_close_m, second=0)
        return MarketStateInfo(
            symbol=symbol,
            session=MarketSession.RTH,
            is_open=True,
            current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
            rth_open=rth_open_str,
            rth_close=rth_close_str,
            globex_open=globex_open_str,
            globex_close=globex_close_str,
            next_session_change=next_change.strftime("%Y-%m-%d %H:%M ET") + " (RTH closes)",
        )

    # Globex session (before RTH or after RTH but before maintenance)
    if time_val < rth_open_val:
        next_change = now.replace(hour=rth_open_h, minute=rth_open_m, second=0)
        label = " (RTH opens)"
    else:
        # After RTH close, before globex close
        next_change = now.replace(hour=globex_close_h, minute=globex_close_m, second=0)
        label = " (daily maintenance)"

    return MarketStateInfo(
        symbol=symbol,
        session=MarketSession.GLOBEX,
        is_open=True,
        current_time=now.strftime("%Y-%m-%d %H:%M:%S ET"),
        rth_open=rth_open_str,
        rth_close=rth_close_str,
        globex_open=globex_open_str,
        globex_close=globex_close_str,
        next_session_change=next_change.strftime("%Y-%m-%d %H:%M ET") + label,
    )


def _next_weekday(dt: datetime, target_weekday: int) -> datetime:
    """Get the next occurrence of a given weekday (0=Mon, 6=Sun)."""
    days_ahead = target_weekday - dt.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return dt + timedelta(days=days_ahead)
