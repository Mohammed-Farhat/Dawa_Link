"""The OpenAPI file: always served, committed, and in step with the code (docs/06 §9)."""

from pathlib import Path

from fastapi.testclient import TestClient

from dawalink.api.main import create_app
from dawalink.ops.export_openapi import openapi_spec, render
from tests.conftest import UNREACHABLE_DATABASE, make_settings

COMMITTED_SPEC = Path(__file__).parents[3] / "docs" / "openapi.json"


def test_the_spec_is_always_served(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]


def test_interactive_docs_exist_only_in_development(tmp_path: Path) -> None:
    # What AWS accepts (docs/12 §8): a long secret key and an https website.
    in_aws = {
        "website_url": "https://website.example.org",
        "app_secret_key": "test-only-kU3n8Qz1rT6vW0yB4dF7hJ2mP5sX9cL0",
    }
    for app_env, extra, expected_status in [("local", {}, 200), ("aws", in_aws, 404)]:
        settings = make_settings(UNREACHABLE_DATABASE, tmp_path, app_env=app_env, **extra)
        app = create_app(settings)
        with TestClient(app) as client:
            assert client.get("/api/v1/docs").status_code == expected_status


def test_the_committed_spec_matches_the_code() -> None:
    """If this fails, run: uv run python -m dawalink.ops.export_openapi ../docs/openapi.json"""
    assert COMMITTED_SPEC.read_text(encoding="utf-8") == render(openapi_spec())
