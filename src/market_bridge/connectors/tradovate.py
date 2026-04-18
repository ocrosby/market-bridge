"""Tradovate REST + WebSocket API connector.

Handles OAuth2 authentication, token renewal, and market data retrieval
via both REST and WebSocket APIs.

Reference: https://api.tradovate.com/
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from market_bridge.config import TradovateSettings
from market_bridge.models import FUTURES_SESSIONS, Bar, DeltaBar, HeatmapLevel, Levels, VolumeNode

logger = logging.getLogger(__name__)

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
        # Tokens last ~80 minutes; refresh at 70 minutes
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

    async def connect_market_data(self) -> None:
        """Connect to the Tradovate market data WebSocket."""
        await self._ensure_authenticated()
        await self._ws_connect()

    async def _ws_connect(self) -> None:
        try:
            self._ws = await websockets.connect(self.settings.md_url)
            # Authorize the WebSocket connection
            await self._ws.send(f"authorize\n{self._next_id()}\n\n{self.access_token}")
            auth_response = await self._ws.recv()
            logger.info("Market data WebSocket connected: %s", str(auth_response)[:100])
            self._reconnect_attempts = 0
            self._ws_listener_task = asyncio.create_task(self._ws_listen())
        except Exception as e:
            logger.error("WebSocket connection failed: %s", e)
            raise TradovateError(f"WebSocket connection failed: {e}") from e

    async def _ws_listen(self) -> None:
        try:
            async for message in self._ws:
                self._handle_ws_message(str(message))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            await self._ws_reconnect()

    def _handle_ws_message(self, message: str) -> None:
        # Tradovate WebSocket responses are formatted as:
        # a[<id>]\n<status>\n<body_json>
        # or for subscriptions: d{"charts": [...]}
        if not message:
            return

        # Handle heartbeat
        if message.startswith("h"):
            return

        # Handle framed responses (a = response to a request)
        if message.startswith("a"):
            try:
                lines = message.split("\n", 2)
                if len(lines) >= 1:
                    req_id_str = lines[0][1:].strip("[]")
                    if req_id_str.isdigit():
                        req_id = int(req_id_str)
                        body = lines[2] if len(lines) > 2 else "{}"
                        future = self._ws_responses.get(req_id)
                        if future and not future.done():
                            future.set_result(json.loads(body) if body.strip() else {})
            except (ValueError, json.JSONDecodeError) as e:
                logger.debug("Could not parse WebSocket message: %s", e)

    async def _ws_reconnect(self) -> None:
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Max WebSocket reconnect attempts reached")
            return

        self._reconnect_attempts += 1
        delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))
        logger.info("Reconnecting WebSocket in %.1fs (attempt %d)", delay, self._reconnect_attempts)
        await asyncio.sleep(delay)

        try:
            await self._ensure_authenticated()
            await self._ws_connect()
        except Exception as e:
            logger.error("Reconnection failed: %s", e)
            await self._ws_reconnect()

    def _next_id(self) -> int:
        self._ws_counter += 1
        return self._ws_counter

    async def _ws_request(self, url: str, body: dict, timeout: float = 10.0) -> dict:
        if not self._ws:
            await self.connect_market_data()

        req_id = self._next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
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

    # ── Data fetching (REST-based fallback) ──────────────────────────────

    async def get_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        """Fetch historical OHLCV bars for a symbol."""
        contract = await self.find_contract(symbol)
        contract_id = contract.get("id") or contract.get("contractId")

        chart_desc = TIMEFRAME_MAP.get(timeframe)
        if not chart_desc:
            raise TradovateError(f"Unsupported timeframe: {timeframe}")

        # Use REST endpoint for historical bars
        bars_data = await self._api_get(
            "/md/getChart",
            {
                "contractId": contract_id,
                "chartDescription": json.dumps({
                    "underlyingType": chart_desc["underlyingType"],
                    "elementSize": chart_desc["elementSize"],
                    "elementSizeUnit": chart_desc["elementSizeUnit"],
                    "withHistogram": False,
                }),
                "timeRange": json.dumps({"asFarAsTimestamp": _utc_now_iso(), "closestTickCount": count}),
            },
        )

        bars = []
        raw_bars = bars_data.get("bars", bars_data) if isinstance(bars_data, dict) else bars_data
        if isinstance(raw_bars, list):
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
        """Fetch current depth of market (DOM) for a symbol."""
        contract = await self.find_contract(symbol)
        contract_id = contract.get("id") or contract.get("contractId")

        dom_data = await self._api_get(f"/md/dom", {"contractId": contract_id})
        bids = []
        asks = []
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
        """Fetch the latest quote for a symbol."""
        contract = await self.find_contract(symbol)
        contract_id = contract.get("id") or contract.get("contractId")
        return await self._api_get(f"/md/quote", {"contractId": contract_id})

    # ── Derived data ─────────────────────────────────────────────────────

    async def compute_levels(self, symbol: str, session: str) -> Levels:
        """Compute session levels from historical bar data."""
        # Fetch enough bars to cover the session
        bars = await self.get_bars(symbol, "5m", 200)
        if not bars:
            return Levels(symbol=symbol, session=session)

        # Filter bars by session time window
        session_bars = _filter_bars_by_session(bars, symbol, session)

        if not session_bars:
            session_bars = bars  # fall back to all bars if filter empties the list

        highs = [b.high for b in session_bars]
        lows = [b.low for b in session_bars]

        session_high = max(highs) if highs else None
        session_low = min(lows) if lows else None

        # Compute volume profile from bars
        vpoc, vah, val, hvns, lvns = _compute_volume_profile(session_bars)

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
        """Compute order flow delta from tick/bar data.

        Note: True tick-level delta requires tick data streaming.
        This approximation uses bar data with up/down volume estimation.
        """
        bars = await self.get_bars(symbol, timeframe, count)
        deltas = []
        cumulative = 0
        for bar in bars:
            # Approximate: if close > open, more buying; if close < open, more selling
            if bar.close >= bar.open:
                buy_pct = 0.5 + 0.5 * min((bar.close - bar.open) / max(bar.high - bar.low, 0.01), 1.0)
            else:
                buy_pct = 0.5 - 0.5 * min((bar.open - bar.close) / max(bar.high - bar.low, 0.01), 1.0)

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
        # Use small timeframe bars for better resolution
        bars_needed = lookback_days * 78 * 5  # ~78 5-min bars per RTH session, 5 for safety
        bars = await self.get_bars(symbol, "5m", min(bars_needed, 500))
        if not bars:
            return [], None, None, None

        vpoc, vah, val, _, _ = _compute_volume_profile(bars)

        # Build node list
        price_vol: dict[float, int] = {}
        tick = _tick_size(symbol)
        for bar in bars:
            rounded = round(round(bar.close / tick) * tick, 2)
            price_vol[rounded] = price_vol.get(rounded, 0) + bar.volume

        nodes = [VolumeNode(price=p, volume=v) for p, v in sorted(price_vol.items())]
        return nodes, vpoc, vah, val

    async def close(self) -> None:
        if self._ws_listener_task:
            self._ws_listener_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._http:
            await self._http.aclose()


# ── Helpers ──────────────────────────────────────────────────────────────


def _compute_volume_profile(
    bars: list[Bar],
) -> tuple[float | None, float | None, float | None, list[float], list[float]]:
    """Compute POC, VAH, VAL, HVNs, and LVNs from bar data."""
    if not bars:
        return None, None, None, [], []

    # Build price -> volume map using close prices binned to tick size
    tick = 0.25  # default for /ES
    price_vol: dict[float, int] = {}
    total_vol = 0

    for bar in bars:
        price = round(round(bar.close / tick) * tick, 2)
        price_vol[price] = price_vol.get(price, 0) + bar.volume
        total_vol += bar.volume

    if not price_vol:
        return None, None, None, [], []

    # POC: price with highest volume
    poc = max(price_vol, key=price_vol.get)

    # Value Area: 70% of volume centered on POC
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
        else:
            lo_idx -= 1
            va_vol += price_vol[sorted_prices[lo_idx]]

    val = sorted_prices[lo_idx]
    vah = sorted_prices[hi_idx]

    # HVN/LVN: prices with volume > 1.5x or < 0.5x average
    avg_vol = total_vol / len(price_vol)
    hvns = [p for p, v in price_vol.items() if v > avg_vol * 1.5]
    lvns = [p for p, v in price_vol.items() if v < avg_vol * 0.5]

    return poc, vah, val, sorted(hvns), sorted(lvns)


def _tick_size(symbol: str) -> float:
    """Get tick size for a futures symbol."""
    tick_sizes = {
        "/ES": 0.25, "/NQ": 0.25, "/YM": 1.0, "/RTY": 0.10,
        "/CL": 0.01, "/GC": 0.10, "/SI": 0.005,
        "/ZB": 1 / 32, "/ZN": 1 / 64, "/ZF": 1 / 128,
        "/6E": 0.00005, "/6J": 0.0000005,
    }
    return tick_sizes.get(symbol, 0.25)


def _filter_bars_by_session(
    bars: list[Bar], symbol: str, session: str
) -> list[Bar]:
    """Filter bars to only include those within the requested session window.

    Args:
        bars: List of bars with ISO timestamp strings.
        symbol: Futures symbol (e.g. /ES) used to look up session times.
        session: One of "rth", "globex", or "full".
    """
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
            filtered.append(bar)  # keep bars we can't parse
            continue

        in_rth = rth_open_minutes <= bar_minutes < rth_close_minutes

        if session == "rth" and in_rth:
            filtered.append(bar)
        elif session == "globex" and not in_rth:
            filtered.append(bar)

    return filtered


def _bar_time_of_day_et(timestamp: str) -> int | None:
    """Extract time-of-day in minutes (ET) from an ISO timestamp string.

    Returns None if the timestamp can't be parsed.
    """
    try:
        # Tradovate timestamps are typically UTC ISO format
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        # Convert UTC to ET (approximate: -4 for EDT, -5 for EST)
        # Use -4 as EDT covers most trading days
        et_hour = (dt.hour - 4) % 24
        return et_hour * 60 + dt.minute
    except (ValueError, AttributeError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
