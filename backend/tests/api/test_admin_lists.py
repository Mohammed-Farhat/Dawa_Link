"""The admin's lists as numbered pages, the audit log in words, the Health page's limits
(docs/03 AS-3, AS-5, AS-9, AS-10, AS-11; the owner, 2026-11-23).

What these tests hold on to:
- a list's `total` counts what its choices match, the same on every page;
- the audit log names who did what, an admin by name and a client by an ID only, and the
  page it is about, with one query per kind of ID for a whole page;
- **the values of the fields that changed are never in an audit answer;**
- every audit code the backend writes is known, so the console has a sentence for it;
- the Health page reads each client's own limits and the budget for everyone.
"""

import ast
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
from sqlalchemy import event

from dawalink.api.schemas.admin import AuditKindName, FlagAction
from dawalink.db.models import ChatMessage
from dawalink.domain.audit_actions import KINDS, AuditAction, kind_of
from dawalink.domain.numbers import CHAT_MESSAGES_PER_DAY, DAILY_TOKEN_BUDGET_PER_CLIENT
from dawalink.domain.state_machine import Actor
from dawalink.services import audit
from tests.api.conftest import Api

ADMIN = "/api/v1/admin"
# The lists are filled with reservations built by hand, with no stock behind them: the
# end-of-test check that reserved units add up is not for them.
pytestmark = pytest.mark.rows_by_hand
SOURCE = Path(__file__).resolve().parents[2] / "src" / "dawalink"


@pytest.fixture
def admin(api: Api) -> dict[str, str]:
    return api.token(admin_user(api, "Rania Admin"))


def admin_user(api: Api, name: str) -> uuid.UUID:
    return api.world.make.user(  # type: ignore[no-any-return]
        "admin", totp_secret=b"not-a-real-secret", full_name=name
    )


def confirmed_pharmacy(api: Api, status: str = "APPROVED", **values: Any) -> uuid.UUID:
    """A pharmacy an admin can open: its login confirmed its email."""
    owner = api.world.make.user("pharmacist", email_verified_at=api.world.clock.now())
    return api.world.make.pharmacy(status, owner_user_id=owner, **values)  # type: ignore[no-any-return]


def write(api: Api, actor: Actor, action: str, entity: str, entity_id: Any, **more: Any) -> None:
    """An audit event, written as the services write one."""
    tx = api.world.tx()
    audit.record(tx, actor, action, entity, entity_id, **more)
    api.world.session.flush()


def page(api: Api, admin: dict[str, str], path: str) -> dict[str, Any]:
    answer = api.http().get(f"{ADMIN}{path}", headers=admin)
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


# --- Numbered pages ----------------------------------------------------------------------------


