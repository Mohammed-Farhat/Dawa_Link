"""Append supplied manual assistant judgments with immutable raw-row pointers.

This helper never generates semantic verdicts. Existing judgments require an explicit
correction record rather than silent replacement.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DESTINATION = HERE / 'evidence/candidate5-primary-assistant-review.jsonl'


def append(run, notes):
    folder = ROOT / 'eval/experiments/architecture-20261118/runs' / run
    paths = list(folder.glob('*/case-checkpoints.jsonl'))
    if len(paths) != 1:
        raise ValueError('Expected exactly one raw checkpoint file')
    path = paths[0]
    existing = {
        (r['run'], r['id'], r.get('where')): r
        for line in DESTINATION.read_text().splitlines()
        if (r := json.loads(line))
    } if DESTINATION.exists() else {}
    pending = []
    found = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        row = json.loads(line)
        key = (row['id'], row.get('where'))
        if key not in notes:
            continue
        found.add(key)
        verdict, note = notes[key]
        record = dict(run=run, id=row['id'], where=row.get('where'),
                      raw_file=str(path.relative_to(ROOT)), raw_line=number,
                      row_sha256=hashlib.sha256(line.encode()).hexdigest(),
                      review_origin='implementation_assistant', human_reviewed=False,
                      independent=False, verdict=verdict, note=note)
        previous = existing.get((run, *key))
        if previous and previous != record:
            raise ValueError('Use a separate correction record for an existing judgment')
        if not previous:
            pending.append(record)
    if found != set(notes):
        raise ValueError('Supplied judgment has no raw row')
    with DESTINATION.open('a') as stream:
        stream.writelines(json.dumps(r, ensure_ascii=False) + '\n' for r in pending)
    return len(pending)
