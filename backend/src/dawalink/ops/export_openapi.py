"""Writes the API's OpenAPI file: python -m dawalink.ops.export_openapi ../docs/openapi.json

Re-run it in any change that touches the API (docs/06 §9). A test compares the committed
file with the code, and the website's TypeScript types are generated from it.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from dawalink.api.main import create_app
from dawalink.config import Settings

# The spec doesn't depend on the settings, so the export needs no real database or website.
_EXPORT_SETTINGS = Settings(
    app_env="test",
    database_url="postgresql+psycopg://export@localhost/export",
    website_url="http://localhost",
)


def openapi_spec() -> dict[str, Any]:
    return create_app(_EXPORT_SETTINGS).openapi()


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    arguments.output.write_text(render(openapi_spec()), encoding="utf-8", newline="\n")
    print(f"wrote {arguments.output}")


if __name__ == "__main__":
    main()
