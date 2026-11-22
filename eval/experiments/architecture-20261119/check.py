"""Free commands only, isolated synthetic settings and append-only command evidence."""
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
name, *command = sys.argv[1:]
if '/' in name:
    raise SystemExit('invalid name')
env = {k: v for k, v in os.environ.items()
       if not any(s in k for s in ('API_KEY', 'LANGFUSE', 'DATABASE_', 'LLM_', 'EVAL_',
                                   'DAWALINK_ARCHITECTURE'))}
for line in (ROOT / 'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
    key, value = line.split('=', 1)
    env[key] = value
env['PATH'] = str(ROOT / 'backend/.venv/bin') + ':' + env['PATH']
start = time.time()
with (HERE / 'evidence' / f'{name}.txt').open('x') as out:
    out.write(f'command: {json.dumps(command)}\n')
    out.flush()
    result = subprocess.run(command, cwd=ROOT / 'backend', env=env, stdout=out,
                            stderr=subprocess.STDOUT)
with (HERE / 'evidence' / f'{name}.command.json').open('x') as out:
    json.dump({'argv': command, 'cwd': 'backend', 'exit_code': result.returncode,
               'seconds': round(time.time() - start, 3)}, out, indent=2)
print(name, result.returncode)
sys.exit(result.returncode)
