"""Counting a list for numbered pages ("Page 2 of 7 · 134 in all").

A list's `total` is the number of rows its filters match. It is counted from the very
statement that reads the page, so the two can never disagree about what a filter means.
"""

from typing import Any

from sqlalchemy import Select, func, select

from dawalink.services.context import Tx


def count_rows(tx: Tx, statement: Select[Any]) -> int:
    """How many rows `statement` gives, whatever page of them is asked for: its order,
    offset and limit are taken off before counting. A join that gives a row twice counts
    it twice, as the list would show it twice.

    Give it the statement before `.offset()` and `.limit()`, or after: the same number.
    """
    rows = statement.order_by(None).offset(None).limit(None).subquery()
    return int(tx.session.execute(select(func.count()).select_from(rows)).scalar_one())
