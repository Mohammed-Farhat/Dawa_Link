"""Use the existing sequential orchestrator under the approved stage limits."""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
from revised_paid_20261120e import apply_policy

apply_policy()
sys.argv = [str(HERE / 'execute_screening.py'), '--execution-id', 'revised-20261120f',
            '--plan', 'revised-screening-commands-20261120e.json', '--start-step', '5']
runpy.run_path(str(HERE / 'execute_screening.py'), run_name='__main__')
