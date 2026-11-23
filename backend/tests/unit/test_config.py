"""Settings: what's required, and that a bad setting never leaks its value (FX-17)."""

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dawalink import config
from dawalink.config import ConfigError, Settings, load_settings

SETTING_NAMES = [
    "APP_ENV",
    "APP_VERSION",
    "DATABASE_URL",
    "WEBSITE_URL",
    "DEMO_MODE",
    "LOG_LEVEL",
    "WORKER_HEARTBEAT_FILE",
    "APP_SECRET_KEY",
    "DEMO_ACCOUNTS_PASSWORD",
    "LLM_MONTHLY_BUDGET_USD",
]
# Invented for these tests: long enough for AWS, and published nowhere.
A_GOOD_KEY = "test-only-9Yq2vN7xK4pL8sD1fG6hJ3mB5cR0tW"
A_GOOD_PASSWORD = "Test-only demo password, 7"


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


@pytest.mark.parametrize("name", ["LANGFUSE_HOST", "LANGFUSE_BASE_URL"])
def test_the_tracing_address_has_two_names(
    clean_environment: pytest.MonkeyPatch, name: str
) -> None:
    """Langfuse's setup page gives LANGFUSE_BASE_URL; both names are read."""
    clean_environment.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@db/dawalink")
    clean_environment.setenv("WEBSITE_URL", "https://example.cloudfront.net")
    clean_environment.delenv("LANGFUSE_HOST", raising=False)
    clean_environment.delenv("LANGFUSE_BASE_URL", raising=False)
    assert load_settings().langfuse_host == "https://cloud.langfuse.com"

    clean_environment.setenv(name, "https://us.cloud.langfuse.com")

    assert load_settings().langfuse_host == "https://us.cloud.langfuse.com"


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


def test_the_monthly_model_budget_defaults_to_the_owners_20(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    """BLD-D13: a forgotten LLM_MONTHLY_BUDGET_USD must not allow five times as much."""
    clean_environment.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@db/dawalink")
    clean_environment.setenv("WEBSITE_URL", "https://example.cloudfront.net")

    assert load_settings().llm_monthly_budget_usd == Decimal(20)


class TestInAws:
    """A#16: what is fine on a laptop is refused in AWS, by name and never by value."""

    def aws(self, env: pytest.MonkeyPatch, **values: str) -> Settings:
        settings = {
            "APP_ENV": "aws",
            "DATABASE_URL": "postgresql+psycopg://user:pw@db/dawalink",
            "WEBSITE_URL": "https://example.cloudfront.net",
            "APP_SECRET_KEY": A_GOOD_KEY,
            "DEMO_MODE": "true",
            "DEMO_ACCOUNTS_PASSWORD": A_GOOD_PASSWORD,
        } | values
        for name, value in settings.items():
            env.setenv(name, value)
        return load_settings()

    def test_good_settings_load(self, clean_environment: pytest.MonkeyPatch) -> None:
        assert self.aws(clean_environment).app_env == "aws"

    def test_a_short_secret_key_is_refused(self, clean_environment: pytest.MonkeyPatch) -> None:
        short = A_GOOD_KEY[: config.AWS_MIN_SECRET_KEY_CHARS - 1]

        with pytest.raises(ConfigError, match="APP_SECRET_KEY") as failure:
            self.aws(clean_environment, APP_SECRET_KEY=short)

        assert short not in str(failure.value)
        assert failure.value.__cause__ is None

    def test_no_secret_key_is_refused(self, clean_environment: pytest.MonkeyPatch) -> None:
        with pytest.raises(ConfigError, match="APP_SECRET_KEY"):
            self.aws(clean_environment, APP_SECRET_KEY="")

    def test_demo_mode_needs_its_password(self, clean_environment: pytest.MonkeyPatch) -> None:
        with pytest.raises(ConfigError, match="DEMO_ACCOUNTS_PASSWORD"):
            self.aws(clean_environment, DEMO_ACCOUNTS_PASSWORD="")

        without_demo = self.aws(clean_environment, DEMO_MODE="false", DEMO_ACCOUNTS_PASSWORD="")
        assert without_demo.demo_accounts_password is None

    def test_an_http_website_is_refused(self, clean_environment: pytest.MonkeyPatch) -> None:
        with pytest.raises(ConfigError, match="WEBSITE_URL"):
            self.aws(clean_environment, WEBSITE_URL="http://example.cloudfront.net")

    def test_the_values_published_in_the_example_are_refused(
        self, clean_environment: pytest.MonkeyPatch
    ) -> None:
        """Compared by hash, as the code keeps them. Here with invented values in their place."""
        key, password = "x" * 40, "Published, so known 1"
        published = frozenset(
            hashlib.sha256(value.encode()).hexdigest() for value in (key, password)
        )
        clean_environment.setattr(config, "PUBLISHED_EXAMPLE_HASHES", published)

        with pytest.raises(ConfigError) as failure:
            self.aws(clean_environment, APP_SECRET_KEY=key, DEMO_ACCOUNTS_PASSWORD=password)

        message = str(failure.value)
        assert "APP_SECRET_KEY" in message
        assert "DEMO_ACCOUNTS_PASSWORD" in message
        assert key not in message
        assert password not in message

    def test_every_value_the_example_file_holds_is_known_to_the_check(self) -> None:
        """If .env.example ever gets a new value for one of the two, its hash must be added."""
        example = Path(__file__).parents[3] / ".env.example"
        for line in example.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            value = value.strip().strip("\"'")
            if name.strip() in ("APP_SECRET_KEY", "DEMO_ACCOUNTS_PASSWORD") and value:
                digest = hashlib.sha256(value.encode()).hexdigest()
                assert digest in config.PUBLISHED_EXAMPLE_HASHES, name

    def test_locally_and_in_tests_nothing_changes(self) -> None:
        for env in ("local", "test"):
            settings = Settings(
                app_env=env,
                database_url="postgresql+psycopg://u@h/d",
                website_url="http://localhost:5173",
                app_secret_key="short",
                demo_mode=True,
                demo_accounts_password=None,
            )
            assert settings.website_url == "http://localhost:5173"

    def test_the_check_is_part_of_the_settings_themselves(self) -> None:
        """So every process that builds them (API, worker, commands) refuses the same way."""
        with pytest.raises(ValidationError):
            Settings(
                app_env="aws",
                database_url="postgresql+psycopg://u@h/d",
                website_url="https://site.test",
                app_secret_key="short",
            )
