"""Read-only model availability; no generation and no API credit spent."""
from pathlib import Path
import anthropic
key=next(line.split('=',1)[1].strip() for line in Path('../.env').read_text().splitlines() if line.startswith('ANTHROPIC_API_KEY='))
try:
 client=anthropic.Anthropic(api_key=key,max_retries=0)
 model=client.models.retrieve('claude-haiku-5-5')
 print('Configured model available:',model.id)
except Exception as error:
 print('Provider availability check failed:',type(error).__name__, 'status:',getattr(error,'status_code',None))
 raise SystemExit(1) from None
