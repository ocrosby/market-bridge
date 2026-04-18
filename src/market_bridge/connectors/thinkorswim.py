"""Thinkorswim CSV watcher connector.

Watches a directory for CSV files exported from TOS thinkScript studies
and parses them into normalized data.

TODO: Implement file watcher and CSV parsing.
"""

from pathlib import Path


class ThinkorswimConnector:
    def __init__(self, watch_dir: Path | None = None) -> None:
        self.watch_dir = watch_dir

    async def start_watching(self) -> None:
        raise NotImplementedError

    async def get_latest_data(self, symbol: str) -> dict:
        raise NotImplementedError
