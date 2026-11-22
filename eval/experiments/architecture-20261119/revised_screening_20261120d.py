"""Use the existing sequential orchestrator under the approved stage limits."""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
from revised_paid_20261120c import apply_policy

apply_policy()
sys.argv = [str(HERE / 'execute_screening.py'), '--execution-id', 'revised-20261120d',
            '--plan', 'revised-screening-commands-20261120d.json']
runpy.run_path(str(HERE / 'execute_screening.py'), run_name='__main__')
