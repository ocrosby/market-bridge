"""Tests for data models."""

from market_bridge.models import (
    Bar,
    DeltaBar,
    Heatmap,
    HeatmapLevel,
    Levels,
    MarketSession,
    MarketStateInfo,
    VolumeNode,
    VolumeProfile,
)


def test_bar_to_dict():
    bar = Bar(timestamp="2026-04-18T10:00:00", open=5400.0, high=5410.0, low=5395.0, close=5405.0, volume=12345)
    d = bar.to_dict()
    assert d["open"] == 5400.0
    assert d["volume"] == 12345
    assert d["timestamp"] == "2026-04-18T10:00:00"


def test_delta_bar_to_dict():
    delta = DeltaBar(timestamp="2026-04-18T10:00:00", buy_volume=7000, sell_volume=5000, delta=2000, cumulative_delta=2000)
    d = delta.to_dict()
    assert d["delta"] == 2000
    assert d["cumulative_delta"] == 2000


def test_volume_profile_to_dict():
    profile = VolumeProfile(
        symbol="/ES", session="rth", lookback_days=1,
        poc=5400.0, vah=5410.0, val=5390.0,
        nodes=[VolumeNode(price=5400.0, volume=50000)],
    )
    d = profile.to_dict()
    assert d["poc"] == 5400.0
    assert len(d["nodes"]) == 1


def test_levels_to_dict():
    levels = Levels(
        symbol="/ES", session="rth",
        poc=5400.0, vah=5410.0, val=5390.0,
        session_high=5420.0, session_low=5380.0,
        high_volume_nodes=[5400.0, 5405.0],
        low_volume_nodes=[5415.0],
    )
    d = levels.to_dict()
    assert d["session_high"] == 5420.0
    assert len(d["high_volume_nodes"]) == 2


def test_heatmap_to_dict():
    heatmap = Heatmap(
        symbol="/ES",
        bids=[HeatmapLevel(price=5400.0, size=500)],
        asks=[HeatmapLevel(price=5401.0, size=300)],
    )
    d = heatmap.to_dict()
    assert len(d["bids"]) == 1
    assert d["asks"][0]["size"] == 300


def test_market_state_info_to_dict():
    state = MarketStateInfo(
        symbol="/ES",
        session=MarketSession.RTH,
        is_open=True,
        current_time="2026-04-18 10:30:00 ET",
    )
    d = state.to_dict()
    assert d["session"] == "rth"
    assert d["is_open"] is True
