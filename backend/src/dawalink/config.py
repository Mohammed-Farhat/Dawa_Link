"""Every setting, read from environment variables in one place (docs/12 §2)."""

import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """A setting is missing or invalid. The message names settings, never their values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    app_env: Literal["local", "test", "aws"] = "local"
    app_version: str = "dev"
    # The app's own login: the API and the worker read and write rows with it (docs/05 §7).
    database_url: str
    # The other three logins. Only the commands that need one are given it (docs/12 §8):
    # the master and migrator logins prepare the database, the retention login deletes old rows.
    database_admin_url: str | None = None
    database_migrator_url: str | None = None
    database_retention_url: str | None = None
    # The website's origin: the only site the API accepts browser calls from (docs/06 §2.1).
    website_url: str
    demo_mode: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    worker_heartbeat_file: Path = Path(tempfile.gettempdir()) / "dawalink-worker-heartbeat"

    @field_validator("website_url")
    @classmethod
    def _must_be_an_origin(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an origin like https://example.com")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError("must be an origin without a path")
        return f"{parts.scheme}://{parts.netloc}"


def required(settings: Settings, *names: str) -> list[str]:
    """The values of settings a command can't run without, or a ConfigError naming the missing."""
    missing = sorted(name.upper() for name in names if not getattr(settings, name))
    if missing:
        raise ConfigError("Missing or invalid settings: " + ", ".join(missing))
    return [str(getattr(settings, name)) for name in names]


def load_settings() -> Settings:
    """Read the settings, or fail naming what's wrong without printing any value (FX-17)."""
    try:
        return Settings()
    except ValidationError as error:
        problems = sorted(
            f"{'.'.join(str(part) for part in item['loc']).upper()} ({item['type']})"
            for item in error.errors()
        )
        # `from None` keeps pydantic's own message, which quotes the values, out of the logs.
        raise ConfigError("Missing or invalid settings: " + ", ".join(problems)) from None
