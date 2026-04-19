"""Tradovate REST + WebSocket API connector.

Handles OAuth2 authentication, token renewal, and market data retrieval.

- REST API: authentication, contract resolution, account data
- WebSocket API: market data (charts, DOM, quotes)

Reference: https://api.tradovate.com/
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
import pytz
import websockets
from websockets.asyncio.client import ClientConnection

from market_bridge.config import TradovateSettings
from market_bridge.models import (
    FUTURES_SESSIONS,
    Bar,
    DeltaBar,
    HeatmapLevel,
    Levels,
    VolumeNode,
    tick_size,
)

logger = logging.getLogger(__name__)

_ET = pytz.timezone("US/Eastern")

# Map user-friendly timeframes to Tradovate chart descriptions
TIMEFRAME_MAP: dict[str, dict] = {
    "1m": {"underlyingType": "MinuteBar", "elementSize": 1, "elementSizeUnit": "UnderlyingUnits"},
    "5m": {"underlyingType": "MinuteBar", "elementSize": 5, "elementSizeUnit": "UnderlyingUnits"},
    "15m": {"underlyingType": "MinuteBar", "elementSize": 15, "elementSizeUnit": "UnderlyingUnits"},
    "30m": {"underlyingType": "MinuteBar", "elementSize": 30, "elementSizeUnit": "UnderlyingUnits"},
    "1h": {"underlyingType": "MinuteBar", "elementSize": 60, "elementSizeUnit": "UnderlyingUnits"},
    "4h": {"underlyingType": "MinuteBar", "elementSize": 240, "elementSizeUnit": "UnderlyingUnits"},
    "1d": {"underlyingType": "DailyBar", "elementSize": 1, "elementSizeUnit": "UnderlyingUnits"},
}

# Front-month contract symbol mapping (slash prefix -> Tradovate product name)
PRODUCT_MAP: dict[str, str] = {
    "/ES": "ES",
    "/NQ": "NQ",
    "/YM": "YM",
    "/RTY": "RTY",
    "/CL": "CL",
    "/GC": "GC",
    "/SI": "SI",
    "/ZB": "ZB",
    "/ZN": "ZN",
    "/ZF": "ZF",
    "/6E": "6E",
    "/6J": "6J",
}


class TradovateError(Exception):
    pass


class TradovateConnector:
    def __init__(self, settings: TradovateSettings) -> None:
        self.settings = settings
        self.access_token: str | None = None
        self.token_expiry: float = 0
        self._http: httpx.AsyncClient | None = None
        self._ws: ClientConnection | None = None
        self._ws_counter: int = 0
        self._ws_responses: dict[int, asyncio.Future] = {}
        self._ws_listener_task: asyncio.Task | None = None
        self._ws_lock = asyncio.Lock()
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 5
        self._reconnect_delay: float = 1.0

    @property
    def is_configured(self) -> bool:
        return self.settings.is_configured

    @property
    def base_url(self) -> str:
        return self.settings.base_url

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def authenticate(self) -> None:
        """Authenticate with Tradovate and obtain an access token."""
        if not self.is_configured:
            raise TradovateError(
                "Tradovate credentials not configured. "
                "Set TRADOVATE_USERNAME, TRADOVATE_PASSWORD, TRADOVATE_APP_ID, "
                "and TRADOVATE_SEC environment variables."
            )

        http = await self._get_http()
        payload = {
            "name": self.settings.username,
            "password": self.settings.password,
            "appId": self.settings.app_id,
            "appVersion": self.settings.app_version,
            "cid": self.settings.cid,
            "sec": self.settings.sec,
        }

        resp = await http.post(f"{self.base_url}/auth/accesstokenrequest", json=payload)
        if resp.status_code != 200:
            raise TradovateError(f"Authentication failed: {resp.status_code} {resp.text}")

        data = resp.json()
        if "errorText" in data:
            raise TradovateError(f"Authentication error: {data['errorText']}")

        self.access_token = data["accessToken"]
        self.token_expiry = time.monotonic() + 70 * 60
        logger.info("Tradovate authentication successful")

    async def _ensure_authenticated(self) -> None:
        if self.access_token is None or time.monotonic() > self.token_expiry:
            await self.authenticate()

    async def _renew_token(self) -> None:
        http = await self._get_http()
        resp = await http.post(
            f"{self.base_url}/auth/renewaccesstoken",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("accessToken", self.access_token)
            self.token_expiry = time.monotonic() + 70 * 60
        else:
            logger.warning("Token renewal failed (HTTP %s), re-authenticating", resp.status_code)
            await self.authenticate()

    async def _api_get(self, path: str, params: dict | None = None) -> dict | list:
        await self._ensure_authenticated()
        http = await self._get_http()
        resp = await http.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        if resp.status_code != 200:
            raise TradovateError(f"API error {path}: {resp.status_code} {resp.text}")
        return resp.json()

    # ── Contract resolution ──────────────────────────────────────────────

    async def find_contract(self, symbol: str) -> dict:
        """Find the front-month contract for a given product symbol."""
        product = PRODUCT_MAP.get(symbol, symbol.lstrip("/"))
        contracts = await self._api_get("/contract/suggest", {"t": product, "l": 1})
        if not contracts:
            raise TradovateError(f"No contract found for {symbol}")
        return contracts[0] if isinstance(contracts, list) else contracts

    # ── WebSocket connection ─────────────────────────────────────────────

    async def _ensure_ws_connected(self) -> None:
        """Ensure a WebSocket connection exists, creating one if needed.

        Uses a lock to prevent concurrent callers from creating duplicate
        connections.
        """
        if self._ws is not None:
            return
        async with self._ws_lock:
            if self._ws is not None:
                return  # another coroutine connected while we waited
            await self._ensure_authenticated()
            await self._ws_connect()

    async def _ws_connect(self) -> None:
        ws = None
        try:
            ws = await websockets.connect(self.settings.md_url)
            await ws.send(f"authorize\n{self._next_id()}\n\n{self.access_token}")
            auth_response = await ws.recv()
            logger.info("Market data WebSocket connected: %s", str(auth_response)[:100])
            self._ws = ws
            self._reconnect_attempts = 0
            self._ws_listener_task = asyncio.create_task(self._ws_listen())
        except Exception as e:
            if ws is not None:
                await ws.close()
            logger.error("WebSocket connection failed: %s", e)
            raise TradovateError(f"WebSocket connection failed: {e}") from e

    async def _ws_listen(self) -> None:
        try:
            async for message in self._ws:
                self._handle_ws_message(str(message))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self._cancel_pending_futures("WebSocket connection lost")
            self._ws = None
            await self._ws_reconnect()

    def _handle_ws_message(self, message: str) -> None:
        """Parse Tradovate WebSocket frames.

        Tradovate sends frames in these formats:
          - Heartbeat: single character 'h' or empty
          - Response: 'a' followed by JSON array of response objects
            e.g. a[{"s":200,"i":1,"d":{...}}]
            where "i" is the request ID, "s" is status, "d" is data
          - Data push: 'd' followed by JSON object (chart data, etc.)
        """
        if not message:
            return

        if message.startswith("h"):
            return

        # Response frame: a[{...}]
        if message.startswith("a"):
            try:
                payload = json.loads(message[1:])
                if isinstance(payload, list):
                    for item in payload:
                        if not isinstance(item, dict):
                            continue
                        req_id = item.get("i")
                        if req_id is not None:
                            future = self._ws_responses.get(req_id)
                            if future and not future.done():
                                status = item.get("s", 200)
                                if status == 200:
                                    future.set_result(item.get("d", {}))
                                else:
                                    future.set_exception(
                                        TradovateError(f"WS request {req_id} failed: status {status}")
                                    )
            except (ValueError, json.JSONDecodeError) as e:
                logger.debug("Could not parse WebSocket response frame: %s", e)
            return

        # Data push frame: d{...} (chart updates, quote updates)
        if message.startswith("d"):
            try:
                payload = json.loads(message[1:])
                self._handle_data_push(payload)
            except (ValueError, json.JSONDecodeError) as e:
                logger.debug("Could not parse WebSocket data frame: %s", e)

    def _handle_data_push(self, data: dict) -> None:
        """Handle incoming data push from WebSocket (chart bars, quotes, etc.).

        Chart data pushes contain a "charts" key with bar arrays.
        We route these to any pending chart request future.
        """
        if "charts" in data:
            for chart in data["charts"]:
                req_id = chart.get("id")
                if req_id is not None:
                    future = self._ws_responses.get(req_id)
                    if future and not future.done():
                        future.set_result(chart)

    def _cancel_pending_futures(self, reason: str) -> None:
        """Cancel all pending WebSocket request futures on disconnect."""
        for req_id, future in list(self._ws_responses.items()):
            if not future.done():
                future.set_exception(TradovateError(reason))
        self._ws_responses.clear()

    async def _ws_reconnect(self) -> None:
        """Reconnect WebSocket with exponential backoff (iterative, bounded)."""
        async with self._ws_lock:
            while self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))
                logger.info("Reconnecting WebSocket in %.1fs (attempt %d/%d)",
                            delay, self._reconnect_attempts, self._max_reconnect_attempts)
                await asyncio.sleep(delay)

                try:
                    await self._ensure_authenticated()
                    await self._ws_connect()
                    return
                except Exception as e:
                    logger.error("Reconnection attempt %d failed: %s", self._reconnect_attempts, e)

            logger.error("Max WebSocket reconnect attempts (%d) reached, giving up",
                          self._max_reconnect_attempts)

    def _next_id(self) -> int:
        self._ws_counter += 1
        return self._ws_counter

    async def _ws_request(self, url: str, body: dict, timeout: float = 10.0) -> dict:
        """Send a request over the WebSocket and wait for the response."""
        await self._ensure_ws_connected()

        if self._ws is None:
            raise TradovateError("WebSocket is not connected")

        req_id = self._next_id()
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._ws_responses[req_id] = future

        msg = f"{url}\n{req_id}\n\n{json.dumps(body)}"
        await self._ws.send(msg)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            raise TradovateError(f"WebSocket request timed out: {url}")
        finally:
            self._ws_responses.pop(req_id, None)

    # ── Market data (via WebSocket) ──────────────────────────────────────

    async def get_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        """Fetch historical OHLCV bars for a symbol via WebSocket."""
        contract = await self.find_contract(symbol)
        contract_id = contract.get("id") or contract.get("contractId")

        chart_desc = TIMEFRAME_MAP.get(timeframe)
        if not chart_desc:
            raise TradovateError(f"Unsupported timeframe: {timeframe}")

        chart_request = {
            "symbol": contract_id,
            "chartDescription": {
                "underlyingType": chart_desc["underlyingType"],
                "elementSize": chart_desc["elementSize"],
                "elementSizeUnit": chart_desc["elementSizeUnit"],
                "withHistogram": False,
            },
            "timeRange": {
                "asFarAsTimestamp": _utc_now_iso(),
                "closestTickCount": count,
            },
        }

        chart_data = await self._ws_request("md/getchart", chart_request, timeout=15.0)

        bars = []
        raw_bars = chart_data.get("bars", []) if isinstance(chart_data, dict) else []
        if not isinstance(raw_bars, list):
            logger.warning("Unexpected bar data structure from Tradovate: %s", type(raw_bars).__name__)
            return []

        for b in raw_bars[-count:]:
            bars.append(Bar(
                timestamp=b.get("timestamp", ""),
                open=float(b.get("open", 0)),
                high=float(b.get("high", 0)),
                low=float(b.get("low", 0)),
                close=float(b.get("close", 0)),
                volume=int(b.get("volume", 0)),
            ))
        return bars

    async def get_dom(self, symbol: str, depth: int = 10) -> dict:
        """Fetch current depth of market (DOM) for a symbol via WebSocket."""
        contract = await self.find_contract(symbol)
        contract_id = contract.get("id") or contract.get("contractId")

        dom_data = await self._ws_request(
            "md/subscribeDOM", {"symbol": contract_id}, timeout=10.0
        )

        bids: list[HeatmapLevel] = []
        asks: list[HeatmapLevel] = []
        if isinstance(dom_data, dict):
            for entry in dom_data.get("bids", [])[:depth]:
                bids.append(HeatmapLevel(
                    price=float(entry.get("price", 0)),
                    size=int(entry.get("size", 0)),
                ))
            for entry in (dom_data.get("offers") or dom_data.get("asks") or [])[:depth]:
                asks.append(HeatmapLevel(
                    price=float(entry.get("price", 0)),
                    size=int(entry.get("size", 0)),
                ))
        return {"bids": bids, "asks": asks}

    async def get_quote(self, symbol: str) -> dict:
        """Fetch the latest quote for a symbol via WebSocket."""
        contract = await self.find_contract(symbol)
        contract_id = contract.get("id") or contract.get("contractId")
        return await self._ws_request(
            "md/subscribeQuote", {"symbol": contract_id}, timeout=10.0
        )

    # ── Derived data ─────────────────────────────────────────────────────

    async def compute_levels(self, symbol: str, session: str) -> Levels:
        """Compute session levels from historical bar data."""
        bars = await self.get_bars(symbol, "5m", 200)
        if not bars:
            return Levels(symbol=symbol, session=session)

        session_bars = _filter_bars_by_session(bars, symbol, session)

        if not session_bars:
            session_bars = bars

        highs = [b.high for b in session_bars]
        lows = [b.low for b in session_bars]

        session_high = max(highs) if highs else None
        session_low = min(lows) if lows else None

        vpoc, vah, val, hvns, lvns = _compute_volume_profile(session_bars, symbol)

        return Levels(
            symbol=symbol,
            session=session,
            poc=vpoc,
            vah=vah,
            val=val,
            session_high=session_high,
            session_low=session_low,
            high_volume_nodes=hvns,
            low_volume_nodes=lvns,
        )

    async def compute_order_flow(
        self, symbol: str, timeframe: str, count: int
    ) -> list[DeltaBar]:
        """Compute order flow delta from bar data.

        Note: True tick-level delta requires tick data streaming.
        This approximation uses bar data with up/down volume estimation.
        """
        bars = await self.get_bars(symbol, timeframe, count)
        deltas = []
        cumulative = 0
        min_range = tick_size(symbol)
        for bar in bars:
            bar_range = max(bar.high - bar.low, min_range)
            if bar.close >= bar.open:
                buy_pct = 0.5 + 0.5 * min((bar.close - bar.open) / bar_range, 1.0)
            else:
                buy_pct = 0.5 - 0.5 * min((bar.open - bar.close) / bar_range, 1.0)

            buy_vol = int(bar.volume * buy_pct)
            sell_vol = bar.volume - buy_vol
            delta = buy_vol - sell_vol
            cumulative += delta

            deltas.append(DeltaBar(
                timestamp=bar.timestamp,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                delta=delta,
                cumulative_delta=cumulative,
            ))
        return deltas

    async def compute_volume_profile(
        self, symbol: str, session: str, lookback_days: int
    ) -> tuple[list[VolumeNode], float | None, float | None, float | None]:
        """Compute volume profile from bar data."""
        bars_needed = lookback_days * 78 * 5
        bars = await self.get_bars(symbol, "5m", min(bars_needed, 500))
        if not bars:
            return [], None, None, None

        vpoc, vah, val, _, _ = _compute_volume_profile(bars, symbol)

        price_vol: dict[float, int] = {}
        tick = tick_size(symbol)
        for bar in bars:
            rounded = round(round(bar.close / tick) * tick, 2)
            price_vol[rounded] = price_vol.get(rounded, 0) + bar.volume

        nodes = [VolumeNode(price=p, volume=v) for p, v in sorted(price_vol.items())]
        return nodes, vpoc, vah, val

    async def close(self) -> None:
        if self._ws_listener_task:
            self._ws_listener_task.cancel()
        self._cancel_pending_futures("Connector closing")
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http:
            await self._http.aclose()


# ── Helpers ──────────────────────────────────────────────────────────────


def _compute_volume_profile(
    bars: list[Bar],
    symbol: str = "/ES",
) -> tuple[float | None, float | None, float | None, list[float], list[float]]:
    """Compute POC, VAH, VAL, HVNs, and LVNs from bar data."""
    if not bars:
        return None, None, None, [], []

    tick = tick_size(symbol)
    price_vol: dict[float, int] = {}
    total_vol = 0

    for bar in bars:
        price = round(round(bar.close / tick) * tick, 2)
        price_vol[price] = price_vol.get(price, 0) + bar.volume
        total_vol += bar.volume

    if not price_vol:
        return None, None, None, [], []

    poc = max(price_vol, key=price_vol.get)

    sorted_prices = sorted(price_vol.keys())
    poc_idx = sorted_prices.index(poc)
    va_target = total_vol * 0.70
    va_vol = price_vol[poc]
    lo_idx = poc_idx
    hi_idx = poc_idx

    while va_vol < va_target and (lo_idx > 0 or hi_idx < len(sorted_prices) - 1):
        vol_below = price_vol.get(sorted_prices[lo_idx - 1], 0) if lo_idx > 0 else 0
        vol_above = price_vol.get(sorted_prices[hi_idx + 1], 0) if hi_idx < len(sorted_prices) - 1 else 0

        if vol_below >= vol_above and lo_idx > 0:
            lo_idx -= 1
            va_vol += price_vol[sorted_prices[lo_idx]]
        elif hi_idx < len(sorted_prices) - 1:
            hi_idx += 1
            va_vol += price_vol[sorted_prices[hi_idx]]
        elif lo_idx > 0:
            lo_idx -= 1
            va_vol += price_vol[sorted_prices[lo_idx]]
        else:
            break

    val = sorted_prices[lo_idx]
    vah = sorted_prices[hi_idx]

    avg_vol = total_vol / len(price_vol)
    hvns = [p for p, v in price_vol.items() if v > avg_vol * 1.5]
    lvns = [p for p, v in price_vol.items() if v < avg_vol * 0.5]

    return poc, vah, val, sorted(hvns), sorted(lvns)


def _filter_bars_by_session(
    bars: list[Bar], symbol: str, session: str
) -> list[Bar]:
    """Filter bars to only include those within the requested session window."""
    if session == "full":
        return bars

    spec = FUTURES_SESSIONS.get(symbol)
    if not spec:
        return bars

    rth_open_minutes = spec["rth_open"][0] * 60 + spec["rth_open"][1]
    rth_close_minutes = spec["rth_close"][0] * 60 + spec["rth_close"][1]

    filtered = []
    for bar in bars:
        bar_minutes = _bar_time_of_day_et(bar.timestamp)
        if bar_minutes is None:
            filtered.append(bar)
            continue

        in_rth = rth_open_minutes <= bar_minutes < rth_close_minutes

        if session == "rth" and in_rth:
            filtered.append(bar)
        elif session == "globex" and not in_rth:
            filtered.append(bar)

    return filtered


def _bar_time_of_day_et(timestamp: str) -> int | None:
    """Extract time-of-day in minutes (ET) from an ISO timestamp string.

    Uses pytz for correct EDT/EST conversion year-round.
    Returns None if the timestamp can't be parsed.
    """
    try:
        dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(_ET)
        return dt_et.hour * 60 + dt_et.minute
    except (ValueError, AttributeError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
