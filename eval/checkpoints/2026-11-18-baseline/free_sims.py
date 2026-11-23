"""Paired free smoke simulations in exclusive output folders; never a paid contender."""
from pathlib import Path
from dawalink.config import load_settings
from dawalink.sim.run import one
from dawalink.sim.params import Params
root=Path(__file__).resolve().parent/'evidence'/'simulations'
root.mkdir(exist_ok=False)
for contender in ('search','rules','rules_asking'):
    result=one(load_settings(), contender, 1, Params(requests=10), folder=root/contender)
    print(contender, result.summary, flush=True)
