"""Suite E6, real-world constraints (docs/08 E6): python -m dawalink.sim.sweep \\
    --contender rules --seeds 1

Nobody measured how pharmacies and clients really behave: every number of `sim/params.py`
is an assumption. This plays the same day again with each assumption at its low and at its
high value (docs/08 §2.4), one at a time, and shows how far the result moves. A conclusion
that holds across the range doesn't depend on our guess; one that flips does, and the
report says so.

Free for the search baseline and the no-AI policy. Each run is saved in `eval/results/`,
and the table in `eval/results/<date>_sweep_<contender>.json`.
"""

import argparse
import json
from datetime import date
from typing import Any

from dawalink.config import load_settings
from dawalink.observability.logging import configure_logging
from dawalink.sim import run, save
from dawalink.sim.params import Params

# Each assumption's low and high value (docs/08 §2.4). The base value is in `Params`.
RANGES: dict[str, tuple[float, float]] = {
    "not_available": (0.0, 0.30),
    "answers_ask": (0.20, 0.80),
    "accepts_ask": (0.25, 0.75),
    "new_listings_per_pharmacy": (3.0, 12.0),
    "early_release_share": (0.125, 0.50),
    "taps_card": (0.70, 1.00),
    "accepts_offer": (0.60, 1.00),
    "other_brand_reserve": (0.20, 0.60),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--contender", choices=sorted(run.CONTENDERS), required=True)
    parser.add_argument("--seeds", default="1", help="'1', '1-5' or '1,3,4'")
    parser.add_argument("--only", nargs="*", choices=sorted(RANGES), help="some assumptions only")
    arguments = parser.parse_args()
    configure_logging("WARNING")
    settings = load_settings()
    today = date.today()

    rows: list[dict[str, Any]] = []
    plays: list[tuple[str, float | None]] = [("base", None)]
    plays += [(name, value) for name in (arguments.only or RANGES) for value in RANGES[name]]
    for seed in run._seeds(arguments.seeds):
        for name, value in plays:
            params = Params() if value is None else Params().but(**{name: value})
            folder = save.folder_for(arguments.contender, None, seed, params, on=today)
            if value is not None:
                folder = folder.with_name(f"{folder.name}_{name}-{value}")
            played = run.one(settings, arguments.contender, seed, params, folder=folder)
            row = {
                "seed": seed,
                "assumption": name,
                "value": value if value is not None else "base",
                "units_wanted": played.summary["units_wanted"],
                "units_secured": played.summary["units_secured"],
                "needs_fulfilled": played.summary["needs_fulfilled"],
                "no_shows": played.summary["no_shows"],
                "seconds": played.seconds,
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
    table = save.RESULTS / f"{today.isoformat()}_sweep_{arguments.contender}.json"
    table.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print("saved in", table)


if __name__ == "__main__":
    main()
