"""Load only the authorized evaluation key, preserving isolated env and no tracing."""
from pathlib import Path
import os,sys
from dawalink.evals.experiment import main
key=next(line.split('=',1)[1].strip() for line in Path('../.env').read_text().splitlines() if line.startswith('ANTHROPIC_API_KEY='))
assert key
os.environ['ANTHROPIC_API_KEY']=key
main()
