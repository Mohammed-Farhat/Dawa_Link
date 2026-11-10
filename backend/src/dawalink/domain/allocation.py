"""Who gets scarce stock first: first come, first served (docs/04 R-PRI, ADR-003, INV-17).

Plain code, with no judgment in it. Nobody can change the order: not the agent, not an admin.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from dawalink.domain.clock import beirut


@dataclass(frozen=True)
class WaitingClaim:
    """A claim that could take this stock.

    The service has already kept only claims for this medicine, within reach, whose box fits
    and whose price limit allows it. `skip_reason` says why this claim must sit this round out:
    its client is paused or at a limit, it already holds a matching offer, or it declined
    this item recently (R-PRI3, R-W3, O10).
    """

    claim_id: str
    created_at: datetime
    qty_missing: int
    skip_reason: str | None = None


@dataclass(frozen=True)
class Hold:
    claim_id: str
    units: int
    reason: str


@dataclass(frozen=True)
class Skipped:
    claim_id: str
    reason: str


@dataclass(frozen=True)
class Allocation:
    holds: tuple[Hold, ...]
    skipped: tuple[Skipped, ...]
    units_left: int


def allocate(units_available: int, claims: Sequence[WaitingClaim]) -> Allocation:
    """Hand the available units to the claims that have waited longest.

    The earliest claim gets its missing units, then the next, while stock remains. Ties on
    time are broken by the claim's ID, so the same input always gives the same result.
    """
    if units_available < 0:
        raise ValueError("Available units can't be negative.")
    holds: list[Hold] = []
    skipped: list[Skipped] = []
    left = units_available
    for claim in sorted(claims, key=lambda c: (c.created_at, c.claim_id)):
        if left == 0:
            break
        if claim.skip_reason is not None:
            skipped.append(Skipped(claim.claim_id, claim.skip_reason))
            continue
        if claim.qty_missing < 1:
            continue
        units = min(claim.qty_missing, left)
        left -= units
        since = beirut(claim.created_at).strftime("%H:%M")
        holds.append(
            Hold(claim.claim_id, units, f"first come, first served: waiting since {since}")
        )
    return Allocation(tuple(holds), tuple(skipped), left)
