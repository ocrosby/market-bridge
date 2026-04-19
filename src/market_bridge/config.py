"""Configuration loaded from environment variables or .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class TradovateSettings(BaseSettings):
    model_config = {"env_prefix": "TRADOVATE_"}

    username: str = ""
    password: str = ""
    app_id: str = ""
    app_version: str = "1.0"
    cid: int = 0
    sec: str = ""
    demo: bool = True

    @property
    def base_url(self) -> str:
        if self.demo:
            return "https://demo.tradovateapi.com/v1"
        return "https://live.tradovateapi.com/v1"

    @property
    def md_url(self) -> str:
        if self.demo:
            return "wss://md-demo.tradovateapi.com/v1/websocket"
        return "wss://md.tradovateapi.com/v1/websocket"

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password and self.app_id and self.sec)


class BookmapSettings(BaseSettings):
    model_config = {"env_prefix": "BOOKMAP_"}

    export_dir: Path = Field(default=Path.home() / "Documents" / "Bookmap" / "exports")

    @property
    def is_configured(self) -> bool:
        return self.export_dir.is_dir()


class ThinkorswimSettings(BaseSettings):
    model_config = {"env_prefix": "TOS_"}

    export_dir: Path = Field(default=Path.home() / "Documents" / "thinkorswim" / "exports")

    @property
    def is_configured(self) -> bool:
        return self.export_dir.is_dir()


class CacheSettings(BaseSettings):
    model_config = {"env_prefix": "CACHE_"}

    default_ttl: int = 30
    max_entries: int = 500


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    tradovate: TradovateSettings = Field(default_factory=TradovateSettings)
    bookmap: BookmapSettings = Field(default_factory=BookmapSettings)
    thinkorswim: ThinkorswimSettings = Field(default_factory=ThinkorswimSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)


def get_settings() -> Settings:
    """Create settings from environment variables and .env file."""
    return Settings()
