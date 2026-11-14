"""Every setting, read from environment variables in one place (docs/12 §2)."""

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator
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
    # Where the worker sends email: the local mail catcher in development. Without a
    # host, emails are only noted in the log (in-app notifications are unaffected).
    smtp_host: str | None = None
    smtp_port: int = 1025
    email_from: str = "DawaLink <no-reply@dawalink.invalid>"
    # Which model the agent thinks with (docs/07 §10). "none" switches the assistant off,
    # and is the default: nothing is ever spent by accident. Tests use a scripted model
    # they build themselves.
    llm_provider: Literal["none", "ollama", "anthropic"] = "none"
    # Empty: the provider's default (the local model). A Claude model is always named.
    llm_model: str = ""
    # How hard a Claude model thinks. Always sent, because its default differs by model.
    llm_effort: Literal["low", "medium", "high"] = "medium"
    ollama_url: str = "http://127.0.0.1:11434"
    # Keys are secrets: they never appear in a log line or an error message.
    anthropic_api_key: SecretStr | None = None
    # The month's LLM budget in USD: the global spend caps are counted from it (N-46).
    llm_monthly_budget_usd: Decimal = Decimal(100)
    # Road travel times (docs/04 R-RT1). Without a key, every time is the estimate.
    ors_api_key: SecretStr | None = None
    ors_url: str = "https://api.heigit.org/openrouteservice"
    # Agent traces (docs/07 §9). Without keys, turns are recorded in our own tables only.
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    # Langfuse's own setup page calls it LANGFUSE_BASE_URL; older guides say LANGFUSE_HOST.
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("langfuse_host", "langfuse_base_url"),
    )

    @field_validator(
        "anthropic_api_key",
        "ors_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        mode="before",
    )
    @classmethod
    def _an_empty_key_is_no_key(cls, value: object) -> object:
        """`ORS_API_KEY=` in a .env file means "not set", not a key of no characters."""
        return None if isinstance(value, str) and not value.strip() else value

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
