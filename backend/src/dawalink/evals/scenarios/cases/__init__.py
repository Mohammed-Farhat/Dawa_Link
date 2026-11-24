"""The scenarios, one module per family. Each module has a list named `SCENARIOS`.

A new module in this folder is found by itself: nothing here needs to change.
"""

import importlib
import pkgutil

from dawalink.evals.scenarios.scenario import Scenario


def all_scenarios() -> list[Scenario]:
    """Every scenario, in the order of the modules' names, then as each module lists them."""
    found: list[Scenario] = []
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if module.name.startswith("_"):
            continue
        loaded = importlib.import_module(f"{__name__}.{module.name}")
        found += list(getattr(loaded, "SCENARIOS", ()))
    ids = [scenario.id for scenario in found]
    twice = sorted({one for one in ids if ids.count(one) > 1})
    if twice:
        raise ValueError(f"Two scenarios share an id: {', '.join(twice)}")
    return found
