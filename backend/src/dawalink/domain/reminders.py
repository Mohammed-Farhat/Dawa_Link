"""When a client is reminded of a reservation (docs/04 N-8, the owner, 2026-11-18).

Every 12 hours while it is reserved, plus once 2 hours before the pickup deadline, and
never in the first hour after reserving. Before, the one reminder came 4 hours before the
deadline: a reservation made for the same evening got it a second after it was made.

Plain rules, no database. The clock check acts on the next moment stored on the order.
"""

from datetime import datetime

from dawalink.domain.numbers import (
    PICKUP_REMINDER_EVERY,
    PICKUP_REMINDER_LAST_BEFORE,
    PICKUP_REMINDER_QUIET,
)


def reminder_times(reserved_at: datetime, deadline: datetime) -> list[datetime]:
    """Every moment a reservation's client is reminded, in order.

    - one every 12 hours after reserving, as long as it is not within an hour of the last
      one (two reminders minutes apart would be noise);
    - the last one 2 hours before the deadline, unless that is within the first hour
      after reserving.
    """
    last = deadline - PICKUP_REMINDER_LAST_BEFORE
    times = []
    moment = reserved_at + PICKUP_REMINDER_EVERY
    while moment <= last - PICKUP_REMINDER_QUIET:
        times.append(moment)
        moment += PICKUP_REMINDER_EVERY
    if last >= reserved_at + PICKUP_REMINDER_QUIET:
        times.append(last)
    return times


def next_reminder(reserved_at: datetime, deadline: datetime, after: datetime) -> datetime | None:
    """The first reminder later than `after`, or None when none is left.

    `after` is the moment of reserving for a new reservation, and "now" once a reminder
    was sent: a worker that was down for a day sends one reminder, not all it missed.
    """
    return next(
        (moment for moment in reminder_times(reserved_at, deadline) if moment > after), None
    )
