"""Run the existing experiment entry point with isolated settings and one private key.

No key is written to evidence or passed as a command argument. The experiment runner
owns run IDs, source archives, raw outcomes, completion manifests and the shared ledger.
"""

import os
import sys
from pathlib import Path

from dawalink.evals.experiment import main

ROOT = Path(__file__).resolve().parents[3]
if (Path(__file__).resolve().parent / "STOP_SCREENING").exists() and "comparison" in sys.argv:
    raise SystemExit("Screening stopped before setup: smoke review requires context correction")
for key in list(os.environ):
    if any(s in key for s in ('API_KEY', 'LANGFUSE', 'DATABASE_', 'LLM_', 'EVAL_',
                              'DAWALINK_ARCHITECTURE')):
        del os.environ[key]
for line in (ROOT / 'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
    key, value = line.split('=', 1)
    os.environ[key] = value
for line in (ROOT / '.env').read_text().splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        os.environ['ANTHROPIC_API_KEY'] = line.split('=', 1)[1].strip().strip('"\'')
        break
else:
    raise SystemExit('Evaluation key missing')
os.environ['EVAL_DATASET'] = 'expanded'
main()
