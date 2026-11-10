"""The worker's sign of life: a file touched after every clock-check pass (docs/12 §6).

The container's health check reads it, so a worker that is stuck (not only one that crashed)
gets restarted (FX-13). This is real time on purpose: it's about the process, not the business.
"""

import time
from pathlib import Path

from dawalink.domain.numbers import CLOCK_CHECK_LATE_AFTER_S


def beat(heartbeat_file: Path) -> None:
    heartbeat_file.write_text(str(time.time()), encoding="utf-8")


def is_alive(
    heartbeat_file: Path,
    *,
    now: float | None = None,
    max_age_s: float = CLOCK_CHECK_LATE_AFTER_S,
) -> bool:
    try:
        last_beat = heartbeat_file.stat().st_mtime
    except FileNotFoundError:
        return False
    current = time.time() if now is None else now
    return current - last_beat <= max_age_s