class TestTotals:
    def test_pharmacies_26_rows_make_two_pages(self, api: Api, admin: dict[str, str]) -> None:
        for number in range(26):
            confirmed_pharmacy(api, name=f"Paging Pharmacy {number:02d}")
        confirmed_pharmacy(api, name="Another One")
        # Its email was never confirmed: in no list, in no total (R-AU7).
        api.world.make.pharmacy("APPROVED", name="Paging Ghost")

        first = page(api, admin, "/pharmacies?status=APPROVED&q=paging&limit=25")
        second = page(api, admin, "/pharmacies?status=APPROVED&q=paging&limit=25&cursor=25")
        everyone = page(api, admin, "/pharmacies?status=APPROVED&limit=1")
        past = page(api, admin, "/pharmacies?status=APPROVED&q=paging&limit=25&cursor=100")

        assert (len(first["items"]), first["total"], first["next_cursor"]) == (25, 26, "25")
        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, 26, None)
        assert everyone["total"] == 27
        # An empty page still says how many there are: the website moves to the last page.
        assert (past["items"], past["total"]) == ([], 26)

    def test_clients_with_their_filters(self, api: Api, admin: dict[str, str]) -> None:
        clients = [api.world.make.client("ACTIVE") for _ in range(26)]
        api.world.make.client("SUSPENDED")
        api.world.make.order("RESERVED", client_id=clients[0])

        first = page(api, admin, "/clients?status=ACTIVE&limit=25")
        second = page(api, admin, "/clients?status=ACTIVE&limit=25&cursor=25")
        reserving = page(api, admin, "/clients?having=reservation")

        assert (len(first["items"]), first["total"]) == (25, 26)
        assert (len(second["items"]), second["total"]) == (1, 26)
        assert reserving["total"] == 1

    def test_the_catalog(self, api: Api, admin: dict[str, str]) -> None:
        for number in range(26):
            api.world.make.product(
                moph_name=f"PAGEMOL {number:02d}", search_name=f"pagemol {number:02d}"
            )

        first = page(api, admin, "/catalog/products?q=pagemol&limit=25")
        second = page(api, admin, "/catalog/products?q=pagemol&limit=25&cursor=25")
        nothing = page(api, admin, "/catalog/products?q=%25")

        assert (len(first["items"]), first["total"]) == (25, 26)
        assert (len(second["items"]), second["total"]) == (1, 26)
        assert (nothing["items"], nothing["total"]) == ([], 0)

    def test_the_audit_log_pages_by_offset(self, api: Api, admin: dict[str, str]) -> None:
        pharmacy = confirmed_pharmacy(api)
        for _ in range(26):
            write(api, Actor.PHARMACY, "pharmacy.settings", "pharmacy", pharmacy, actor_id=pharmacy)

        first = page(api, admin, f"/audit?entity_id={pharmacy}&limit=25")
        second = page(api, admin, f"/audit?entity_id={pharmacy}&limit=25&offset=25")
        # The last ID seen, then rows skipped within what is left: the total ignores both.
        older = page(
            api,
            admin,
            f"/audit?entity_id={pharmacy}&limit=5&cursor={first['items'][0]['id']}&offset=20",
        )

        assert (len(first["items"]), first["total"]) == (25, 26)
        assert (len(second["items"]), second["total"]) == (1, 26)
        assert second["items"][0]["id"] < first["items"][-1]["id"]
        assert (len(older["items"]), older["total"]) == (5, 26)

    @pytest.mark.parametrize("offset", ["-1", str(10**40), "soon", "1000001"])
    def test_an_offset_is_bounded(self, api: Api, admin: dict[str, str], offset: str) -> None:
        answer = api.http().get(f"{ADMIN}/audit?offset={offset}", headers=admin)
        assert answer.status_code == 422

    def test_a_kind_is_a_family_of_codes(self, api: Api, admin: dict[str, str]) -> None:
        client = api.world.make.client()
        claim = api.world.make.claim(client_id=client)
        request = api.world.make.request(client_id=client)
        item = api.world.make.request_item(request)
        write(api, Actor.AGENT, "claim.create", "claim", claim, after={"kind": "REQUEST_ITEM"})
        write(api, Actor.SYSTEM, "request_item.state", "request_item", item)
        write(api, Actor.CLIENT, "request.create", "sourcing_request", request, actor_id=client)
        write(api, Actor.SYSTEM, "login.locked", "user", client)

        requests = page(api, admin, "/audit?kind=requests")
        accounts = page(api, admin, "/audit?kind=accounts")
        unknown = api.http().get(f"{ADMIN}/audit?kind=everything", headers=admin)

        assert sorted(row["action"] for row in requests["items"]) == [
            "claim.create",
            "request.create",
            "request_item.state",
        ]
        assert requests["total"] == 3
        assert [row["action"] for row in accounts["items"]] == ["login.locked"]
        assert unknown.status_code == 422


# --- The audit log in words --------------------------------------------------------------------


