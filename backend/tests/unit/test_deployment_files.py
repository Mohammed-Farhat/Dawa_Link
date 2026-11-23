"""The files that build and start DawaLink, read as text (docs/12 §6, §8, §12).

Nothing here runs Docker: these are the promises the deployment guide makes about the
images and docker-compose.yml, kept true when one of the files changes.
"""

import re
from pathlib import Path
from typing import Any

from dawalink.config import Settings
from dawalink.domain.numbers import TURN_TIME_LIMIT_CHAT_S, WORKER_STOP_WAIT_S

ROOT = Path(__file__).parents[3]
BACKEND_IMAGE = ROOT / "backend" / "Dockerfile"
WEBSITE_IMAGE = ROOT / "frontend" / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
EXAMPLE = ROOT / ".env.example"
GUIDE = ROOT / "docs" / "12_infrastructure.md"

# The load balancer's idle timeout, as docs/12 §5 leaves it (AWS's default).
ALB_IDLE_TIMEOUT_S = 60
# What ECS and docker-compose give a stopping task (docs/12 §6).
STOP_TIMEOUT_S = 120


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def api_command_option(name: str) -> int:
    """A number given to uvicorn in the image's command, as `"--name", "75"`."""
    found = re.search(rf'"--{name}",\s*"(\d+)"', text(BACKEND_IMAGE))
    assert found, f"--{name} is missing from the API's command"
    return int(found.group(1))


def compose_seconds(setting: str) -> list[int]:
    """Every value of a compose setting written as `120s`."""
    return [
        int(value) for value in re.findall(rf"^\s*{setting}:\s*(\d+)s\s*$", text(COMPOSE), re.M)
    ]


class TestTheBackendImage:
    def test_a_forgotten_app_env_is_aws(self) -> None:
        """A#2: a task definition without APP_ENV must not count every visitor as the
        load balancer, nor serve the interactive API docs."""
        assert re.search(r"^ENV .*\bAPP_ENV=aws\b", text(BACKEND_IMAGE), re.M)

    def test_the_laptop_says_local(self) -> None:
        assert "APP_ENV: ${APP_ENV:-local}" in text(COMPOSE)

    def test_the_version_is_given_at_build_time(self) -> None:
        """A#18: /health shows which build runs."""
        image = text(BACKEND_IMAGE)
        assert "ARG APP_VERSION" in image
        assert "ENV APP_VERSION=${APP_VERSION}" in image
        assert re.search(r"args:\s*\n\s*APP_VERSION:", text(COMPOSE))

    def test_idle_connections_outlive_the_load_balancers(self) -> None:
        """A#15: the load balancer must always be the one to close an idle connection."""
        assert api_command_option("timeout-keep-alive") > ALB_IDLE_TIMEOUT_S

    def test_a_stopping_api_fits_in_its_stop_time(self) -> None:
        """Open answers get the graceful stop, then running chat turns finish (main.py)."""
        graceful = api_command_option("timeout-graceful-shutdown")
        assert graceful + TURN_TIME_LIMIT_CHAT_S < STOP_TIMEOUT_S

    def test_settings_files_stay_out_of_both_images(self) -> None:
        for ignore in (ROOT / "backend" / ".dockerignore", ROOT / "frontend" / ".dockerignore"):
            assert ".env*" in text(ignore).splitlines(), ignore


class TestCompose:
    def test_a_stopping_worker_is_given_its_whole_wait(self) -> None:
        """A#21: docker's default 10 s would cut a running agent turn in the middle."""
        grace = compose_seconds("stop_grace_period")
        assert grace
        assert all(WORKER_STOP_WAIT_S < seconds <= STOP_TIMEOUT_S for seconds in grace)

    def test_the_secret_key_has_no_value_written_in_a_public_file(self) -> None:
        """A#16: compose stops and says what to do, rather than start with a known key."""
        assert "${APP_SECRET_KEY:?" in text(COMPOSE)


class TestTheExampleSettings:
    def values(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for line in text(EXAMPLE).splitlines():
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                found[name.strip()] = value.strip()
        return found

    def test_no_usable_secret_is_published(self) -> None:
        """A#16: the two values are made by each person, with the command beside them."""
        values = self.values()
        assert values["APP_SECRET_KEY"] == ""
        assert values["DEMO_ACCOUNTS_PASSWORD"] == ""
        assert text(EXAMPLE).count("import secrets") == 2

    def test_the_example_loads_as_settings(self) -> None:
        """Copied as it is, the file must still be read (an empty port would not be)."""
        given: dict[str, Any] = {name.lower(): value for name, value in self.values().items()}
        settings = Settings(**given)
        assert settings.app_env == "local"
        assert settings.app_secret_key is None


class TestTheWebsiteImage:
    def test_it_is_never_built_without_the_apis_address(self) -> None:
        """A#17: built without it, every call would go to the website's own address."""
        image = text(WEBSITE_IMAGE)
        check = image.index('test -n "$VITE_API_URL"')
        assert check < image.index("RUN npm run build")
        assert image.index("RUN npm ci") < image.index("ARG VITE_API_URL")


class TestTheGuide:
    def test_it_names_every_setting(self) -> None:
        """A#18: every setting the code reads is in the guide's list for the task
        definitions, so none silently keeps a default in AWS."""
        guide = text(GUIDE)
        aliases = {"langfuse_host": "LANGFUSE_BASE_URL"}
        missing = [
            name
            for field in Settings.model_fields
            if (name := aliases.get(field, field.upper())) not in guide
        ]
        assert not missing
        # Read by create_admin itself, outside the settings.
        assert "ADMIN_PASSWORD" in guide
