"""Keep a multi-pharmacy plan's displayed cards consistent with its scope."""

import re
from collections.abc import Sequence
from typing import Any

_PARTIAL = re.compile(r"\b(?:partial|incomplete|na2es|na2sin|juz2i)\b|جزئي|ناقص", re.I)


def incomplete_plan_cards(text: str, payloads: Sequence[dict[str, Any]]) -> bool:
    """A displayed plan needs every group, or an explicit partial-plan explanation.

    Provenance is written by the proposal tool. Older cards without provenance
    remain review work; sharing a listing with another plan is not provenance.
    """
    groups: dict[str, set[int]] = {}
    totals: dict[str, int] = {}
    for payload in payloads:
        plan_id = payload.get("plan_id")
        index, count = payload.get("plan_group_index"), payload.get("plan_group_count")
        if isinstance(plan_id, str) and isinstance(index, int) and isinstance(count, int):
            groups.setdefault(plan_id, set()).add(index)
            totals[plan_id] = count
    return not _PARTIAL.search(text) and any(
        indexes != set(range(totals[plan_id])) for plan_id, indexes in groups.items()
    )
