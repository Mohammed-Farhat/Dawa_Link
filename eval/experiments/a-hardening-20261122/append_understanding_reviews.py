"""Record supplied assistant judgments; never infer verdicts or alter raw outcomes."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
RUN=HERE.parent/'architecture-20261118/runs/20261122T142220_8b5e802698ef'
OUT=HERE/'evidence/candidate4-understanding-assistant-review.jsonl'


def append(notes):
    files=list(RUN.glob('*/case-checkpoints.jsonl'))
    assert len(files)==1
    path=files[0]
    rows=[(n,line,json.loads(line)) for n,line in enumerate(path.read_text().splitlines(),1)]
    assert set(notes).issubset({r['id'] for _,_,r in rows})
    seen={json.loads(line)['id'] for line in OUT.read_text().splitlines()}
    with OUT.open('a') as stream:
        for n,line,row in rows:
            if row['id'] not in notes or row['id'] in seen:continue
            verdict,note=notes[row['id']]
            record=dict(run=RUN.name,id=row['id'],raw_file=str(path),raw_line=n,
                row_sha256=hashlib.sha256(line.encode()).hexdigest(),review_origin='implementation assistant',
                human_reviewed=False,independent=False,verdict=verdict,note=note)
            stream.write(json.dumps(record)+'\n')
