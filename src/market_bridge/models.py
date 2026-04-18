"""Shared data models used across connectors and tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SessionType(str, Enum):
    RTH = "rth"
    GLOBEX = "globex"
    FULL = "full"


class MarketSession(str, Enum):
    PRE_MARKET = "pre_market"
    RTH = "rth"
    POST_MARKET = "post_market"
    GLOBEX = "globex"
    CLOSED = "closed"


@dataclass
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class VolumeNode:
    price: float
    volume: int

    def to_dict(self) -> dict:
        return {"price": self.price, "volume": self.volume}


@dataclass
class VolumeProfile:
    symbol: str
    session: str
    lookback_days: int
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    nodes: list[VolumeNode] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "session": self.session,
            "lookback_days": self.lookback_days,
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "nodes": [n.to_dict() for n in self.nodes],
        }


@dataclass
class DeltaBar:
    timestamp: str
    buy_volume: int
    sell_volume: int
    delta: int
    cumulative_delta: int

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "delta": self.delta,
            "cumulative_delta": self.cumulative_delta,
        }


@dataclass
class Levels:
    symbol: str
    session: str
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    session_high: float | None = None
    session_low: float | None = None
    high_volume_nodes: list[float] = field(default_factory=list)
    low_volume_nodes: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "session": self.session,
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "session_high": self.session_high,
            "session_low": self.session_low,
            "high_volume_nodes": self.high_volume_nodes,
            "low_volume_nodes": self.low_volume_nodes,
        }


@dataclass
class HeatmapLevel:
    price: float
    size: int

    def to_dict(self) -> dict:
        return {"price": self.price, "size": self.size}


@dataclass
class Heatmap:
    symbol: str
    bids: list[HeatmapLevel] = field(default_factory=list)
    asks: list[HeatmapLevel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "bids": [b.to_dict() for b in self.bids],
            "asks": [a.to_dict() for a in self.asks],
        }


@dataclass
class MarketStateInfo:
    symbol: str
    session: MarketSession
    is_open: bool
    current_time: str
    rth_open: str = "09:30 ET"
    rth_close: str = "16:00 ET"
    globex_open: str = "18:00 ET"
    globex_close: str = "17:00 ET"
    next_session_change: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "session": self.session.value,
            "is_open": self.is_open,
            "current_time": self.current_time,
            "rth_open": self.rth_open,
            "rth_close": self.rth_close,
            "globex_open": self.globex_open,
            "globex_close": self.globex_close,
            "next_session_change": self.next_session_change,
        }


# Futures contract specifications for session times
FUTURES_SESSIONS: dict[str, dict] = {
    "/ES": {
        "name": "E-mini S&P 500",
        "exchange": "CME",
        "rth_open": (9, 30),   # 9:30 AM ET
        "rth_close": (16, 0),  # 4:00 PM ET
        "globex_open": (18, 0),  # 6:00 PM ET (previous day)
        "globex_close": (17, 0),  # 5:00 PM ET
        "weekend_close": "Friday 17:00 ET",
        "weekend_open": "Sunday 18:00 ET",
    },
    "/NQ": {
        "name": "E-mini Nasdaq 100",
        "exchange": "CME",
        "rth_open": (9, 30),
        "rth_close": (16, 0),
        "globex_open": (18, 0),
        "globex_close": (17, 0),
        "weekend_close": "Friday 17:00 ET",
        "weekend_open": "Sunday 18:00 ET",
    },
    "/YM": {
        "name": "E-mini Dow",
        "exchange": "CBOT",
        "rth_open": (9, 30),
        "rth_close": (16, 0),
        "globex_open": (18, 0),
        "globex_close": (17, 0),
        "weekend_close": "Friday 17:00 ET",
        "weekend_open": "Sunday 18:00 ET",
    },
    "/RTY": {
        "name": "E-mini Russell 2000",
        "exchange": "CME",
        "rth_open": (9, 30),
        "rth_close": (16, 0),
        "globex_open": (18, 0),
        "globex_close": (17, 0),
        "weekend_close": "Friday 17:00 ET",
        "weekend_open": "Sunday 18:00 ET",
    },
    "/CL": {
        "name": "Crude Oil",
        "exchange": "NYMEX",
        "rth_open": (9, 0),
        "rth_close": (14, 30),
        "globex_open": (18, 0),
        "globex_close": (17, 0),
        "weekend_close": "Friday 17:00 ET",
        "weekend_open": "Sunday 18:00 ET",
    },
    "/GC": {
        "name": "Gold",
        "exchange": "COMEX",
        "rth_open": (8, 20),
        "rth_close": (13, 30),
        "globex_open": (18, 0),
        "globex_close": (17, 0),
        "weekend_close": "Friday 17:00 ET",
        "weekend_open": "Sunday 18:00 ET",
    },
}
