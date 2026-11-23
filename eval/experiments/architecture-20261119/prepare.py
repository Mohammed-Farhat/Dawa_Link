"""Freeze balanced development screening cases, before comparative scoring (offline)."""

import hashlib
import itertools
import json
import random
from collections import Counter
from pathlib import Path

from dawalink.evals.development_review import raw, stratified

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DATA = ROOT / 'eval/development-v2/scored'
SEED = 20261119


def balanced(suite: str, counts: list[int]) -> list[str]:
    rows = raw(DATA / f'{suite}.jsonl')
    result = []
    for index, (lang, count) in enumerate(zip(
        ['english', 'arabic', 'arabizi', 'mixed'], counts, strict=True
    )):
        subset = [r for r in rows if r['lang'] == lang]
        result.extend(stratified(subset, count, SEED + index))
    return sorted(result)


def behavior(row: dict) -> str:
    purpose = row['purpose']
    for key in ('long', 'partial', 'quantity', 'budget', 'pickup', 'transport'):
        if key in purpose:
            return key
    if 'drop' in purpose or 'remove' in purpose:
        return 'remove'
    return 'conflict'


def main() -> None:
    conversations = raw(DATA / 'multiturn.jsonl')
    rng = random.Random(SEED)
    candidates = list(itertools.combinations(conversations, 10))
    rng.shuffle(candidates)
    wanted = Counter(english=3, arabic=3, arabizi=2, mixed=2)
    chosen = min(candidates, key=lambda rows: (
        8 - len({behavior(r) for r in rows}),
        sum(abs(Counter(r['lang'] for r in rows)[k] - v) for k, v in wanted.items()),
    ))
    cases = {'understanding': balanced('understanding', [8, 8, 7, 7]),
             'safety': balanced('safety', [5, 5, 5, 5]),
             'multiturn': sorted(r['id'] for r in chosen)}
    lookup = {r['id']: r for suite in cases for r in raw(DATA / f'{suite}.jsonl')}
    plan = {
        'seed': SEED,
        'method': 'Near-equal language quotas, category strata within language; conversation '
                  'seeded combination minimizing uncovered behaviors then language imbalance',
        'cases': cases,
        'coverage': {s: {'count': len(ids), 'languages': dict(Counter(lookup[i]['lang'] for i in ids)),
                         'behaviors': [lookup[i].get('category', lookup[i].get('purpose')) for i in ids]}
                     for s, ids in cases.items()},
        'dataset_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in DATA.glob('*.jsonl')},
        'smoke_understanding': stratified([lookup[i] for i in cases['understanding']], 5, SEED + 3),
        'repetitions': {'1': ['current', 'staged', 'verified'],
                        '2': ['verified', 'staged', 'current']},
        'supersedes_before_scoring': 'screening-proportional-rejected.json; mixed safety absent',
    }
    with (HERE / 'screening.json').open('x') as stream:
        json.dump(plan, stream, indent=2)
    print(json.dumps(plan['coverage'], indent=2))


if __name__ == '__main__':
    main()
