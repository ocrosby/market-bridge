"""Tests for Tradovate connector with mocked methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_bridge.config import TradovateSettings
from market_bridge.connectors.tradovate import (
    TradovateConnector,
    TradovateError,
    _bar_time_of_day_et,
    _compute_volume_profile,
    _filter_bars_by_session,
    _tick_size,
)
from market_bridge.models import Bar

DEMO_URL = "https://demo.tradovateapi.com/v1"


def _configured_settings() -> TradovateSettings:
    return TradovateSettings(
        username="testuser",
        password="testpass",
        app_id="testapp",
        app_version="1.0",
        cid=1,
        sec="testsecret",
        demo=True,
    )


def _authed_connector() -> TradovateConnector:
    """Create a connector pre-authenticated so tests skip real HTTP calls."""
    connector = TradovateConnector(_configured_settings())
    connector.access_token = "tok_test"
    connector.token_expiry = float("inf")
    return connector


def _sample_bars_raw() -> list[dict]:
    return [
        {"timestamp": "2026-04-18T14:00:00Z", "open": 5400, "high": 5410, "low": 5395, "close": 5405, "volume": 1000},
        {"timestamp": "2026-04-18T14:05:00Z", "open": 5405, "high": 5420, "low": 5400, "close": 5415, "volume": 1500},
    ]


# ── Authentication ───────────────────────────────────────────────────────


class TestAuthentication:
    async def test_not_configured_raises(self):
        connector = TradovateConnector(TradovateSettings())
        with pytest.raises(TradovateError, match="not configured"):
            await connector.authenticate()

    def test_is_configured(self):
        assert TradovateConnector(_configured_settings()).is_configured is True
        assert TradovateConnector(TradovateSettings()).is_configured is False

    def test_base_url_demo(self):
        s = TradovateSettings(demo=True)
        assert "demo" in TradovateConnector(s).base_url

    def test_base_url_live(self):
        s = TradovateSettings(demo=False)
        assert "live" in TradovateConnector(s).base_url

    async def test_authenticate_sets_token(self):
        connector = _authed_connector()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"accessToken": "tok_new"}
        mock_resp.text = ""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        connector._http = mock_client
        connector.access_token = None  # force re-auth
        connector.token_expiry = 0

        await connector.authenticate()
        assert connector.access_token == "tok_new"

    async def test_authenticate_error_text_raises(self):
        connector = TradovateConnector(_configured_settings())
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errorText": "Bad password"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        connector._http = mock_client

        with pytest.raises(TradovateError, match="Bad password"):
            await connector.authenticate()

    async def test_authenticate_http_error_raises(self):
        connector = TradovateConnector(_configured_settings())
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        connector._http = mock_client

        with pytest.raises(TradovateError, match="Authentication failed"):
            await connector.authenticate()


# ── Contract resolution ──────────────────────────────────────────────────


class TestContractResolution:
    async def test_find_contract(self):
        connector = _authed_connector()
        connector._api_get = AsyncMock(return_value=[{"id": 42, "name": "ESM6"}])
        contract = await connector.find_contract("/ES")
        assert contract["id"] == 42

    async def test_find_contract_empty_raises(self):
        connector = _authed_connector()
        connector._api_get = AsyncMock(return_value=[])
        with pytest.raises(TradovateError, match="No contract found"):
            await connector.find_contract("/ES")

    async def test_find_contract_maps_symbol(self):
        connector = _authed_connector()
        connector._api_get = AsyncMock(return_value=[{"id": 1}])
        await connector.find_contract("/NQ")
        connector._api_get.assert_called_with("/contract/suggest", {"t": "NQ", "l": 1})


# ── Bar fetching ─────────────────────────────────────────────────────────


class TestGetBars:
    async def test_get_bars_parses_response(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        connector._api_get = AsyncMock(return_value={"bars": _sample_bars_raw()})

        bars = await connector.get_bars("/ES", "1h", 10)
        assert len(bars) == 2
        assert bars[0].open == 5400.0
        assert bars[1].volume == 1500

    async def test_get_bars_unsupported_timeframe(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        with pytest.raises(TradovateError, match="Unsupported timeframe"):
            await connector.get_bars("/ES", "2h", 10)

    async def test_get_bars_limits_count(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        many_bars = [
            {"timestamp": f"t{i}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
            for i in range(20)
        ]
        connector._api_get = AsyncMock(return_value={"bars": many_bars})
        bars = await connector.get_bars("/ES", "5m", 5)
        assert len(bars) == 5

    async def test_get_bars_empty_response(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        connector._api_get = AsyncMock(return_value={"bars": []})
        bars = await connector.get_bars("/ES", "1h", 10)
        assert bars == []


# ── DOM ──────────────────────────────────────────────────────────────────


class TestGetDom:
    async def test_dom_with_offers_key(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        connector._api_get = AsyncMock(return_value={
            "bids": [{"price": 5400.0, "size": 500}],
            "offers": [{"price": 5401.0, "size": 300}],
        })
        dom = await connector.get_dom("/ES", depth=5)
        assert len(dom["bids"]) == 1
        assert len(dom["asks"]) == 1
        assert dom["asks"][0].price == 5401.0

    async def test_dom_with_asks_key(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        connector._api_get = AsyncMock(return_value={
            "bids": [{"price": 5400.0, "size": 500}],
            "asks": [{"price": 5401.0, "size": 300}],
        })
        dom = await connector.get_dom("/ES", depth=5)
        assert len(dom["asks"]) == 1

    async def test_dom_empty_response(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        connector._api_get = AsyncMock(return_value={})
        dom = await connector.get_dom("/ES", depth=5)
        assert dom["bids"] == []
        assert dom["asks"] == []

    async def test_dom_neither_offers_nor_asks(self):
        connector = _authed_connector()
        connector.find_contract = AsyncMock(return_value={"id": 42})
        connector._api_get = AsyncMock(return_value={
            "bids": [{"price": 5400, "size": 100}],
        })
        dom = await connector.get_dom("/ES", depth=5)
        assert dom["asks"] == []


# ── Order flow ───────────────────────────────────────────────────────────


class TestOrderFlow:
    async def test_bullish_bar_positive_delta(self):
        connector = _authed_connector()
        connector.get_bars = AsyncMock(return_value=[
            Bar("t1", open=5400, high=5410, low=5395, close=5408, volume=10000),
        ])
        deltas = await connector.compute_order_flow("/ES", "5m", 1)
        assert len(deltas) == 1
        assert deltas[0].delta > 0  # close > open = bullish

    async def test_bearish_bar_negative_delta(self):
        connector = _authed_connector()
        connector.get_bars = AsyncMock(return_value=[
            Bar("t1", open=5408, high=5412, low=5395, close=5400, volume=10000),
        ])
        deltas = await connector.compute_order_flow("/ES", "5m", 1)
        assert deltas[0].delta < 0  # close < open = bearish

    async def test_cumulative_delta_sums(self):
        connector = _authed_connector()
        connector.get_bars = AsyncMock(return_value=[
            Bar("t1", open=5400, high=5410, low=5395, close=5408, volume=10000),
            Bar("t2", open=5408, high=5412, low=5395, close=5400, volume=8000),
        ])
        deltas = await connector.compute_order_flow("/ES", "5m", 2)
        assert deltas[1].cumulative_delta == deltas[0].delta + deltas[1].delta

    async def test_empty_bars(self):
        connector = _authed_connector()
        connector.get_bars = AsyncMock(return_value=[])
        deltas = await connector.compute_order_flow("/ES", "5m", 10)
        assert deltas == []


# ── Levels ───────────────────────────────────────────────────────────────


class TestComputeLevels:
    async def test_computes_session_high_low(self):
        connector = _authed_connector()
        connector.get_bars = AsyncMock(return_value=[
            Bar("2026-04-18T14:00:00Z", 5400, 5420, 5390, 5410, 5000),
            Bar("2026-04-18T14:05:00Z", 5410, 5430, 5405, 5425, 3000),
        ])
        levels = await connector.compute_levels("/ES", "full")
        assert levels.session_high == 5430
        assert levels.session_low == 5390

    async def test_computes_poc(self):
        connector = _authed_connector()
        bars = [
            Bar(f"2026-04-18T{14+i//12:02d}:{(i%12)*5:02d}:00Z",
                5400, 5401, 5399, 5400.0, 5000)
            for i in range(10)
        ] + [
            Bar("2026-04-18T15:00:00Z", 5401, 5402, 5400, 5400.25, 1000),
        ]
        connector.get_bars = AsyncMock(return_value=bars)
        levels = await connector.compute_levels("/ES", "full")
        assert levels.poc == 5400.0  # highest volume

    async def test_empty_bars(self):
        connector = _authed_connector()
        connector.get_bars = AsyncMock(return_value=[])
        levels = await connector.compute_levels("/ES", "rth")
        assert levels.poc is None


# ── Helper: tick sizes ───────────────────────────────────────────────────


class TestTickSize:
    def test_known_symbols(self):
        assert _tick_size("/ES") == 0.25
        assert _tick_size("/NQ") == 0.25
        assert _tick_size("/YM") == 1.0
        assert _tick_size("/CL") == 0.01
        assert _tick_size("/ZN") == 1 / 64
        assert _tick_size("/ZF") == 1 / 128
        assert _tick_size("/6E") == 0.00005
        assert _tick_size("/6J") == 0.0000005

    def test_unknown_defaults_to_025(self):
        assert _tick_size("/UNKNOWN") == 0.25


# ── Helper: bar time of day ──────────────────────────────────────────────


class TestBarTimeOfDayET:
    def test_utc_timestamp(self):
        # 14:30 UTC = 10:30 ET (EDT, -4)
        assert _bar_time_of_day_et("2026-04-18T14:30:00Z") == 10 * 60 + 30

    def test_midnight_utc(self):
        # 00:00 UTC = 20:00 ET previous day
        assert _bar_time_of_day_et("2026-04-18T00:00:00Z") == 20 * 60

    def test_invalid_returns_none(self):
        assert _bar_time_of_day_et("not-a-date") is None
        assert _bar_time_of_day_et("") is None


# ── Helper: session filtering ────────────────────────────────────────────


class TestFilterBarsBySession:
    def _bars(self, timestamps: list[str]) -> list[Bar]:
        return [Bar(ts, 5400, 5410, 5390, 5405, 1000) for ts in timestamps]

    def test_full_returns_all(self):
        bars = self._bars(["2026-04-18T14:00:00Z", "2026-04-18T22:00:00Z"])
        assert len(_filter_bars_by_session(bars, "/ES", "full")) == 2

    def test_rth_keeps_only_rth(self):
        bars = self._bars([
            "2026-04-18T13:00:00Z",  # 9:00 ET -> pre-RTH
            "2026-04-18T13:30:00Z",  # 9:30 ET -> RTH open
            "2026-04-18T15:00:00Z",  # 11:00 ET -> RTH
            "2026-04-18T20:00:00Z",  # 16:00 ET -> at close (excluded)
            "2026-04-18T21:00:00Z",  # 17:00 ET -> post-RTH
        ])
        assert len(_filter_bars_by_session(bars, "/ES", "rth")) == 2

    def test_globex_excludes_rth(self):
        bars = self._bars([
            "2026-04-18T13:00:00Z",  # 9:00 ET -> globex
            "2026-04-18T14:00:00Z",  # 10:00 ET -> RTH
            "2026-04-18T21:00:00Z",  # 17:00 ET -> globex
        ])
        assert len(_filter_bars_by_session(bars, "/ES", "globex")) == 2

    def test_unknown_symbol_returns_all(self):
        bars = self._bars(["2026-04-18T14:00:00Z"])
        assert len(_filter_bars_by_session(bars, "/ZZ", "rth")) == 1


# ── Helper: volume profile computation ───────────────────────────────────


class TestComputeVolumeProfile:
    def test_poc_is_highest_volume(self):
        bars = [
            Bar("t1", 5400, 5401, 5399, 5400.0, 5000),
            Bar("t2", 5400, 5401, 5399, 5400.0, 5000),
            Bar("t3", 5400, 5401, 5399, 5400.25, 3000),
            Bar("t4", 5400, 5401, 5399, 5400.50, 1000),
        ]
        poc, vah, val, hvns, lvns = _compute_volume_profile(bars)
        assert poc == 5400.0
        assert vah is not None
        assert val is not None
        assert vah >= poc >= val

    def test_empty_bars_returns_nones(self):
        poc, vah, val, hvns, lvns = _compute_volume_profile([])
        assert poc is None
        assert hvns == []
        assert lvns == []
