"""Settings: what's required, and that a bad setting never leaks its value (FX-17)."""

import pytest

from dawalink.config import ConfigError, Settings, load_settings

SETTING_NAMES = [
    "APP_ENV",
    "APP_VERSION",
    "DATABASE_URL",
    "WEBSITE_URL",
    "DEMO_MODE",
    "LOG_LEVEL",
    "WORKER_HEARTBEAT_FILE",
]


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_loads_from_the_environment(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@db/dawalink")
    clean_environment.setenv("WEBSITE_URL", "https://example.cloudfront.net")
    clean_environment.setenv("DEMO_MODE", "true")

    settings = load_settings()

    assert settings.website_url == "https://example.cloudfront.net"
    assert settings.demo_mode is True
    assert settings.app_env == "local"


def test_missing_settings_are_named(clean_environment: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError) as failure:
        load_settings()

    assert "DATABASE_URL" in str(failure.value)
    assert "WEBSITE_URL" in str(failure.value)


def test_an_invalid_value_is_never_printed(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("DATABASE_URL", "postgresql+psycopg://user:top-secret-pw@db/x")
    clean_environment.setenv("WEBSITE_URL", "not-a-url-with-secret-token")
    clean_environment.setenv("LOG_LEVEL", "another-secret")

    with pytest.raises(ConfigError) as failure:
        load_settings()

    message = str(failure.value)
    assert "WEBSITE_URL" in message
    assert "LOG_LEVEL" in message
    assert "secret" not in message
    assert failure.value.__cause__ is None
    assert failure.value.__suppress_context__ is True


def test_website_url_is_reduced_to_its_origin() -> None:
    settings = Settings(database_url="postgresql+psycopg://u@h/d", website_url="https://site.test/")

    assert settings.website_url == "https://site.test"


@pytest.mark.parametrize("value", ["site.test", "ftp://site.test", "https://site.test/app"])
def test_website_url_must_be_an_origin(value: str) -> None:
    with pytest.raises(ValueError, match="origin"):
        Settings(database_url="postgresql+psycopg://u@h/d", website_url=value)
