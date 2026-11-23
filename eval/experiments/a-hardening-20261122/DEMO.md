# Repeatable local demo (synthetic infrastructure only)

Live-model status: BLOCKED BY STOP_PAID; NOT VERIFIED. The older scripted journeys are supporting UI
transport/state evidence. Do not describe them as live-model validation.

Prerequisites: local isolated evaluation PostgreSQL/Mailpit; local.env from the existing
ignored integration checkpoint; live-model key in ignored root .env; canonical ledger
with applicable expanded-stage room and a $0.645 conservative call reservation. Never
replace the production/development database or show credentials in recordings.

Before any live run, resolve STOP_PAID through attributable billing evidence or explicit
revised authorization, then pin live_browser.py to the approved candidate6 source.
The current factory still references candidate5 and rejects source drift. Do not remove
the stop or treat this script as authorization.

1. After those prerequisites, from backend initialize the disposable fixture:
   `.venv/bin/python ../eval/experiments/a-hardening-20261122/live_browser.py init`
2. Launch the factory on loopback port58000 using the same Python environment:
   `.venv/bin/python -m uvicorn live_browser:make --factory --app-dir ../eval/experiments/a-hardening-20261122 --host 127.0.0.1 --port 58000`
3. From frontend, `VITE_API_URL=http://localhost:58000 npm run dev -- --port 55173`.
   Open localhost:55173 in a dedicated browser tab; sign in with the synthetic client
   and configured demo password. Fixture initialization prints the stocked and empty
   product names. Synthetic clock starts 16Nov2026 10:00 Beirut; say "today" accordingly.
4. Ask for one box of the stocked product. Show the live clarification. Answer:
   "Today, seven days, I have a car." Show the proposal and explain that stock is still
   unreserved until approval. Approve one actual card; note its ticket.
5. As the synthetic pharmacy account for the selected card, locate that ticket and mark
   Picked up. Verify the client-visible state. If the live model picked another pharmacy,
   use that pharmacy's synthetic account; do not assume pharmacy02.
6. Make a new client-approved reservation; cancel through its confirmation flow and
   verify Cancelled. Make a separate reservation; pharmacy marks Not available and verify
   the client sees that outcome. These are distinct orders; preserve all ticket evidence.
7. Ask for the fixture's empty product and approve the sourcing proposal. Verify it is
   open, then from backend run `live_browser.py timeout` with the same environment.
   Refresh and verify the six-hour sourcing timeout. No invented responses or hidden
   scripted model phases may substitute for the live interaction.
8. Stop API/frontend servers. Keep evidence and the isolated evaluation volume; do not
   drop databases or release unknown charges. Run the new audit and record costs by
   browser run_id from browser-state.json, screenshots, tickets and observed limitations.

Keep a recording brief: clarification → proposal → explicit approval → reservation →
pickup; cancellation and unavailable-stock on separate orders; empty-stock request →
six-hour timeout. State the run's actual model, source pin, synthetic clock and cost.
If a model or provider fails, retain and show that outcome; do not replay it invisibly.
