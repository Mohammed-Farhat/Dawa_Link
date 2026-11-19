from pathlib import Path
from dawalink.evals.validate import check
from dawalink.evals.datasets import read, UCase, RCase
root=Path('../eval/experiments/architecture-20261118')
for name in ('development','challenge'):
 p=root/name
 problems=check(p,with_catalog=True)
 print(name, 'problems:',problems)
 assert not problems
 print('understanding:',len(read(p/'understanding.jsonl',UCase)), 'safety:',len(read(p/'safety.jsonl',RCase)))
