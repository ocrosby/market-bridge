"""Bookmap data connector.

TODO: Research Bookmap API/export capabilities and implement.
"""


class BookmapConnector:
    def __init__(self) -> None:
        pass

    async def get_heatmap(self, symbol: str, depth: int) -> dict:
        raise NotImplementedError

    async def get_volume_profile(
        self, symbol: str, session: str, lookback_days: int
    ) -> dict:
        raise NotImplementedError
