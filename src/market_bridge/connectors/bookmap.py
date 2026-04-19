"""Bookmap data connector.

Bookmap does not expose a public REST API. This connector works with
exported data files from Bookmap's "Export Heatmap Data" feature
(Tools -> Export Heatmap Data) and CSV level exports.

Supported export formats:
  - Heatmap CSV: timestamp, price, bid_size, ask_size
  - Volume profile CSV: price, volume
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Union

from market_bridge.config import BookmapSettings
from market_bridge.models import Heatmap, HeatmapLevel, VolumeNode, VolumeProfile

logger = logging.getLogger(__name__)


class BookmapError(Exception):
    pass


class BookmapConnector:
    def __init__(self, settings: BookmapSettings) -> None:
        self.settings = settings
        self._file_cache: dict[str, tuple[float, Union[Heatmap, VolumeProfile]]] = {}

    @property
    def is_configured(self) -> bool:
        return self.settings.is_configured

    def _is_stale(self, path: Path) -> bool:
        """Check if the cached data for a file is stale."""
        cached = self._file_cache.get(str(path))
        if cached is None:
            return True
        cached_mtime, _ = cached
        try:
            return path.stat().st_mtime > cached_mtime
        except (FileNotFoundError, OSError):
            del self._file_cache[str(path)]
            return True

    def _get_cached_heatmap(self, path: Path) -> Heatmap | None:
        if self._is_stale(path):
            return None
        value = self._file_cache[str(path)][1]
        return value if isinstance(value, Heatmap) else None

    def _get_cached_profile(self, path: Path) -> VolumeProfile | None:
        if self._is_stale(path):
            return None
        value = self._file_cache[str(path)][1]
        return value if isinstance(value, VolumeProfile) else None

    def _set_cached(self, path: Path, value: Heatmap | VolumeProfile) -> None:
        try:
            self._file_cache[str(path)] = (path.stat().st_mtime, value)
        except (FileNotFoundError, OSError):
            pass

    def _find_latest_file(self, pattern: str) -> Path | None:
        """Find the most recently modified file matching a glob pattern."""
        if not self.settings.export_dir.is_dir():
            return None
        files = sorted(
            self.settings.export_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files[0] if files else None

    def get_heatmap(self, symbol: str, depth: int = 10) -> Heatmap:
        """Load heatmap data from the latest Bookmap export file."""
        symbol_clean = symbol.lstrip("/").upper()

        path = (
            self._find_latest_file(f"*{symbol_clean}*heatmap*.csv")
            or self._find_latest_file("*heatmap*.csv")
        )

        if not path:
            logger.info("No Bookmap heatmap export found in %s", self.settings.export_dir)
            return Heatmap(symbol=symbol)

        cached = self._get_cached_heatmap(path)
        if cached is not None:
            return Heatmap(symbol=symbol, bids=cached.bids[:depth], asks=cached.asks[:depth])

        heatmap = self._parse_heatmap_csv(path, symbol, depth=50)
        self._set_cached(path, heatmap)
        return Heatmap(symbol=symbol, bids=heatmap.bids[:depth], asks=heatmap.asks[:depth])

    def _parse_heatmap_csv(self, path: Path, symbol: str, depth: int) -> Heatmap:
        bids: list[HeatmapLevel] = []
        asks: list[HeatmapLevel] = []

        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return Heatmap(symbol=symbol)

            col_map = {c.strip().lower(): c for c in reader.fieldnames}

            price_col = col_map.get("price")
            bid_col = col_map.get("bid_size") or col_map.get("bidsize") or col_map.get("bid")
            ask_col = col_map.get("ask_size") or col_map.get("asksize") or col_map.get("ask")

            if not (price_col and (bid_col or ask_col)):
                logger.warning("Heatmap CSV missing expected columns: %s", reader.fieldnames)
                return Heatmap(symbol=symbol)

            bid_map: dict[float, int] = {}
            ask_map: dict[float, int] = {}

            for row in reader:
                try:
                    price = float(row[price_col])
                    if bid_col and row.get(bid_col):
                        size = int(float(row[bid_col]))
                        if size > 0:
                            bid_map[price] = size
                    if ask_col and row.get(ask_col):
                        size = int(float(row[ask_col]))
                        if size > 0:
                            ask_map[price] = size
                except (ValueError, KeyError):
                    continue

        sorted_bids = sorted(bid_map.items(), key=lambda x: x[0], reverse=True)
        sorted_asks = sorted(ask_map.items(), key=lambda x: x[0])

        bids = [HeatmapLevel(price=p, size=s) for p, s in sorted_bids[:depth]]
        asks = [HeatmapLevel(price=p, size=s) for p, s in sorted_asks[:depth]]

        logger.info("Loaded heatmap from %s: %d bids, %d asks", path.name, len(bids), len(asks))
        return Heatmap(symbol=symbol, bids=bids, asks=asks)

    def get_volume_profile(
        self, symbol: str, session: str, lookback_days: int
    ) -> VolumeProfile:
        """Load volume profile from the latest Bookmap export file."""
        symbol_clean = symbol.lstrip("/").upper()

        path = (
            self._find_latest_file(f"*{symbol_clean}*volume*.csv")
            or self._find_latest_file(f"*{symbol_clean}*profile*.csv")
            or self._find_latest_file("*volume*.csv")
            or self._find_latest_file("*profile*.csv")
        )

        if not path:
            logger.info("No Bookmap volume profile export found in %s", self.settings.export_dir)
            return VolumeProfile(symbol=symbol, session=session, lookback_days=lookback_days)

        cached = self._get_cached_profile(path)
        if cached is not None:
            return cached

        profile = self._parse_volume_csv(path, symbol, session, lookback_days)
        self._set_cached(path, profile)
        return profile

    def _parse_volume_csv(
        self, path: Path, symbol: str, session: str, lookback_days: int
    ) -> VolumeProfile:
        nodes: list[VolumeNode] = []

        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return VolumeProfile(symbol=symbol, session=session, lookback_days=lookback_days)

            col_map = {c.strip().lower(): c for c in reader.fieldnames}
            price_col = col_map.get("price")
            vol_col = col_map.get("volume") or col_map.get("vol")

            if not (price_col and vol_col):
                logger.warning("Volume CSV missing expected columns: %s", reader.fieldnames)
                return VolumeProfile(symbol=symbol, session=session, lookback_days=lookback_days)

            for row in reader:
                try:
                    price = float(row[price_col])
                    volume = int(float(row[vol_col]))
                    nodes.append(VolumeNode(price=price, volume=volume))
                except (ValueError, KeyError):
                    continue

        if not nodes:
            return VolumeProfile(symbol=symbol, session=session, lookback_days=lookback_days)

        total_vol = sum(n.volume for n in nodes)
        poc_node = max(nodes, key=lambda n: n.volume)
        poc = poc_node.price

        sorted_nodes = sorted(nodes, key=lambda n: n.price)
        poc_idx = next(i for i, n in enumerate(sorted_nodes) if n.price == poc)
        va_target = total_vol * 0.70
        va_vol = sorted_nodes[poc_idx].volume
        lo_idx = poc_idx
        hi_idx = poc_idx

        while va_vol < va_target and (lo_idx > 0 or hi_idx < len(sorted_nodes) - 1):
            vol_below = sorted_nodes[lo_idx - 1].volume if lo_idx > 0 else 0
            vol_above = sorted_nodes[hi_idx + 1].volume if hi_idx < len(sorted_nodes) - 1 else 0
            if vol_below >= vol_above and lo_idx > 0:
                lo_idx -= 1
                va_vol += sorted_nodes[lo_idx].volume
            elif hi_idx < len(sorted_nodes) - 1:
                hi_idx += 1
                va_vol += sorted_nodes[hi_idx].volume
            elif lo_idx > 0:
                lo_idx -= 1
                va_vol += sorted_nodes[lo_idx].volume
            else:
                break

        val = sorted_nodes[lo_idx].price
        vah = sorted_nodes[hi_idx].price

        logger.info("Loaded volume profile from %s: %d nodes, POC=%.2f", path.name, len(nodes), poc)
        return VolumeProfile(
            symbol=symbol,
            session=session,
            lookback_days=lookback_days,
            poc=poc,
            vah=vah,
            val=val,
            nodes=sorted_nodes,
        )
