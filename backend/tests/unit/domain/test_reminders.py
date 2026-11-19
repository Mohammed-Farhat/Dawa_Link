"""When a reservation's client is reminded (docs/04 N-8; the owner, 2026-11-18): every
12 hours, once 2 hours before the deadline, and never in the first hour."""

from datetime import UTC, datetime, timedelta

from dawalink.domain.reminders import next_reminder, reminder_times

RESERVED = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)


def hours(count: float) -> timedelta:
    return timedelta(hours=count)


def after(times: list[datetime]) -> list[float]:
    """How many hours after reserving each reminder comes."""
    return [(moment - RESERVED) / hours(1) for moment in times]


def test_a_reservation_for_the_same_evening_gets_one_reminder_two_hours_before() -> None:
    """Reserved at 18:00 for a deadline at 22:00, Beirut time: one reminder at 20:00. It
    used to come a second after reserving, because the deadline was under 4 hours away."""
    assert after(reminder_times(RESERVED, RESERVED + hours(4))) == [2]


def test_a_reservation_made_just_before_closing_gets_none() -> None:
    """Under 3 hours to the deadline: "2 hours before" would fall in the first hour."""
    assert reminder_times(RESERVED, RESERVED + hours(2.5)) == []
    assert after(reminder_times(RESERVED, RESERVED + hours(3))) == [1]


def test_a_reservation_for_three_days_is_reminded_every_12_hours_then_before_closing() -> None:
    assert after(reminder_times(RESERVED, RESERVED + hours(52))) == [12, 24, 36, 48, 50]


def test_two_reminders_are_never_within_an_hour_of_each_other() -> None:
    """The 12-hour mark that falls 30 minutes before the last one is left out."""
    assert after(reminder_times(RESERVED, RESERVED + hours(13.5))) == [11.5]
    assert after(reminder_times(RESERVED, RESERVED + hours(15))) == [12, 13]


def test_the_next_one_is_the_first_later_than_a_moment() -> None:
    deadline = RESERVED + hours(52)

    assert next_reminder(RESERVED, deadline, after=RESERVED) == RESERVED + hours(12)
    assert next_reminder(RESERVED, deadline, after=RESERVED + hours(12)) == RESERVED + hours(24)
    # A worker that was down for a day sends one reminder, then the next in its turn.
    assert next_reminder(RESERVED, deadline, after=RESERVED + hours(40)) == RESERVED + hours(48)
    assert next_reminder(RESERVED, deadline, after=RESERVED + hours(50)) is None
