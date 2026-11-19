"""Create a command index and integrity snapshot without changing run evidence."""
import hashlib
import json
import sqlite3
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EVIDENCE = HERE/'evidence'
EXPERIMENT = ROOT/'eval/experiments/architecture-20261118'
lines = ['# Executed command index', '',
         'Run from repository root: `python3 eval/checkpoints/2026-11-18-readiness/check.py NEW-NAME backend|frontend COMMAND...`.', '',
         'The wrapper sets synthetic isolated settings, strips inherited service/database keys, '
         'and refuses existing evidence names. Paid commands additionally use paid.py, which reads '
         'only the ignored Anthropic key. Do not rerun paid commands until billing holds are reconciled.', '',
         '| Evidence | Working directory | Exact argument vector | Exit | Seconds |',
         '|---|---|---|---:|---:|']
for path in sorted(EVIDENCE.glob('*.json')):
    data = json.loads(path.read_text())
    if isinstance(data, dict) and 'command' in data and 'exit_code' in data:
        command = json.dumps(data['command'], ensure_ascii=False).replace('|', '&#124;')
        lines.append(f"| [{path.stem}](evidence/{path.stem}.txt) | {data['cwd']} | `{command}` | {data['exit_code']} | {data['seconds']} |")
lines += ['', 'A zero shell exit for a paid runner does not mean a complete evaluation. '
          'The four larger paid runs have completion.json status incomplete.', '',
          'Earlier failed attempts without wrapper metadata are retained in scorers-first.txt, '
          'types-first.txt, types-r2.txt, collection.txt and partial-review.txt. The first partial '
          'review produced its JSON correctly but collided with the wrapper metadata filename; '
          'partial-review-r2 uses separate output and metadata names. Nothing was overwritten.']
with (HERE/'CHECKS.md').open('x') as stream:
    stream.write('\n'.join(lines)+'\n')

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

handoff = ROOT/'DawaLink_Roadmap_and_Database_Handoff.md'
expected = (ROOT/'eval/checkpoints/2026-11-18-baseline/evidence/handoff.sha256').read_text().split()[0]
assert hashlib.sha256(handoff.read_bytes()).hexdigest() == expected
assert not git('diff', '--', 'backend/src/dawalink/agent', 'frontend/src', 'eval/results', 'eval/baseline.json')
subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
secret = None
for line in (ROOT/'.env').read_text().splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        secret = line.split('=', 1)[1].strip().strip('\"\'')
assert secret
leaks = [str(p.relative_to(ROOT)) for base in (ROOT/'eval/checkpoints', EXPERIMENT)
         for p in base.rglob('*') if p.is_file() and secret.encode() in p.read_bytes()]
assert not leaks, 'A credential appeared in an output file'
assert stat.S_IMODE((ROOT/'.env').stat().st_mode) == 0o600
snapshot = EVIDENCE/'ledger-snapshot.sqlite'
assert not snapshot.exists()
with sqlite3.connect(EXPERIMENT/'budget.sqlite') as source:
    with sqlite3.connect(snapshot) as destination:
        source.backup(destination)
integrity = {'reference_commit': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
             'handoff_sha256': expected, 'agent_frontend_historical_results_unchanged': True,
             'diff_whitespace_check': 'passed', 'credential_output_scan': 'passed',
             'root_env_mode': '0600', 'run_files_sha256': {
                 str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((EXPERIMENT/'runs').rglob('*')) if p.is_file()},
             'ledger_snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()}
with (EVIDENCE/'integrity.json').open('x') as stream:
    json.dump(integrity, stream, indent=2)
print('Command index, ledger snapshot, run hashes, original-agent and handoff checks saved.')
