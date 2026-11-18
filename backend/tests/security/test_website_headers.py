"""The headers the website is served with (docs/10 TH-20, TH-37, RR-13; docs/09 FS-8).

The login token is kept where a script of the page can read it, so the page must only
ever run its own scripts. Locally nginx sends these headers; in AWS the same list is typed
into CloudFront by hand (docs/12 §4.1), so this file is the list to copy from.
"""

import re
from pathlib import Path

NGINX = Path(__file__).parents[3] / "frontend" / "nginx.conf.template"


def headers() -> dict[str, str]:
    found = re.findall(r'add_header\s+([\w-]+)\s+"([^"]*)"\s+always;', NGINX.read_text("utf-8"))
    return dict(found)


def policy() -> dict[str, str]:
    """The content policy, as `{directive: sources}`."""
    parts = [part.strip().split(" ", 1) for part in headers()["Content-Security-Policy"].split(";")]
    return {part[0]: part[1] if len(part) > 1 else "" for part in parts}


def test_only_the_websites_own_scripts_may_run() -> None:
    rules = policy()

    assert rules["default-src"] == "'self'"
    assert rules["script-src"] == "'self'"
    # No inline script, no `eval`, and nothing from another site, in any directive that
    # could load code.
    for directive in ("default-src", "script-src", "object-src", "base-uri"):
        assert "unsafe-inline" not in rules[directive], directive
        assert "unsafe-eval" not in rules[directive], directive
        assert "http" not in rules[directive], directive
        assert "*" not in rules[directive], directive
    assert rules["object-src"] == "'none'"
    assert rules["base-uri"] == "'none'"


def test_the_page_talks_to_our_api_and_the_maps_pictures_only() -> None:
    rules = policy()

    assert rules["connect-src"] == "'self' ${API_ORIGIN}"
    assert rules["img-src"] == "'self' data: https://tile.openstreetmap.org"
    assert rules["form-action"] == "'self'"


def test_no_other_site_can_put_the_website_in_a_frame() -> None:
    sent = headers()

    assert policy()["frame-ancestors"] == "'none'"
    assert sent["X-Frame-Options"] == "DENY"


def test_the_other_headers() -> None:
    sent = headers()

    assert sent["X-Content-Type-Options"] == "nosniff"
    assert sent["Referrer-Policy"] == "strict-origin-when-cross-origin"
    # The location is asked only by our own page; the camera, microphone and payments never.
    assert sent["Permissions-Policy"] == "geolocation=(self), camera=(), microphone=(), payment=()"