class TestWhoAndWhat:
    def test_an_admin_by_name_a_pharmacy_by_name_a_client_by_an_id(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        approver = admin_user(api, "Karim Approver")
        pharmacy = confirmed_pharmacy(api, name="Cedar Pharmacy")
        (owner,) = api.world.one("SELECT owner_user_id FROM pharmacies WHERE id = :id", id=pharmacy)
        client = api.world.make.client(person={"full_name": "Secret Client Name"})
        write(
            api,
            Actor.ADMIN,
            "pharmacy.approve",
            "pharmacy",
            pharmacy,
            actor_id=approver,
            before={"status": "PENDING"},
            after={"status": "APPROVED"},
        )
        # A pharmacy's password events name its login, not the pharmacy (auth.py).
        write(api, Actor.PHARMACY, "password.changed", "user", owner, actor_id=owner)
        write(
            api,
            Actor.CLIENT,
            "client.verified",
            "client",
            client,
            actor_id=client,
            before={"status": "UNVERIFIED"},
            after={"status": "ACTIVE"},
        )
        # An admin's ID on a client's row is never looked up as a name.
        write(api, Actor.CLIENT, "client.registered_again", "client", client, actor_id=client)

        # A case the client asked for holds no actor ID: the case's client is shown.
        case = escalation_of(api, client)
        write(
            api,
            Actor.CLIENT,
            "escalation.open",
            "escalation",
            case,
            after={"state": "OPEN", "reason": "client_asked_human"},
        )
        # An "admin" row whose ID is a client's (it never happens): no name is read for it.
        write(api, Actor.ADMIN, "pii.view", "client", client, actor_id=client)

        answer = api.http().get(f"{ADMIN}/audit", headers=admin)
        rows = {row["action"]: row for row in answer.json()["items"]}

        assert rows["escalation.open"]["who"] == {"kind": "client", "name": None, "id": str(client)}
        assert rows["escalation.open"]["subject"] == {"kind": "escalation", "id": str(case)}
        assert rows["escalation.open"]["code"] == "client_asked_human"
        assert rows["pii.view"]["who"] == {"kind": "admin", "name": None, "id": None}
        assert rows["pharmacy.approve"]["who"] == {
            "kind": "admin",
            "name": "Karim Approver",
            "id": None,
        }
        assert rows["pharmacy.approve"]["subject"] == {"kind": "pharmacy", "id": str(pharmacy)}
        assert (rows["pharmacy.approve"]["state_from"], rows["pharmacy.approve"]["state_to"]) == (
            "PENDING",
            "APPROVED",
        )
        assert rows["pharmacy.approve"]["known_action"] == "pharmacy.approve"
        assert rows["password.changed"]["who"] == {
            "kind": "pharmacy",
            "name": "Cedar Pharmacy",
            "id": str(pharmacy),
        }
        assert rows["password.changed"]["subject"] == {"kind": "pharmacy", "id": str(pharmacy)}
        assert rows["client.verified"]["who"] == {"kind": "client", "name": None, "id": str(client)}
        assert rows["client.verified"]["subject"] == {"kind": "client", "id": str(client)}
        assert "Secret Client Name" not in answer.text

    def test_what_an_event_is_about_leads_to_its_page(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        pharmacy = confirmed_pharmacy(api)
        client = api.world.make.client()
        box = api.world.make.item(pharmacy_id=pharmacy)
        order = api.world.make.order("RESERVED", client_id=client)
        request = api.world.make.request(client_id=client)
        item = api.world.make.request_item(request)
        er_request = api.world.make.early_release_request(client_id=client)
        ask = api.world.make.early_release_ask(pharmacy_id=pharmacy, er_request_id=er_request)
        unconfirmed = api.world.make.pharmacy("PENDING")
        write(api, Actor.PHARMACY, "inventory.edit", "inventory_item", box, actor_id=pharmacy)
        write(api, Actor.CLIENT, "order.cancel", "order", order, actor_id=client)
        write(api, Actor.SYSTEM, "request_item.state", "request_item", item)
        write(api, Actor.SYSTEM, "early_release.close", "early_release_request", er_request)
        write(
            api,
            Actor.PHARMACY,
            "early_release_ask.state",
            "early_release_ask",
            ask,
            actor_id=pharmacy,
        )
        write(api, Actor.ADMIN, "clock.advance", "app_state", None)
        write(
            api,
            Actor.CLIENT,
            "answer_report.new",
            "answer_report",
            uuid.uuid4(),
            actor_id=client,
            after={"state": "NEW", "reason": "unsafe"},
        )
        # Nobody has shown the email is theirs: the admin's page of it doesn't open.
        write(
            api,
            Actor.PHARMACY,
            "pharmacy.registered",
            "pharmacy",
            unconfirmed,
            actor_id=unconfirmed,
        )
        # A reservation deleted since: no page to go to.
        write(api, Actor.SYSTEM, "order.no_show", "order", uuid.uuid4())

        rows = {row["action"]: row for row in page(api, admin, "/audit")["items"]}

        assert rows["inventory.edit"]["subject"] == {"kind": "pharmacy", "id": str(pharmacy)}
        assert rows["early_release_ask.state"]["subject"] == {
            "kind": "pharmacy",
            "id": str(pharmacy),
        }
        for action in ("order.cancel", "request_item.state", "early_release.close"):
            assert rows[action]["subject"] == {"kind": "client", "id": str(client)}, action
        assert rows["clock.advance"]["subject"] == {"kind": "clock", "id": None}
        assert rows["answer_report.new"]["subject"]["kind"] == "reports"
        assert rows["answer_report.new"]["code"] == "unsafe"
        assert rows["pharmacy.registered"]["subject"] is None
        assert rows["order.no_show"]["subject"] is None
        # The system's own rows: no name, no ID.
        assert rows["order.no_show"]["who"] == {"kind": "system", "name": None, "id": None}

    def test_a_page_costs_one_query_per_kind_of_id(self, api: Api, admin: dict[str, str]) -> None:
        def fill(count: int) -> None:
            for _ in range(count):
                pharmacy = confirmed_pharmacy(api)
                order = api.world.make.order("RESERVED", pharmacy_id=pharmacy)
                approver = admin_user(api, "An Admin")
                write(api, Actor.ADMIN, "pharmacy.suspend", "pharmacy", pharmacy, actor_id=approver)
                write(api, Actor.PHARMACY, "order.picked_up", "order", order, actor_id=pharmacy)

        http = api.http()
        fill(2)
        with counted(api) as few:
            http.get(f"{ADMIN}/audit", headers=admin)
        fill(20)
        with counted(api) as many:
            http.get(f"{ADMIN}/audit", headers=admin)

        assert len(many) <= len(few)


def escalation_of(api: Api, client: uuid.UUID) -> uuid.UUID:
    """An open case of this client, as `services/escalations.py` writes one."""
    (case,) = api.world.one(
        "INSERT INTO escalations (client_id, reason, state, summary) "
        "VALUES (:client, 'client_asked_human', 'OPEN', 'Asked for a person.') RETURNING id",
        client=client,
    )
    return case  # type: ignore[no-any-return]


@contextmanager
def counted(api: Api) -> Iterator[list[str]]:
    """The SQL statements run on the test's connection while the block runs."""
    seen: list[str] = []

    def note(*args: Any) -> None:
        seen.append(str(args[2]))

    api.world.session.flush()
    event.listen(api.world.connection, "before_cursor_execute", note)
    try:
        yield seen
    finally:
        event.remove(api.world.connection, "before_cursor_execute", note)


class TestNoValueIsShown:
    def test_the_fields_are_named_never_their_values(self, api: Api, admin: dict[str, str]) -> None:
        """The rule of the log (CLAUDE.md §4): an admin reads which fields changed, never
        what they were or became: not a phone number, a price, a quantity, opening hours,
        a date, the clock's offset, nor a text a person typed into a stored state."""
        pharmacy = confirmed_pharmacy(api)
        client = api.world.make.client()
        box = api.world.make.item(pharmacy_id=pharmacy)
        # Long and odd enough never to be part of an ID or a time of the answer.
        hidden = {
            "+96171999888",
            "87654321",
            "87654329",
            "4321987",
            "3141592",
            "07:45",
            "2031-07-19",
            "98765432",
            "A typed rejection reason",
        }
        write(
            api,
            Actor.PHARMACY,
            "pharmacy.phone_changed",
            "pharmacy",
            pharmacy,
            actor_id=pharmacy,
            before={"phone": "+96171999888"},
            after={"fields": ["phone"]},
        )
        write(
            api,
            Actor.PHARMACY,
            "inventory.edit",
            "inventory_item",
            box,
            actor_id=pharmacy,
            before={
                "qty_on_hand": 4321987,
                "price_override_lbp": 87654321,
                "listing_control": "LIVE",
            },
            after={
                "qty_on_hand": 3141592,
                "price_override_lbp": 87654329,
                "listing_control": "PAUSED",
                "reserved_kept": False,
            },
        )
        write(
            api,
            Actor.PHARMACY,
            "pharmacy.settings",
            "pharmacy",
            pharmacy,
            actor_id=pharmacy,
            before={"pickup_days": 1, "hours": [[0, "07:45", "13:00"]]},
            after={"pickup_days": 2, "hours": [[0, "08:00", "13:00"]]},
        )
        write(
            api,
            Actor.SYSTEM,
            "client.pause",
            "client",
            client,
            before={"status": "ACTIVE", "paused_until": "None"},
            after={"status": "PAUSED", "paused_until": "2031-07-19T10:00:00+00:00"},
        )
        write(
            api,
            Actor.ADMIN,
            "clock.advance",
            "app_state",
            None,
            before={"offset_seconds": 0},
            after={"offset_seconds": 98765432},
        )
        write(
            api,
            Actor.PHARMACY,
            "pharmacy.resubmitted",
            "pharmacy",
            pharmacy,
            actor_id=pharmacy,
            before={"status": "REJECTED", "reason": "A typed rejection reason"},
            after={"status": "PENDING"},
        )
        write(
            api,
            Actor.ADMIN,
            "pharmacy.suspend",
            "pharmacy",
            pharmacy,
            before={"status": "APPROVED"},
            after={"status": "SUSPENDED", "offers_cancelled": 2, "asks_withdrawn": 1},
        )

        answer = api.http().get(f"{ADMIN}/audit", headers=admin)
        rows = {row["action"]: row for row in answer.json()["items"]}

        for value in hidden:
            assert value not in answer.text, value
        assert all("before" not in row and "after" not in row for row in rows.values())
        assert rows["pharmacy.phone_changed"]["changed"] == ["phone"]
        assert sorted(rows["inventory.edit"]["changed"]) == ["price_override_lbp", "qty_on_hand"]
        assert (rows["inventory.edit"]["state_from"], rows["inventory.edit"]["state_to"]) == (
            "LIVE",
            "PAUSED",
        )
        assert sorted(rows["pharmacy.settings"]["changed"]) == ["hours", "pickup_days"]
        assert rows["client.pause"]["changed"] == ["paused_until"]
        assert rows["clock.advance"]["changed"] == ["offset_seconds"]
        assert rows["pharmacy.resubmitted"]["state_from"] == "REJECTED"
        assert rows["pharmacy.resubmitted"]["code"] is None
        assert rows["pharmacy.suspend"]["counts"] == {"offers_cancelled": 2, "asks_withdrawn": 1}

    def test_a_state_that_is_not_a_code_is_not_shown(self, api: Api, admin: dict[str, str]) -> None:
        client = api.world.make.client()
        write(
            api,
            Actor.SYSTEM,
            "client.pause_ended",
            "client",
            client,
            before={"status": "call me on 70123456"},
            after={"status": "ACTIVE"},
        )
        write(
            api,
            Actor.AGENT,
            "escalation.open",
            "escalation",
            uuid.uuid4(),
            after={"state": "OPEN", "reason": "my number is 70123456"},
        )

        answer = api.http().get(f"{ADMIN}/audit", headers=admin)
        rows = {row["action"]: row for row in answer.json()["items"]}

        assert "70123456" not in answer.text
        assert rows["client.pause_ended"]["state_from"] is None
        assert rows["escalation.open"]["code"] is None


# --- Every code has a sentence -----------------------------------------------------------------


def _written_codes() -> tuple[set[str], set[str], list[str]]:
    """Every action an `audit.record` of the backend writes: literal codes, the starts of
    codes made by adding a word ("abuse_flag." + action), and what could not be read."""
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in SOURCE.rglob("*.py")}
    codes: set[str] = set()
    starts: set[str] = set()
    unread: list[str] = []
    # Functions that hand one of their parameters to `audit.record` as the action
    # (`orders.move`): (function name, the parameter's position).
    relays: dict[str, int] = {}

    def constants(tree: ast.Module) -> dict[str, str]:
        return {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

    for path, tree in trees.items():
        known = constants(tree)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            params = [arg.arg for arg in function.args.args]
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call) and ast.unparse(node.func).endswith("audit.record")
                ):
                    continue
                action = (
                    node.args[2]
                    if len(node.args) > 2
                    else next((k.value for k in node.keywords if k.arg == "action"), None)
                )
                if isinstance(action, ast.Constant) and isinstance(action.value, str):
                    codes.add(action.value)
                elif isinstance(action, ast.Name) and action.id in known:
                    codes.add(known[action.id])
                elif isinstance(action, ast.Name) and action.id in params:
                    relays[function.name] = params.index(action.id)
                elif (
                    isinstance(action, ast.BinOp)
                    and isinstance(action.left, ast.Constant)
                    and isinstance(action.left.value, str)
                ):
                    starts.add(action.left.value)
                else:
                    unread.append(f"{path.name}:{node.lineno}")
    # Every call was read, also one outside a function.
    every_call = sum(
        1
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("audit.record")
    )
    read_calls = sum(
        1
        for tree in trees.values()
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("audit.record")
    )
    if read_calls < every_call:
        unread.append("an audit.record outside a function")
    # What each relay is called with.
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func).rsplit(".", 1)[-1]
            if called not in relays:
                continue
            at = relays[called]
            given = node.args[at] if len(node.args) > at else None
            if isinstance(given, ast.Constant) and isinstance(given.value, str):
                codes.add(given.value)
            elif isinstance(given, ast.Name) and given.id == "action":
                continue  # the relay passing its own parameter on
            else:
                unread.append(f"{path.name}:{node.lineno}")
    return codes, starts, unread


