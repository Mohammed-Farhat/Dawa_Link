# Native Safari observations

Dedicated new Safari window, localhost:55173 -> loopback API :58000;
PostgreSQL :55433/dawalink_sim_browser_reconciliation_1811, synthetic demo accounts.
No paid model, ORS or Langfuse. Fixture source: ../browser_fixture.py. Agent/API
source unchanged; fixture phases are selected explicitly, not a language benchmark.

- Initial fixture incorrectly matched "today" in the model's contextual UserText
  and skipped clarification. No reservation was approved in that attempt. Corrected
  fixture uses explicit clarify/reserve phases; original output preserved in chat.
- New chat: "I need one box of LITAK." -> visible pickup/day/transport clarification.
  Answered "Today, seven days, I have a car." -> actual reserve proposal.
  Client Reserve -> R-EYA8WZ. Pharmacy02 Today queue -> same ticket -> Picked up.
  Visible "Picked up", due/reserved counts returned to zero.
- Client Me -> Log out -> immediately /login with "Welcome back", without refresh.
  Repeated client/pharmacy switches also redirected correctly; password-save prompts
  dismissed with Not Now. Synthetic credentials only.
- New client-approved reservation R-DTGEVU -> ticket -> Cancel this reservation ->
  confirmation -> Yes, cancel it -> visible "Cancelled by you". Chat showed Cancelled.
- New client-approved reservation R-G3X3RH -> pharmacy queue -> Not available ->
  Mark as not available -> visible "Marked not available" and due/reserved zero.
  Client re-login displayed "Not available: the pharmacy didn't have R-G3X3RH".
- Sourcing: HAVRIX '1440' deliberately has no inventory in this fixture. Client
  approved Start sourcing -> Q-RRX7QJ, "0 of 1 reserved", "6 h 0 min left".
  Advanced synthetic clock six hours one minute; real ClockTasks.end_windows
  expired exactly one request (browser-timeout evidence). Final timeout UI remains
  unverified: user switched Safari to another window before the refresh. Stopped
  native input instead of acting on the user's video window. No other tabs changed.

These observations verify transport/approval/state rendering and user actions.
They do not establish live model understanding, clinical safety or sourcing quality.

## Follow-up after explicit user permission

User authorized returning to the test window. Fresh Safari AX state showed request
Q-RRX7QJ with "The search has ended: nothing was found in time", HAVRIX '1440'
"Not found in time", and "Request Q-RRX7QJ is closed." Thus final timeout UI is now
verified. Browser input ended; no unrelated form was edited or submitted.
