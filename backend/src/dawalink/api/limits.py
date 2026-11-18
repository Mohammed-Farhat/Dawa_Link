"""Per-minute limits, counted in memory (docs/06 §4, docs/10 RR-8).

One API process serves everyone, so a dictionary is enough. The counters start again when
the process restarts: the limits that must survive that (failed logins, sign-ups, the
daily chat count, the budgets) are counted in the database instead.
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Hashable


class Limiter:
    """At most `limit` events per `window_s` seconds for each key."""

    def __init__(
        self, limit: int, window_s: float, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._monotonic = monotonic
        self._events: dict[Hashable, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def wait_s(self, key: Hashable) -> int:
        """Counts one event for `key`. Returns 0 if it is allowed, or the seconds to wait."""
        now = self._monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self._window_s:
                events.popleft()
            if len(events) >= self._limit:
                return max(1, int(events[0] + self._window_s - now) + 1)
            events.append(now)
            if len(self._events) > 10_000:
                self._forget_idle(now)
            return 0

    def full(self, key: Hashable) -> bool:
        """Whether one more event for `key` would be refused, without counting one."""
        now = self._monotonic()
        with self._lock:
            events = self._events.get(key, ())
            return sum(1 for at in events if at > now - self._window_s) >= self._limit

    def _forget_idle(self, now: float) -> None:
        for key in [k for k, v in self._events.items() if not v or v[-1] <= now - self._window_s]:
            del self._events[key]
