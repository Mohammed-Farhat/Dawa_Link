"""The statistics of the evaluation (docs/08 §4): a share with its 95% interval, and the
difference between two contenders on the same clients.

Both are bootstraps: the cases are drawn again with replacement many times, and the
interval is where 95% of the results fall. The draws come from a fixed seed, so a report
made twice from the same runs prints the same numbers.

A comparison is **paired**: two contenders of a seed serve the same clients on the same
day, so the same clients are drawn for both, and the luck of the draw cancels out.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

DRAWS = 2000
SEED = 2026


@dataclass(frozen=True)
class Estimate:
    value: float
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.value:.1%} ({self.low:.1%} to {self.high:.1%})"

    @property
    def excludes_zero(self) -> bool:
        """For a difference: the whole interval is on one side of zero."""
        return self.low > 0 or self.high < 0


def _interval(results: list[float]) -> tuple[float, float]:
    results.sort()
    return results[int(0.025 * len(results))], results[
        min(len(results) - 1, int(0.975 * len(results)))
    ]


def _share(got: Sequence[float], of: Sequence[float], picks: Sequence[int]) -> float:
    total = sum(of[i] for i in picks)
    return sum(got[i] for i in picks) / total if total else 0.0


def share(got: Sequence[float], of: Sequence[float], *, draws: int = DRAWS) -> Estimate:
    """`sum(got) / sum(of)` over the cases, with its 95% interval. For "units secured of
    units wanted", a case is a client's need; for a yes/no check, `of` is 1 for each."""
    if len(got) != len(of) or not got:
        raise ValueError("one number per case, and at least one case")
    numbers = random.Random(SEED)
    everyone = range(len(got))
    results = [_share(got, of, numbers.choices(everyone, k=len(got))) for _ in range(draws)]
    return Estimate(_share(got, of, everyone), *_interval(results))


def difference(
    first: Sequence[float], second: Sequence[float], of: Sequence[float], *, draws: int = DRAWS
) -> Estimate:
    """The share of `first` minus the share of `second`, on the same cases, with its 95%
    interval. The interval excluding zero is what "better" means in the report."""
    if not (len(first) == len(second) == len(of)) or not of:
        raise ValueError("the two contenders must have served the same cases")
    numbers = random.Random(SEED)
    everyone = range(len(of))
    results = []
    for _ in range(draws):
        picks = numbers.choices(everyone, k=len(of))
        results.append(_share(first, of, picks) - _share(second, of, picks))
    value = _share(first, of, everyone) - _share(second, of, everyone)
    return Estimate(value, *_interval(results))


def clustered_difference(
    first: Sequence[float],
    second: Sequence[float],
    of: Sequence[float],
    seeds: Sequence[int],
    *,
    draws: int = DRAWS,
) -> Estimate:
    """Paired bootstrap of whole seeds, preserving within-world competition."""
    if not (len(first) == len(second) == len(of) == len(seeds)) or not of:
        raise ValueError("the two contenders must have served the same seeded cases")
    groups = {seed: [i for i, value in enumerate(seeds) if value == seed] for seed in seeds}
    numbers = random.Random(SEED)
    results = []
    for _ in range(draws):
        picks = [i for seed in numbers.choices(sorted(groups), k=len(groups)) for i in groups[seed]]
        results.append(_share(first, of, picks) - _share(second, of, picks))
    everyone = range(len(of))
    return Estimate(_share(first, of, everyone) - _share(second, of, everyone), *_interval(results))
