"""Every endpoint asks who is calling (docs/06 §2.2; Definition of Done #2; docs/09 FS-5).

The tests walk the application's own routes, so an endpoint added later is checked
without anyone remembering to write its test: it must either be on the short public
list below, or refuse a call with no login.
"""

import re

from tests.api.conftest import Api, code_of

# What a visitor may call. Adding a line here is a decision: say why.
PUBLIC = {
    ("GET", "/api/v1/health"),  # the load balancer's check
    ("GET", "/api/v1/config/public"),  # timers and the exchange rate, before login
    ("GET", "/api/v1/districts"),  # the sign-up form's list
    ("POST", "/api/v1/auth/register/client"),
    ("POST", "/api/v1/auth/register/pharmacy"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/verify-email"),  # the link of the confirmation email
}
# Any logged-in user: these are about the login itself.
ANY_ROLE = {
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/verify-email/resend"),
    ("POST", "/api/v1/auth/password"),
    # The catalog is for everyone who is logged in (docs/06 §6.2): a client searches it,
    # a pharmacy picks its products from it. It never holds stock or a controlled medicine.
    ("GET", "/api/v1/catalog/products"),
    ("GET", "/api/v1/catalog/products/{id}"),
    # Everyone has notifications: a client's are CN-x, a pharmacy's PN-x. Each route
    # reads or changes the caller's own rows only.
    ("GET", "/api/v1/notifications"),
    ("GET", "/api/v1/notifications/unread-count"),
    ("POST", "/api/v1/notifications/read"),
}
# Whose endpoints the others are, by where they live.
PHARMACY_PATHS = ("/api/v1/pharmacy",)
ADMIN_PATHS = ("/api/v1/admin",)

AN_ID = "11111111-1111-4111-8111-111111111111"


METHODS = {"get", "post", "put", "patch", "delete"}


def endpoints(api: Api) -> list[tuple[str, str]]:
    """`(method, path)` of every endpoint, with an ID in place of each `{name}`.

    Read from the API's own description, the same list the website's types come from.
    """
    described = api.app(assistant=False).openapi()["paths"]
    found = [
        (method.upper(), re.sub(r"\{[a-z_]+\}", AN_ID, path))
        for path, methods in described.items()
        for method in methods
        if method in METHODS
    ]
    # A walk over nothing would prove nothing.
    assert len(found) >= 15, found
    return found


def template(path: str) -> str:
    return path.replace(AN_ID, "{id}")


def test_every_endpoint_but_the_public_ones_refuses_a_call_with_no_login(api: Api) -> None:
    http = api.http(assistant=False)
    public = {(method, template(path)) for method, path in PUBLIC}

    let_in = []
    for method, path in endpoints(api):
        if (method, template(path)) in public:
            continue
        answer = http.request(method, path, json={})
        if (answer.status_code, code_of(answer)) != (401, "UNAUTHENTICATED"):
            let_in.append((method, path, answer.status_code))

    assert let_in == []


def test_a_clients_endpoints_refuse_a_pharmacist_and_an_admin(api: Api) -> None:
    http = api.http(assistant=False)
    skip = {(method, template(path)) for method, path in PUBLIC | ANY_ROLE}
    others = {
        "pharmacist": api.token(api.world.make.user("pharmacist")),
        "admin": api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret")),
    }

    let_in = []
    for method, path in endpoints(api):
        if (method, template(path)) in skip or path.startswith(PHARMACY_PATHS + ADMIN_PATHS):
            continue
        for role, headers in others.items():
            answer = http.request(method, path, json={}, headers=headers)
            if (answer.status_code, code_of(answer)) != (403, "FORBIDDEN"):
                let_in.append((role, method, path, answer.status_code))

    assert let_in == []


def test_a_pharmacys_endpoints_refuse_a_client_and_an_admin(api: Api) -> None:
    http = api.http(assistant=False)
    others = {
        "client": api.token(api.client()),
        "admin": api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret")),
    }
    theirs = [(m, p) for m, p in endpoints(api) if p.startswith(PHARMACY_PATHS)]
    assert len(theirs) >= 8, theirs

    let_in = []
    for method, path in theirs:
        for role, headers in others.items():
            answer = http.request(method, path, json={}, headers=headers)
            if (answer.status_code, code_of(answer)) != (403, "FORBIDDEN"):
                let_in.append((role, method, path, answer.status_code))

    assert let_in == []


def test_an_admins_endpoints_refuse_a_client_and_a_pharmacist(api: Api) -> None:
    http = api.http(assistant=False)
    others = {
        "client": api.token(api.client()),
        "pharmacist": api.token(api.world.make.user("pharmacist")),
    }
    theirs = [(m, p) for m, p in endpoints(api) if p.startswith(ADMIN_PATHS)]
    assert theirs, "no admin endpoint was found"

    let_in = []
    for method, path in theirs:
        for role, headers in others.items():
            answer = http.request(method, path, json={}, headers=headers)
            if (answer.status_code, code_of(answer)) != (403, "FORBIDDEN"):
                let_in.append((role, method, path, answer.status_code))

    assert let_in == []


def test_every_endpoint_has_a_name_of_its_own(api: Api) -> None:
    """The website's generated client names its calls after these: two endpoints with one
    name would silently share one."""
    described = api.app(assistant=False).openapi()["paths"]
    names = [
        operation["operationId"]
        for methods in described.values()
        for method, operation in methods.items()
        if method in METHODS
    ]

    assert sorted(names) == sorted(set(names))


def test_the_public_list_names_only_endpoints_that_exist(api: Api) -> None:
    known = {(method, template(path)) for method, path in endpoints(api)}

    gone = sorted((PUBLIC | ANY_ROLE) - known)

    assert gone == []
