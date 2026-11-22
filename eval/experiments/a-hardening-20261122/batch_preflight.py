"""Reject batches that would reuse or exhaust synthetic clients, before paid work."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def check_capacity(args):
    suite = args[0]
    if suite not in ('understanding', 'safety', 'multiturn'):
        return
    def option(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    rows = [json.loads(line) for line in
            (ROOT / f'eval/development-v2/scored/{suite}.jsonl').read_text().splitlines()]
    ids = option('--cases', '')
    if ids:
        wanted = ids.split(',')
        if len(set(wanted)) != len(wanted) or set(wanted) - {r['id'] for r in rows}:
            raise SystemExit('Invalid or duplicate case selection')
        rows = [r for r in rows if r['id'] in wanted]
    limit = option('--limit')
    if limit is not None and int(limit) < 1:
        raise SystemExit('Batch limit must be positive')
    rows = rows[:int(limit) if limit is not None else None]
    clients = sum(2 * len(r['where']) for r in rows) if suite == 'safety' else len(rows)
    if not rows or clients > 200:
        raise SystemExit(f'{suite} needs {clients} clients; fresh batch capacity is 200')
