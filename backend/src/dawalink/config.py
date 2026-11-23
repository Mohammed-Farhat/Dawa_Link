"""Every setting, read from environment variables in one place (docs/12 §2)."""

import hashlib
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """A setting is missing or invalid. The message names settings, never their values."""


# In AWS the app's secret key must be at least this long: it encrypts the admins'
# two-factor secrets, so it must not be guessable (docs/10 TH-43).
AWS_MIN_SECRET_KEY_CHARS = 32
# SHA-256 of every value `.env.example` has ever published for APP_SECRET_KEY and
# DEMO_ACCOUNTS_PASSWORD. The file is public, so in AWS each of them is refused: anyone
# could log into the demo accounts, or decrypt the admins' two-factor secrets from a
# copy of the database (docs/10 RR-17). Hashes, so the values themselves are not
# repeated here.
PUBLISHED_EXAMPLE_HASHES = frozenset(
    {
        "a62b65c70899f0139999058d5a8839adb7733361eda94322ee3832b21aec2269",
        "1f7eb073c083ec152d946822246e684925a3f504e5d5fd75941106036f53057d",
        "95dbc87d7fa3458fe9fa35b7fd50f3e274a94b0846d2dad5ead72616b8c7a77c",
    }
)
# The error type of a setting refused in AWS. Its message is ours and names settings only.
UNSAFE_IN_AWS = "unsafe_in_aws"


def _is_published(value: SecretStr) -> bool:
    digest = hashlib.sha256(value.get_secret_value().encode()).hexdigest()
    return digest in PUBLISHED_EXAMPLE_HASHES


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
    # The app's own secret: admins' two-factor secrets are encrypted with it, and the
    # network address of a sign-up is hashed with it (docs/04 R-AU5, R-AU6). The API and
    # the commands that create accounts refuse to start without it.
    app_secret_key: SecretStr | None = None
    # The password of the demo accounts (`seed_demo`). Without it they can't log in.
    demo_accounts_password: SecretStr | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    worker_heartbeat_file: Path = Path(tempfile.gettempdir()) / "dawalink-worker-heartbeat"
    # Where the worker sends email: the local mail catcher in development. Without a
    # host, emails are only noted in the log (in-app notifications are unaffected).
    smtp_host: str | None = None
    smtp_port: int = 1025
    # A mail server that needs a login (Amazon SES: port 587). With a user name the worker
    # logs in, and asks for TLS first unless SMTP_STARTTLS says otherwise (docs/12 §9).
    # The local mail catcher needs neither.
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool | None = None
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
    # The app's own safety net, set by the owner (decision BLD-D13).
    llm_monthly_budget_usd: Decimal = Decimal(20)
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
        "app_secret_key",
        "demo_accounts_password",
        "anthropic_api_key",
        "ors_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "smtp_user",
        "smtp_password",
        "smtp_starttls",
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

    @model_validator(mode="after")
    def _safe_for_aws(self) -> Self:
        """In AWS, refuse what is fine on a laptop but unsafe on the internet (docs/12 §8).

        Locally and in tests nothing is checked here: their values are not secrets.
        """
        if self.app_env != "aws":
            return self
        problems: list[str] = []
        key = self.app_secret_key
        if key is None or len(key.get_secret_value()) < AWS_MIN_SECRET_KEY_CHARS:
            problems.append(f"APP_SECRET_KEY ({AWS_MIN_SECRET_KEY_CHARS} characters or more)")
        elif _is_published(key):
            problems.append("APP_SECRET_KEY (not the value published in .env.example)")
        # The demo accounts get their password only in demo mode (prepare_db), so it is
        # judged only then.
        password = self.demo_accounts_password
        if self.demo_mode and password is None:
            problems.append("DEMO_ACCOUNTS_PASSWORD (required when DEMO_MODE is on)")
        elif self.demo_mode and password is not None and _is_published(password):
            problems.append("DEMO_ACCOUNTS_PASSWORD (not the value published in .env.example)")
        if urlsplit(self.website_url).scheme != "https":
            # Over http the login token would cross the internet in clear (docs/12 §4).
            problems.append("WEBSITE_URL (https)")
        if problems:
            raise PydanticCustomError(
                UNSAFE_IN_AWS, "{settings}", {"settings": ", ".join(problems)}
            )
        return self


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
            # The check for AWS names its settings itself, and never their values.
            f"{item['msg']} (in AWS)"
            if item["type"] == UNSAFE_IN_AWS
            else f"{'.'.join(str(part) for part in item['loc']).upper()} ({item['type']})"
            for item in error.errors()
        )
        # `from None` keeps pydantic's own message, which quotes the values, out of the logs.
        raise ConfigError("Missing or invalid settings: " + ", ".join(problems)) from None
