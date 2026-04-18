"""Tests for market state session logic."""

from datetime import datetime
from unittest.mock import patch

import pytz

from market_bridge.models import MarketSession
from market_bridge.tools.market_state import compute_market_state


def _mock_now(year, month, day, hour, minute, weekday_check=None):
    """Create a mock datetime in US/Eastern."""
    et = pytz.timezone("US/Eastern")
    dt = et.localize(datetime(year, month, day, hour, minute, 0))
    return dt


def _compute_at(hour, minute, weekday_offset=0):
    """Helper: compute /ES market state at a given ET time on a specific weekday.

    weekday_offset: 0=Monday(2026-04-13), 4=Friday(2026-04-17), 5=Saturday, 6=Sunday
    """
    # 2026-04-13 is a Monday
    day = 13 + weekday_offset
    et = pytz.timezone("US/Eastern")
    mock_dt = et.localize(datetime(2026, 4, day, hour, minute, 0))

    with patch("market_bridge.tools.market_state.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        return compute_market_state("/ES")


def test_rth_session():
    state = _compute_at(10, 30)  # Monday 10:30 ET
    assert state.session == MarketSession.RTH
    assert state.is_open is True


def test_rth_open_boundary():
    state = _compute_at(9, 30)  # Exactly at RTH open
    assert state.session == MarketSession.RTH
    assert state.is_open is True


def test_globex_before_rth():
    state = _compute_at(8, 0)  # Monday 8:00 ET (before RTH)
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True


def test_globex_after_rth():
    state = _compute_at(16, 30)  # Monday 4:30 PM ET (after RTH)
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True


def test_daily_maintenance_halt():
    state = _compute_at(17, 30)  # Monday 5:30 PM ET (maintenance)
    assert state.session == MarketSession.CLOSED
    assert state.is_open is False


def test_globex_evening_open():
    state = _compute_at(18, 30)  # Monday 6:30 PM ET
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True


def test_saturday_closed():
    state = _compute_at(12, 0, weekday_offset=5)  # Saturday noon
    assert state.session == MarketSession.CLOSED
    assert state.is_open is False


def test_sunday_before_open():
    state = _compute_at(15, 0, weekday_offset=6)  # Sunday 3 PM
    assert state.session == MarketSession.CLOSED
    assert state.is_open is False


def test_sunday_after_open():
    state = _compute_at(19, 0, weekday_offset=6)  # Sunday 7 PM
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True


def test_friday_before_close():
    state = _compute_at(16, 30, weekday_offset=4)  # Friday 4:30 PM
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True


def test_friday_after_close():
    state = _compute_at(17, 30, weekday_offset=4)  # Friday 5:30 PM
    assert state.session == MarketSession.CLOSED
    assert state.is_open is False


def test_unknown_symbol():
    et = pytz.timezone("US/Eastern")
    mock_dt = et.localize(datetime(2026, 4, 13, 10, 0, 0))
    with patch("market_bridge.tools.market_state.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        state = compute_market_state("/UNKNOWN")
    assert state.session == MarketSession.CLOSED
    assert state.is_open is False


def test_next_session_change_present():
    state = _compute_at(10, 30)  # During RTH
    assert state.next_session_change is not None
    assert "RTH closes" in state.next_session_change


def test_exactly_at_maintenance_start():
    state = _compute_at(17, 0)  # Exactly at 17:00 ET (maintenance starts)
    assert state.session == MarketSession.CLOSED
    assert state.is_open is False


def test_exactly_at_globex_reopen():
    state = _compute_at(18, 0)  # Exactly at 18:00 ET (globex reopens)
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True


def test_cl_rth_session():
    """Crude oil has different RTH hours: 9:00-14:30 ET."""
    et = pytz.timezone("US/Eastern")
    mock_dt = et.localize(datetime(2026, 4, 13, 10, 0, 0))  # Monday 10:00 ET
    with patch("market_bridge.tools.market_state.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        state = compute_market_state("/CL")
    assert state.session == MarketSession.RTH
    assert state.is_open is True


def test_cl_after_rth_close():
    """/CL RTH closes at 14:30 ET — should be globex after that."""
    et = pytz.timezone("US/Eastern")
    mock_dt = et.localize(datetime(2026, 4, 13, 15, 0, 0))  # Monday 3:00 PM ET
    with patch("market_bridge.tools.market_state.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        state = compute_market_state("/CL")
    assert state.session == MarketSession.GLOBEX
    assert state.is_open is True
