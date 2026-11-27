from datetime import date, timedelta

import pytest

from dawalink.agent.guards.pickup import explicit_pickup_day


@pytest.mark.parametrize(
    ("text", "offset"),
    [
        ("I will pick it up today", 0),
        ("Tomorrow please", 1),
        ("The day after tomorrow", 2),
        ("baddi ba3d bukra", 2),
        ("ba3dbukra", 2),
        ("bukra la2 lyom", 0),
        ("tomorrow, actually today", 0),
        ("بدي بعد بكرا", 2),
        ("بكرا لا اليوم", 0),
        ("If tomorrow works, tell me", None),
        ("Can I pick it up today?", None),
        ("not tomorrow", None),
        ("No pickup tomorrow", None),
        ("The box expires tomorrow", None),
        ("My appointment is tomorrow", None),
        ("I need it by tomorrow", None),
        ("today or tomorrow", None),
        ("بدي اليوم أو بكرا", None),
        ("tomorrow, actually maybe today", None),
        ("Concor 5 one box", None),
    ],
)
def test_explicit_pickup_date(text: str, offset: int | None) -> None:
    today = date(2026, 11, 16)
    expected = None if offset is None else today + timedelta(days=offset)
    assert explicit_pickup_day(text, today) == expected


def test_relative_day_uses_beirut_turn_date_across_month_boundary() -> None:
    assert explicit_pickup_day("day after tomorrow", date(2026, 12, 31)) == date(2027, 1, 2)


@pytest.mark.parametrize(
    ("text", "offset"),
    [
        ("today instead of tomorrow", 0),
        ("Tomorrow instead of today, please", 1),
        ("I can pick it up today instead of tomorrow", 0),
        ("No, I can collect today instead of tomorrow", 0),
        ("day after tomorrow instead of tomorrow", 2),
        ("لا، بقدر اجي اليوم بدل بكرا", 0),
        ("بقدر أجي بكرا بدل اليوم", 1),
        ("اليوم بدل بكرا", 0),
        ("بدي اليوم بدلاً من بكرا", 0),
        ("maybe today instead of tomorrow", None),
        ("If I can collect today instead of tomorrow, let me know", None),
        ("Can I collect today instead of tomorrow?", None),
        ("today instead of tomorrow?", None),
        ("not today instead of tomorrow", None),
        ("I cannot collect today instead of tomorrow", None),
        ("ممكن اجي اليوم بدل بكرا؟", None),
        ("ما بقدر اجي اليوم بدل بكرا", None),
        ("لا بقدر اجي اليوم بدل بكرا", None),
        ("أنا لا بقدر اجي اليوم بدل بكرا", None),
        ("بدي اليوم أو بكرا", None),
        ("today instead of tomorrow or day after tomorrow", None),
        ("The box expires today instead of tomorrow", None),
        ("My appointment is today instead of tomorrow", None),
    ],
)
def test_explicit_replacement_is_directional_and_requires_a_firm_assertion(
    text: str, offset: int | None
) -> None:
    today = date(2026, 12, 31)
    expected = None if offset is None else today + timedelta(days=offset)
    assert explicit_pickup_day(text, today) == expected
