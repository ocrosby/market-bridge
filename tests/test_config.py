"""Tests for configuration."""

from pathlib import Path

from market_bridge.config import (
    BookmapSettings,
    CacheSettings,
    ThinkorswimSettings,
    TradovateSettings,
)


def test_tradovate_not_configured_by_default():
    settings = TradovateSettings()
    assert not settings.is_configured


def test_tradovate_configured_with_credentials():
    settings = TradovateSettings(
        username="user", password="pass", app_id="app", sec="secret"
    )
    assert settings.is_configured


def test_tradovate_demo_url():
    settings = TradovateSettings(demo=True)
    assert "demo" in settings.base_url


def test_tradovate_live_url():
    settings = TradovateSettings(demo=False)
    assert "live" in settings.base_url


def test_tradovate_demo_md_url():
    settings = TradovateSettings(demo=True)
    assert "md-demo" in settings.md_url


def test_tradovate_live_md_url():
    settings = TradovateSettings(demo=False)
    assert "md-demo" not in settings.md_url
    assert "md.tradovateapi.com" in settings.md_url


def test_bookmap_not_configured_nonexistent_dir():
    settings = BookmapSettings(export_dir=Path("/nonexistent"))
    assert not settings.is_configured


def test_bookmap_configured_existing_dir(tmp_path):
    settings = BookmapSettings(export_dir=tmp_path)
    assert settings.is_configured


def test_tos_not_configured_nonexistent_dir():
    settings = ThinkorswimSettings(export_dir=Path("/nonexistent"))
    assert not settings.is_configured


def test_tos_configured_existing_dir(tmp_path):
    settings = ThinkorswimSettings(export_dir=tmp_path)
    assert settings.is_configured


def test_cache_defaults():
    settings = CacheSettings()
    assert settings.default_ttl == 30
    assert settings.max_entries == 500