def test_every_code_the_backend_writes_is_known() -> None:
    """A new `audit.record` with a code that is not in `AuditAction` fails here: add it
    there, and the website's typecheck and its test then ask for its sentence."""
    codes, starts, unread = _written_codes()
    known = {code.value for code in AuditAction}

    assert unread == [], "an audit action this test can't read: write it as a literal"
    assert codes - known == set(), "add these to domain/audit_actions.py"
    # "abuse_flag." + the admin's action (dismiss, or one of FlagAction's).
    assert starts == {"abuse_flag."}
    flag_actions = {"dismiss", *get_args(FlagAction.model_fields["action"].annotation)}
    assert {f"abuse_flag.{action}" for action in flag_actions} <= known
    # Nothing stays in the list that no code writes any more.
    assert known - codes - {f"abuse_flag.{action}" for action in flag_actions} == set()


def test_every_code_has_a_family_and_the_api_offers_each() -> None:
    assert [code for code in AuditAction if kind_of(code.value) is None] == []
    assert set(get_args(AuditKindName)) == set(KINDS)


def test_the_codes_are_in_the_api_description(api: Api) -> None:
    """The website reads them from here (`docs/openapi.json`): its sentences must cover
    each one."""
    described = api.app(assistant=False).openapi()
    listed = described["components"]["schemas"]["AuditAction"]["enum"]
    assert sorted(listed) == sorted(code.value for code in AuditAction)
    row = described["components"]["schemas"]["AuditRow"]["properties"]
    assert "before" not in row
    assert "after" not in row


