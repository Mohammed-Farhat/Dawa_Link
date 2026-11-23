"""Numbered pages: the count behind "Page 2 of 7 · 134 in all", and the answer's shape."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from dawalink.api.schemas.common import CountedPage, next_cursor
from dawalink.db.models import AuditEvent
from dawalink.domain.state_machine import Actor
from dawalink.services import audit
from dawalink.services.paging import count_rows
from tests.services.conftest import World

# Invented actions, so that no event written by a builder is counted.
KIND = "pagingtest."


def _events(world: World, count: int, action: str) -> None:
    tx = world.tx()
    for _ in range(count):
        audit.record(tx, Actor.SYSTEM, action, "pagingtest", None)
    tx.session.flush()


class TestCountRows:
    def test_counts_what_the_filters_match_whatever_the_page(self, world: World) -> None:
        _events(world, 27, f"{KIND}one")
        _events(world, 4, f"{KIND}two")
        tx = world.tx()
        mine = select(AuditEvent).where(AuditEvent.action.startswith(KIND))
        only_one = mine.where(AuditEvent.action == f"{KIND}one")

        assert count_rows(tx, mine) == 31
        assert count_rows(tx, only_one) == 27
        # The page asked for changes nothing: its order, offset and limit are taken off.
        second_page = only_one.order_by(AuditEvent.id.desc()).offset(25).limit(26)
        assert count_rows(tx, second_page) == 27
        assert len(tx.session.execute(second_page).scalars().all()) == 2
        # A page past the end is empty, and the total is still there.
        past_the_end = only_one.offset(1000).limit(25)
        assert tx.session.execute(past_the_end).scalars().all() == []
        assert count_rows(tx, past_the_end) == 27

    def test_an_empty_list_counts_zero(self, world: World) -> None:
        nothing = select(AuditEvent).where(AuditEvent.action == f"{KIND}never")
        assert count_rows(world.tx(), nothing) == 0


class TestTheAnswer:
    def test_a_list_answer_keeps_its_name_and_fields_and_gains_a_total(self) -> None:
        class Rows(CountedPage):
            items: list[int]
            next_cursor: str | None

        page = Rows(items=[1, 2], next_cursor="25", total=134)
        assert page.model_dump() == {"total": 134, "items": [1, 2], "next_cursor": "25"}
        assert Rows.model_json_schema()["title"] == "Rows"
        assert "total" in Rows.model_json_schema()["required"]
        with pytest.raises(ValidationError):
            Rows(items=[], next_cursor=None, total=-1)

    def test_the_next_page_starts_after_this_one_when_a_row_more_came_back(self) -> None:
        assert next_cursor(0, 25, 26) == "25"
        assert next_cursor(25, 25, 26) == "50"
        assert next_cursor(25, 25, 25) is None
        assert next_cursor(0, 25, 0) is None
