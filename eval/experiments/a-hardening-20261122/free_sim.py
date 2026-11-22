"""One paired free baseline contender; unique evidence via the common experiment runner."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for line in (ROOT/'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
    if line and not line.startswith('#'):
        key, value = line.split('=',1)
        os.environ[key] = value
for key in ('ANTHROPIC_API_KEY','ORS_API_KEY','LANGFUSE_SECRET_KEY','LANGFUSE_PUBLIC_KEY'):
    os.environ.pop(key,None)
os.environ['EVAL_DATASET'] = 'expanded'
if '--contender' not in sys.argv or sys.argv[sys.argv.index('--contender')+1] not in ('search','rules','rules_asking'):
    raise SystemExit('Only free baseline contenders allowed')
from dawalink.evals.experiment import main
sys.argv.insert(1,'simulation')
main()