# --- Health: each client's limits and the budget for everyone ---------------------------------


class TestHealthLimits:
    def test_the_page_reads_the_rules_numbers_and_who_reached_them(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        heavy = api.world.make.client()
        light = api.world.make.client()
        for client, tokens in ((heavy, DAILY_TOKEN_BUDGET_PER_CLIENT), (light, 1000)):
            conversation = api.world.make.conversation(client_id=client)
            api.world.make.agent_run(
                conversation_id=conversation,
                tokens_in=tokens,
                tokens_out=0,
                started_at=api.world.clock.now(),
            )
        # Yesterday's tokens count for yesterday only.
        old = api.world.make.client()
        api.world.make.agent_run(
            conversation_id=api.world.make.conversation(client_id=old),
            tokens_in=DAILY_TOKEN_BUDGET_PER_CLIENT,
            started_at=api.world.clock.now() - timedelta(days=1),
        )
        talker = api.world.make.client()
        chat = api.world.make.conversation(client_id=talker)
        api.world.session.add_all(
            ChatMessage(
                conversation_id=chat, seq=seq, author="client", kind="text", text_redacted="hi"
            )
            for seq in range(1, CHAT_MESSAGES_PER_DAY + 1)
        )

        agent = page(api, admin, "/health?days=1")["agent"]

        assert agent["messages_per_day_per_client"] == CHAT_MESSAGES_PER_DAY
        assert agent["tokens_per_day_per_client"] == DAILY_TOKEN_BUDGET_PER_CLIENT
        assert agent["clients_at_token_limit_today"] == 1
        assert agent["clients_at_message_limit_today"] == 1
        assert agent["day_budget_usd"] == pytest.approx(
            agent["month_budget_usd"] * agent["day_share_percent"] / 100
        )
        assert agent["day_spend_usd"] == 0
        # No dollar figure for a client's own limit: it is counted in tokens.
        assert not [key for key in agent if "client" in key and "usd" in key]
