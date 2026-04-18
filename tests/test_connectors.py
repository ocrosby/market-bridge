"""Tests for connector implementations."""

import csv
import tempfile
from pathlib import Path

from market_bridge.config import BookmapSettings, ThinkorswimSettings
from market_bridge.connectors.bookmap import BookmapConnector
from market_bridge.connectors.thinkorswim import ThinkorswimConnector


class TestBookmapConnector:
    def test_heatmap_no_export_dir(self):
        settings = BookmapSettings(export_dir=Path("/nonexistent"))
        connector = BookmapConnector(settings)
        heatmap = connector.get_heatmap("/ES", depth=5)
        assert heatmap.bids == []
        assert heatmap.asks == []

    def test_heatmap_from_csv(self, tmp_path):
        # Write a sample heatmap CSV
        csv_path = tmp_path / "ES_heatmap_20260418.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "price", "bid_size", "ask_size"])
            writer.writerow(["2026-04-18 10:00:00", "5400.00", "500", "0"])
            writer.writerow(["2026-04-18 10:00:00", "5399.75", "300", "0"])
            writer.writerow(["2026-04-18 10:00:00", "5400.25", "0", "400"])
            writer.writerow(["2026-04-18 10:00:00", "5400.50", "0", "200"])

        settings = BookmapSettings(export_dir=tmp_path)
        connector = BookmapConnector(settings)
        heatmap = connector.get_heatmap("/ES", depth=5)

        assert len(heatmap.bids) == 2
        assert len(heatmap.asks) == 2
        assert heatmap.bids[0].price == 5400.00  # highest bid first
        assert heatmap.asks[0].price == 5400.25  # lowest ask first

    def test_volume_profile_from_csv(self, tmp_path):
        csv_path = tmp_path / "ES_volume_profile.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["price", "volume"])
            writer.writerow(["5395.00", "10000"])
            writer.writerow(["5397.50", "15000"])
            writer.writerow(["5400.00", "50000"])  # POC
            writer.writerow(["5402.50", "20000"])
            writer.writerow(["5405.00", "8000"])

        settings = BookmapSettings(export_dir=tmp_path)
        connector = BookmapConnector(settings)
        profile = connector.get_volume_profile("/ES", "rth", 1)

        assert profile.poc == 5400.00
        assert profile.vah is not None
        assert profile.val is not None
        assert len(profile.nodes) == 5

    def test_volume_profile_no_files(self, tmp_path):
        settings = BookmapSettings(export_dir=tmp_path)
        connector = BookmapConnector(settings)
        profile = connector.get_volume_profile("/ES", "rth", 1)
        assert profile.nodes == []
        assert profile.poc is None


class TestThinkorswimConnector:
    def test_price_bars_no_export_dir(self):
        settings = ThinkorswimSettings(export_dir=Path("/nonexistent"))
        connector = ThinkorswimConnector(settings)
        bars = connector.get_price_bars("/ES", count=10)
        assert bars == []

    def test_price_bars_from_csv(self, tmp_path):
        csv_path = tmp_path / "ES_price.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
            writer.writerow(["2026-04-18 09:30", "5400.00", "5410.00", "5395.00", "5405.00", "12345"])
            writer.writerow(["2026-04-18 09:35", "5405.00", "5415.00", "5400.00", "5412.00", "10000"])
            writer.writerow(["2026-04-18 09:40", "5412.00", "5420.00", "5408.00", "5418.00", "8000"])

        settings = ThinkorswimSettings(export_dir=tmp_path)
        connector = ThinkorswimConnector(settings)
        bars = connector.get_price_bars("/ES", count=10)

        assert len(bars) == 3
        assert bars[0].open == 5400.00
        assert bars[0].volume == 12345
        assert bars[2].close == 5418.00

    def test_price_bars_count_limit(self, tmp_path):
        csv_path = tmp_path / "ES_price.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
            for i in range(20):
                minute = 30 + i % 30
                hour = 9 + (30 + i) // 60
                writer.writerow([f"2026-04-18 {hour:02d}:{minute:02d}", "5400", "5410", "5395", "5405", "1000"])

        settings = ThinkorswimSettings(export_dir=tmp_path)
        connector = ThinkorswimConnector(settings)
        bars = connector.get_price_bars("/ES", count=5)
        assert len(bars) == 5

    def test_price_bars_caching(self, tmp_path):
        csv_path = tmp_path / "ES_price.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
            writer.writerow(["2026-04-18 09:30", "5400", "5410", "5395", "5405", "1000"])

        settings = ThinkorswimSettings(export_dir=tmp_path)
        connector = ThinkorswimConnector(settings)

        bars1 = connector.get_price_bars("/ES", count=10)
        bars2 = connector.get_price_bars("/ES", count=10)
        assert len(bars1) == len(bars2)

    def test_volume_profile_from_bars(self, tmp_path):
        csv_path = tmp_path / "ES_price.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
            # Write bars at various prices
            for i in range(50):
                price = 5400.0 + (i % 5) * 0.25
                writer.writerow([f"2026-04-18 09:{30 + i // 2}", price, price + 0.25, price - 0.25, price, "1000"])

        settings = ThinkorswimSettings(export_dir=tmp_path)
        connector = ThinkorswimConnector(settings)
        profile = connector.get_volume_profile("/ES", "rth", 1)

        assert profile.poc is not None
        assert len(profile.nodes) > 0

    def test_tab_delimited_csv(self, tmp_path):
        csv_path = tmp_path / "ES_price.csv"
        with csv_path.open("w") as f:
            f.write("datetime\topen\thigh\tlow\tclose\tvolume\n")
            f.write("2026-04-18 09:30\t5400.00\t5410.00\t5395.00\t5405.00\t12345\n")

        settings = ThinkorswimSettings(export_dir=tmp_path)
        connector = ThinkorswimConnector(settings)
        bars = connector.get_price_bars("/ES", count=10)
        assert len(bars) == 1
        assert bars[0].volume == 12345
