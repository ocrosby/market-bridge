"""Tradovate REST + WebSocket API connector.

TODO: Implement OAuth2 auth flow and WebSocket connection.
Reference: https://api.tradovate.com/
"""


class TradovateConnector:
    def __init__(self, api_url: str = "https://demo.tradovateapi.com/v1") -> None:
        self.api_url = api_url
        self.access_token: str | None = None
        self.ws = None

    async def authenticate(self, username: str, password: str, app_id: str) -> None:
        raise NotImplementedError

    async def connect_websocket(self) -> None:
        raise NotImplementedError

    async def get_bars(
        self, symbol: str, timeframe: str, count: int
    ) -> list[dict]:
        raise NotImplementedError

    async def subscribe_quotes(self, symbol: str) -> None:
        raise NotImplementedError
