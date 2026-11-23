"""Accepted-data free gates in the isolated evaluation environment; no model calls."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for line in (ROOT / 'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
    if line and not line.startswith('#'):
        key, value = line.split('=', 1)
        os.environ[key] = value
for key in ('ANTHROPIC_API_KEY', 'ORS_API_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_PUBLIC_KEY'):
    os.environ.pop(key, None)

from dawalink.evals import before_commit
from dawalink.evals.dataset_selection import select_dataset

before_commit.DATASETS, before_commit.CASES = select_dataset('expanded')
sys.argv = [__file__]
before_commit.main()
