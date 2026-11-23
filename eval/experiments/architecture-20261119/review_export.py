"""Export compact raw evidence for assistant inspection, without model/scoring calls."""

import argparse
import json
from pathlib import Path

from dawalink.evals.score_understanding import CHECKS

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--case', default='')
    parser.add_argument('--flags-only', action='store_true')
    args = parser.parse_args()
    folder = RUNS / args.run
    manifest = json.loads((folder / 'manifest.json').read_text())
    expected = {r['id']: r for r in (json.loads(line) for line in (
        ROOT / 'eval/development-v2/scored' / (manifest['suite'] + '.jsonl')
    ).read_text().splitlines())}
    filename = 'conversations.jsonl' if manifest['suite'] == 'multiturn' else 'answers.jsonl'
    for p in folder.glob(f'*/{filename}'):
        for line in p.read_text().splitlines():
            row = json.loads(line)
            if args.case and row['id'] not in args.case.split(','):
                continue
            steps = row.get('exchanges', [row])
            display_steps = row.get('exchanges') or row.get('turns') or [row]
            failed = [k for step in steps for k, v in step.get('checks', {}).items()
                      if v is not None and v != CHECKS.get(k, True)]
            flags = [issue for step in steps
                     for issue in step.get('review', {}).get('candidate_issues', [])]
            if args.flags_only and not failed and not flags and row.get('outcome') == 'ok':
                continue
            print(json.dumps({
                'run': folder.name, 'architecture': manifest['architecture'], 'suite': manifest['suite'],
                'id': row['id'], 'where': row.get('where'), 'expected': expected[row['id']],
                'automatic_failed': failed, 'semantic_flags': flags,
                'root_cards': row.get('card_items'),
                'root_tools': [{'name': t['name'], 'arguments': t['arguments'],
                                'ok': t['ok']} for t in row.get('tools', [])],
                'turns': [{'client': s.get('client', row.get('text')), 'reply': s.get('reply'),
                           'outcome': s.get('outcome'), 'checks': s.get('checks'),
                           'cards': s.get('card_items'),
                           'tools': [{'name': t['name'], 'arguments': t['arguments'],
                                      'ok': t['ok']} for t in s.get('tools', [])]}
                          for s in display_steps],
            }, ensure_ascii=False))


if __name__ == '__main__':
    main()
