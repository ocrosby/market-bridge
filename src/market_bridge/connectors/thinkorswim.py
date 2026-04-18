"""Thinkorswim CSV watcher connector.

Watches a directory for CSV files exported from TOS thinkScript studies
and parses them into normalized data models.

TOS thinkScript export format (typical):
  - Column headers vary by study but commonly include:
    datetime/date/time, open, high, low, close, volume
  - Date formats: "yyyy-MM-dd HH:mm" or "MM/dd/yyyy HH:mm"
  - Studies may add extra columns (e.g., SMA, VWAP, delta)

File naming convention expected:
  - {symbol}_price.csv     -> OHLCV data
  - {symbol}_volume.csv    -> volume profile data
  - {symbol}_study.csv     -> custom study data
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from market_bridge.config import ThinkorswimSettings
from market_bridge.models import Bar, VolumeNode, VolumeProfile, tick_size

logger = logging.getLogger(__name__)

# Common date formats from TOS exports
DATE_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y",
]


class ThinkorswimError(Exception):
    pass


class ThinkorswimConnector:
    def __init__(self, settings: ThinkorswimSettings) -> None:
        self.settings = settings
        self._file_cache: dict[str, tuple[float, list]] = {}

    @property
    def is_configured(self) -> bool:
        return self.settings.is_configured

    def _find_latest_file(self, pattern: str) -> Path | None:
        if not self.settings.export_dir.is_dir():
            return None
        files = sorted(
            self.settings.export_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files[0] if files else None

    def _is_stale(self, path: Path) -> bool:
        """Check if the cached data for a file is stale."""
        cached = self._file_cache.get(str(path))
        if cached is None:
            return True
        cached_mtime, _ = cached
        return path.stat().st_mtime > cached_mtime

    def get_price_bars(self, symbol: str, count: int = 50) -> list[Bar]:
        """Load OHLCV bars from a TOS price export CSV."""
        symbol_clean = symbol.lstrip("/").upper()

        path = (
            self._find_latest_file(f"*{symbol_clean}*price*.csv")
            or self._find_latest_file(f"*{symbol_clean}*.csv")
        )

        if not path:
            logger.info("No TOS price export found for %s in %s", symbol, self.settings.export_dir)
            return []

        # Use cache if file hasn't changed
        cache_key = str(path)
        if not self._is_stale(path):
            _, bars = self._file_cache[cache_key]
            return bars[-count:]

        bars = self._parse_price_csv(path)
        self._file_cache[cache_key] = (path.stat().st_mtime, bars)
        return bars[-count:]

    def _parse_price_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []

        with path.open(newline="") as f:
            # TOS sometimes uses different delimiters
            sample = f.read(2048)
            f.seek(0)
            delimiter = "," if "," in sample else "\t"

            reader = csv.DictReader(f, delimiter=delimiter)
            if not reader.fieldnames:
                return []

            col_map = {c.strip().lower(): c for c in reader.fieldnames}

            # Find column names (TOS uses various naming)
            dt_col = _find_col(col_map, "datetime", "date", "time", "timestamp")
            open_col = _find_col(col_map, "open")
            high_col = _find_col(col_map, "high")
            low_col = _find_col(col_map, "low")
            close_col = _find_col(col_map, "close", "last")
            vol_col = _find_col(col_map, "volume", "vol")

            if not (dt_col and close_col):
                logger.warning("TOS CSV missing required columns: %s", reader.fieldnames)
                return []

            for row in reader:
                try:
                    timestamp = _parse_datetime(row[dt_col].strip())
                    bars.append(Bar(
                        timestamp=timestamp,
                        open=float(row.get(open_col, 0) or 0) if open_col else 0.0,
                        high=float(row.get(high_col, 0) or 0) if high_col else 0.0,
                        low=float(row.get(low_col, 0) or 0) if low_col else 0.0,
                        close=float(row[close_col]),
                        volume=int(float(row.get(vol_col, 0) or 0)) if vol_col else 0,
                    ))
                except (ValueError, KeyError) as e:
                    logger.debug("Skipping row in %s: %s", path.name, e)
                    continue

        logger.info("Loaded %d bars from TOS export %s", len(bars), path.name)
        return bars

    def get_volume_profile(
        self, symbol: str, session: str, lookback_days: int
    ) -> VolumeProfile:
        """Build a volume profile from TOS price export data."""
        bars = self.get_price_bars(symbol, count=lookback_days * 400)

        if not bars:
            return VolumeProfile(symbol=symbol, session=session, lookback_days=lookback_days)

        # Build price -> volume map
        tick = tick_size(symbol)
        price_vol: dict[float, int] = {}
        total_vol = 0
        for bar in bars:
            price = round(round(bar.close / tick) * tick, 2)
            price_vol[price] = price_vol.get(price, 0) + bar.volume
            total_vol += bar.volume

        if not price_vol:
            return VolumeProfile(symbol=symbol, session=session, lookback_days=lookback_days)

        nodes = [VolumeNode(price=p, volume=v) for p, v in sorted(price_vol.items())]

        # POC
        poc_node = max(nodes, key=lambda n: n.volume)
        poc = poc_node.price

        # Value area (70%)
        sorted_nodes = sorted(nodes, key=lambda n: n.price)
        poc_idx = next(i for i, n in enumerate(sorted_nodes) if n.price == poc)
        va_target = total_vol * 0.70
        va_vol = sorted_nodes[poc_idx].volume
        lo = poc_idx
        hi = poc_idx

        while va_vol < va_target and (lo > 0 or hi < len(sorted_nodes) - 1):
            vol_below = sorted_nodes[lo - 1].volume if lo > 0 else 0
            vol_above = sorted_nodes[hi + 1].volume if hi < len(sorted_nodes) - 1 else 0
            if vol_below >= vol_above and lo > 0:
                lo -= 1
                va_vol += sorted_nodes[lo].volume
            elif hi < len(sorted_nodes) - 1:
                hi += 1
                va_vol += sorted_nodes[hi].volume
            else:
                lo -= 1
                va_vol += sorted_nodes[lo].volume

        return VolumeProfile(
            symbol=symbol,
            session=session,
            lookback_days=lookback_days,
            poc=poc,
            vah=sorted_nodes[hi].price,
            val=sorted_nodes[lo].price,
            nodes=sorted_nodes,
        )


def _find_col(col_map: dict[str, str], *candidates: str) -> str | None:
    """Find a column name from a list of candidates."""
    for name in candidates:
        if name in col_map:
            return col_map[name]
    return None


def _parse_datetime(value: str) -> str:
    """Parse a datetime string trying multiple formats, return ISO string."""
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    # If no format matches, return as-is
    return value
