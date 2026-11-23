"""Run one free command with isolated settings and exclusive evidence files."""
import json, os, pathlib, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
name, directory, *command = sys.argv[1:]
if directory not in ('backend', 'frontend') or '/' in name:
    raise SystemExit('invalid evidence name or working directory')
env = {k:v for k,v in os.environ.items() if not any(s in k for s in ('API_KEY', 'LANGFUSE', 'DATABASE_', 'LLM_'))}
for line in (HERE/'local.env').read_text().splitlines():
    key, value = line.split('=', 1)
    env[key] = value
env['PATH'] = str(ROOT/'backend/.venv/bin') + ':/Users/ajkanaan/.nvm/versions/node/v24.21.0/bin:' + env['PATH']
start = time.time()
with (HERE/'evidence'/f'{name}.txt').open('x') as out:
    out.write(f'cwd: {directory}\ncommand: {json.dumps(command)}\n'); out.flush()
    result = subprocess.run(command, cwd=ROOT/directory, env=env, stdout=out, stderr=subprocess.STDOUT)
with (HERE/'evidence'/f'{name}.json').open('x') as out:
    json.dump({'command':command,'cwd':directory,'exit_code':result.returncode,'seconds':round(time.time()-start,3)},out,indent=2)
print(name, result.returncode)
sys.exit(result.returncode)
