"""The contract every endpoint keeps, whatever it is for (docs/06 §9; docs/09 FI-7).

`test_every_route.py` walks the routes for "who may call". These walks are about what is
sent: a body of the wrong shape is refused with `422 VALIDATION_ERROR`, an ID that is not
an ID is refused, an ID nobody has is "not found", and none of these is ever a `500`.
An endpoint added later is checked without anyone remembering to write its test.
"""

import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from dawalink.api.errors import ErrorCode
from dawalink.services.errors import Code
from tests.agent.conftest import Scene, scene  # noqa: F401  (the fixture)
from tests.api.conftest import Api, code_of
from tests.api.test_every_route import ADMIN_PATHS, AN_ID, METHODS, PHARMACY_PATHS, PUBLIC
from tests.db.factories import TODAY

Headers = dict[str, str]

# A body no schema accepts: every `In` schema refuses a field it doesn't know.
WRONG_SHAPE = {"no_such_field": 1}
NOT_AN_ID = "not-an-id"


def described(api: Api) -> dict[str, dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = api.app(assistant=False).openapi()["paths"]
    return paths


def callers(api: Api) -> dict[str, Headers]:
    """One login of each role."""
    (pharmacist,) = api.world.one(
        "SELECT owner_user_id FROM pharmacies WHERE id = :id", id=api.world.make.pharmacy()
    )
    return {
        "client": api.token(api.client()),
        "pharmacist": api.token(pharmacist),
        "admin": api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret")),
    }


def owner_of(path: str, logins: dict[str, Headers]) -> Headers:
    """The login whose endpoint this is, by where it lives, with the key a creating tap
    carries (docs/06 §1): an endpoint that asks for one would stop there otherwise."""
    role = (
        "pharmacist"
        if path.startswith(PHARMACY_PATHS)
        else "admin"
        if path.startswith(ADMIN_PATHS)
        else "client"
    )
    return {**logins[role], "Idempotency-Key": str(uuid.uuid4())}


def with_id(path: str, value: str) -> str:
    return re.sub(r"\{[a-z_]+\}", value, path)


def test_a_body_of_the_wrong_shape_is_refused_by_every_endpoint_that_takes_one(api: Api) -> None:
    http = api.http(assistant=False)
    logins = callers(api)

    taking_a_body = 0
    wrong = []
    for path, methods in described(api).items():
        for method, operation in methods.items():
            content = operation.get("requestBody", {}).get("content", {})
            if method not in METHODS or "application/json" not in content:
                continue
            taking_a_body += 1
            answer = http.request(
                method.upper(),
                with_id(path, AN_ID),
                json=WRONG_SHAPE,
                headers=owner_of(path, logins),
            )
            if (answer.status_code, code_of(answer)) != (422, "VALIDATION_ERROR"):
                wrong.append((method.upper(), path, answer.status_code, answer.text[:120]))

    # A walk over nothing would prove nothing.
    assert taking_a_body >= 30, taking_a_body
    assert wrong == []


def test_a_body_that_is_not_json_at_all_is_refused_never_a_crash(api: Api) -> None:
    http = api.http(assistant=False)
    logins = callers(api)

    wrong = []
    for path, methods in described(api).items():
        for method, operation in methods.items():
            content = operation.get("requestBody", {}).get("content", {})
            if method not in METHODS or "application/json" not in content:
                continue
            for body in (b"{", b"[1, 2]", b'"text"', b"null"):
                answer = http.request(
                    method.upper(),
                    with_id(path, AN_ID),
                    content=body,
                    headers={**owner_of(path, logins), "Content-Type": "application/json"},
                )
                # `null` is "no body": an endpoint whose body is optional may go on to
                # say that the object doesn't exist. Nothing else may pass.
                allowed = {422} if body != b"null" else {422, 404, 409}
                if answer.status_code not in allowed:
                    wrong.append((method.upper(), path, body, answer.status_code))

    assert wrong == []


def test_an_id_that_is_not_an_id_is_refused_before_anything_is_looked_up(api: Api) -> None:
    http = api.http(assistant=False)
    logins = callers(api)

    with_an_id = 0
    wrong = []
    for path, methods in described(api).items():
        if "{" not in path:
            continue
        for method in methods:
            if method not in METHODS:
                continue
            with_an_id += 1
            answer = http.request(
                method.upper(),
                with_id(path, NOT_AN_ID),
                json={},
                headers=owner_of(path, logins),
            )
            if (answer.status_code, code_of(answer)) != (422, "VALIDATION_ERROR"):
                wrong.append((method.upper(), path, answer.status_code, answer.text[:120]))

    assert with_an_id >= 30, with_an_id
    assert wrong == []


def test_reading_an_id_nobody_has_is_not_found(api: Api) -> None:
    """Also what someone else's object answers (docs/06 §2.2): the two can't be told apart."""
    http = api.http(assistant=False)
    logins = callers(api)

    read_by_id = 0
    wrong = []
    for path, methods in described(api).items():
        if "{" not in path or "get" not in methods:
            continue
        read_by_id += 1
        answer = http.get(with_id(path, AN_ID), headers=owner_of(path, logins))
        if (answer.status_code, code_of(answer)) != (404, "NOT_FOUND"):
            wrong.append((path, answer.status_code, answer.text[:120]))

    assert read_by_id >= 10, read_by_id
    assert wrong == []


def test_every_list_refuses_a_page_size_out_of_range(api: Api) -> None:
    """N-31: 50 at most. A list that took any number would hand over a whole table."""
    http = api.http(assistant=False)
    logins = callers(api)

    paged = 0
    wrong = []
    for path, methods in described(api).items():
        names = {p["name"] for p in methods.get("get", {}).get("parameters", [])}
        if "limit" not in names or "{" in path:
            continue
        paged += 1
        for size in ("0", "-1", "100000", "many"):
            answer = http.get(path, params={"limit": size}, headers=owner_of(path, logins))
            if (answer.status_code, code_of(answer)) != (422, "VALIDATION_ERROR"):
                wrong.append((path, size, answer.status_code))

    assert paged >= 5, paged
    assert wrong == []


def test_an_endpoint_that_changes_something_refuses_another_websites_page(api: Api) -> None:
    """docs/06 §2.1: a browser on another website sends that website's `Origin`."""
    http = api.http(assistant=False)
    logins = callers(api)
    public = {(method, with_id(path, "{id}")) for method, path in PUBLIC}

    wrong = []
    for path, methods in described(api).items():
        for method in methods:
            if method not in METHODS - {"get"}:
                continue
            if (method.upper(), with_id(path, "{id}")) in public:
                continue
            answer = http.request(
                method.upper(),
                with_id(path, AN_ID),
                json={},
                headers={**owner_of(path, logins), "Origin": "https://elsewhere.example"},
            )
            if answer.status_code != 403:
                wrong.append((method.upper(), path, answer.status_code))

    assert wrong == []


# A code no endpoint can answer with, and where its test is instead. Adding a line here
# is a decision: say why.
NEVER_OVER_HTTP = {
    # Only the agent asks a pharmacy for an early release: the limit is a tool's answer to
    # the model (docs/06 §3.2). Tested in tests/services/test_early_release.py.
    "LIMIT_EARLY_RELEASE",
}


def test_every_error_code_is_caused_by_a_test_through_the_api() -> None:
    """docs/06 §9: each code of the catalog has a test that triggers it, over HTTP.

    The check is plain: a code counts when a test of the API names it (`tests/api/`, and
    `tests/failure/` for what the API answers when something it needs is down). A code
    added to the catalog without such a test fails here.
    """
    tests = Path(__file__).parents[1]
    over_http = "\n".join(
        path.read_text(encoding="utf-8")
        for folder in ("api", "failure")
        for path in (tests / folder).glob("test_*.py")
        if path.name != Path(__file__).name
    )
    codes = {code.value for code in [*Code, *ErrorCode]}

    never = sorted(code for code in codes - NEVER_OVER_HTTP if f'"{code}"' not in over_http)

    assert never == []
    assert codes >= NEVER_OVER_HTTP


def test_a_zero_byte_is_refused_in_an_address_and_in_a_body(api: Api) -> None:
    """PostgreSQL can't store one in a text: it used to come back as a server error."""
    http = api.http(assistant=False)
    logins = callers(api)

    searched = 0
    wrong = []
    for path, methods in described(api).items():
        names = {p["name"] for p in methods.get("get", {}).get("parameters", [])}
        if "q" not in names or "{" in path:
            continue
        searched += 1
        answer = http.get(f"{path}?q=a%00b", headers=owner_of(path, logins))
        if (answer.status_code, code_of(answer)) != (422, "VALIDATION_ERROR"):
            wrong.append((path, answer.status_code))
    in_a_body = http.post(
        "/api/v1/auth/login", json={"email": "a\x00b@example.com", "password": "a\x00b"}
    )

    assert searched >= 4, searched
    assert wrong == []
    assert (in_a_body.status_code, code_of(in_a_body)) == (422, "VALIDATION_ERROR")


def test_a_body_that_is_not_even_text_is_refused(api: Api) -> None:
    """Bytes that are not UTF-8: the framework's own refusal used to end as a server error."""
    http = api.http(assistant=False)

    answer = http.post(
        "/api/v1/auth/login", content=b"U\xff", headers={"Content-Type": "application/json"}
    )

    assert (answer.status_code, code_of(answer)) == (422, "VALIDATION_ERROR")
    assert answer.json()["error"]["details"]["fields"][0]["field"] == "body"


def test_a_list_refuses_a_place_to_go_on_from_that_no_table_could_have(api: Api) -> None:
    """A number the database can't hold used to come back as its own error."""
    http = api.http(assistant=False)
    logins = callers(api)

    paged = 0
    wrong = []
    for path, methods in described(api).items():
        names = {p["name"] for p in methods.get("get", {}).get("parameters", [])}
        if "cursor" not in names or "{" in path:
            continue
        paged += 1
        for cursor in ("-1", str(10**40), "soon"):
            answer = http.get(path, params={"cursor": cursor}, headers=owner_of(path, logins))
            if (answer.status_code, code_of(answer)) != (422, "VALIDATION_ERROR"):
                wrong.append((path, cursor, answer.status_code))

    assert paged >= 8, paged
    assert wrong == []


# What someone types into a search box to reach the database behind it, and the two
# characters that mean "anything" to it.
MADE_TO_BREAK_A_QUERY = (
    "'; DROP TABLE users; --",
    "' OR '1'='1",
    '" OR ""="',
    "1; SELECT pg_sleep(5)",
    "%",
    "_",
    "\\",
    "%' AND 1=1 --",
)


@pytest.mark.rows_by_hand
def test_text_made_to_break_a_query_is_only_text(api: Api) -> None:
    """docs/09 FS-9, docs/10 TH-39. Every search box of the API, as its owner, over rows
    that an ordinary search does find: the text finds nothing (it names nothing), nothing
    fails, and every table is still there."""
    http = api.http(assistant=False)
    make = api.world.make
    pharmacy = make.pharmacy(name="Hamra Pharmacy")
    (owner,) = api.world.one("SELECT owner_user_id FROM pharmacies WHERE id = :id", id=pharmacy)
    with api.world.as_owner():
        # An admin only sees a pharmacy whose email is confirmed.
        api.world.connection.exec_driver_sql(
            "UPDATE users SET email_verified_at = now() WHERE id = %s", (owner,)
        )
    product = make.product(moph_name="PANADOL 500MG", search_name="panadol 500mg")
    box = make.item(pharmacy_id=pharmacy, product_id=product, batch="LOT7", qty_reserved=1)
    order = make.order(pharmacy_id=pharmacy, product_id=product, inventory_item_id=box)
    (ref,) = api.world.one("SELECT ref FROM orders WHERE id = :id", id=order)
    logins = {
        "client": api.token(api.client()),
        "pharmacist": api.token(owner),
        "admin": api.token(make.user("admin", totp_secret=b"not-a-real-secret")),
    }
    # What an honest search finds in each box. A search box added later must be added here.
    finds = {
        "/api/v1/catalog/products": "panadol",
        "/api/v1/admin/catalog/products": "panadol",
        "/api/v1/admin/pharmacies": "hamra",
        "/api/v1/pharmacy/inventory": "lot7",
        "/api/v1/pharmacy/reservations": ref,
    }
    people = api.world.one("SELECT count(*) FROM users")

    boxes = {
        path
        for path, methods in described(api).items()
        if "q" in {p["name"] for p in methods.get("get", {}).get("parameters", [])}
    }
    wrong = []
    for path in sorted(boxes):
        login = owner_of(path, logins)
        honest = http.get(path, params={"q": finds[path]}, headers=login)
        if honest.status_code != 200 or not honest.json()["items"]:
            wrong.append((path, "an honest search found nothing", honest.status_code))
        for text in MADE_TO_BREAK_A_QUERY:
            answer = http.get(path, params={"q": text}, headers=login)
            found = answer.json().get("items") if answer.status_code == 200 else []
            if answer.status_code not in (200, 422) or found:
                wrong.append((path, text, answer.status_code))

    assert boxes == set(finds)
    assert wrong == []
    assert api.world.one("SELECT count(*) FROM users") == people


# Endpoints whose object belongs to nobody: every logged-in user may read these.
PUBLIC_OBJECTS = {
    "/api/v1/catalog/products/{product_id}",  # the catalog (never a controlled medicine)
    "/api/v1/listings/{listing_id}/view",  # a box that is listed is listed for everyone
}
# A stock file that waits has no builder here: another pharmacy's one is refused in
# tests/api/test_pharmacy_stock.py.
ELSEWHERE = ("/api/v1/pharmacy/inventory/uploads/",)


@pytest.mark.rows_by_hand
def test_someone_elses_object_does_not_exist_on_any_endpoint(api: Api, scene: Scene) -> None:  # noqa: F811
    """docs/10 TH-8, docs/06 §2.2. One client and one pharmacy own a thing of every kind;
    another client and another pharmacist call every endpoint that takes an ID with those
    real IDs. Each answer is "not found", the same as for an ID nobody has, and nothing
    has changed afterwards."""
    http = api.http(assistant=False)
    make, world = api.world.make, api.world
    reserved = make.order(client_id=scene.client, pharmacy_id=scene.pharmacy)
    offered = make.order("OFFERED", client_id=scene.client, pharmacy_id=scene.pharmacy)
    request, _thread = scene.start_request()
    card = scene.tool("propose_reservation", listing_id=scene.stock(), pickup_day=TODAY)
    theirs = {
        "conversation_id": scene.chat,
        "seq": 1,
        "reservation_id": reserved,
        "offer_id": offered,
        "request_id": request,
        "proposal_id": card["proposal_id"],
        "watch_id": make.claim(client_id=scene.client),
        "ask_id": make.early_release_ask(pharmacy_id=scene.pharmacy),
        "item_id": scene.stock(scene.concor),
    }
    scene.say("I need Augmentin")
    (other_owner,) = world.one(
        "SELECT owner_user_id FROM pharmacies WHERE id = :id", id=make.pharmacy()
    )
    logins = {"client": api.token(api.client()), "pharmacist": api.token(other_owner)}
    # What a real call of each endpoint sends, so that it gets past the form's own checks.
    bodies: dict[str, dict[str, Any]] = {
        "/conversations/{conversation_id}/location": {"district_id": 1},
        "/conversations/{conversation_id}/messages": {
            "text": "Hello",
            "client_message_id": str(uuid.uuid4()),
        },
        "/conversations/{conversation_id}/messages/{seq}/report": {"reason": "wrong_information"},
        "/offers/{offer_id}/accept": {"pickup_day": str(TODAY)},
        "/pharmacy/early-release-asks/{ask_id}/accept": {"qty": 1, "price_lbp": 100_000},
        "/pharmacy/early-release-asks/{ask_id}/decline": {"reason": "other"},
        "/pharmacy/reservations/{reservation_id}/not-available": {"units": 1},
    }
    watched = (
        "SELECT (SELECT string_agg(state, ',' ORDER BY id) FROM orders), "
        "(SELECT string_agg(state, ',' ORDER BY id) FROM sourcing_requests), "
        "(SELECT string_agg(state, ',' ORDER BY id) FROM claims), "
        "(SELECT string_agg(state, ',' ORDER BY id) FROM early_release_asks), "
        "(SELECT string_agg(qty_on_hand::text, ',' ORDER BY id) FROM inventory_items), "
        "(SELECT count(*) FROM chat_messages), (SELECT count(*) FROM answer_reports), "
        "(SELECT string_agg(coalesce(loc_source, '-'), ',' ORDER BY id) FROM conversations)"
    )
    before = world.one(watched)

    walked = 0
    wrong = []
    for path, methods in described(api).items():
        if "{" not in path or path.startswith(ADMIN_PATHS) or path in PUBLIC_OBJECTS:
            continue
        if path.startswith(ELSEWHERE):
            continue
        real = re.sub(r"\{([a-z_]+)\}", lambda found: str(theirs[found.group(1)]), path)
        for method in methods:
            if method not in METHODS:
                continue
            walked += 1
            sent = bodies.get(path.removeprefix("/api/v1"), {}) if method != "get" else None
            answer = http.request(method.upper(), real, json=sent, headers=owner_of(path, logins))
            if (answer.status_code, code_of(answer)) != (404, "NOT_FOUND"):
                wrong.append((method.upper(), path, answer.status_code, answer.text[:160]))

    assert walked >= 18, walked
    assert wrong == []
    assert world.one(watched) == before
