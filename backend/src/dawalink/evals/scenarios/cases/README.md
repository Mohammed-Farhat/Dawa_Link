# Writing a scenario

**In short:** a scenario is one situation between a client and DawaLink, written as a small Python function that drives a `Stage`. It states what a good agent does (`expected`), plays the story through the API, and checks what the agent really did with `s.check(...)`. Every scenario runs in English, Arabizi and Arabic.

Read [`find.py`](find.py) first: it has three complete examples.

## The rules of a good scenario

1. **The expectation comes from the product's rules, never from what the agent happens to do.** Take it from [`docs/04_domain_rules.md`](../../../../../../docs/04_domain_rules.md), the decision log and `CLAUDE.md` §4, and name the rules in `rules=`. If you can't find the rule, the scenario has no expectation: leave it out.
2. **Check facts with code.** A reservation, a watch, an ask, a case, a tool call and its arguments are read from the tables and the trace. Tone, clarity and "did it explain well" are the judge's: write them in `expected`, don't write a check for them.
3. **A check that fails must mean the agent (or the product) did something wrong.** If it can fail because the scenario was set up wrongly, fix the set-up. A scenario's own mistake is a `StageError`, never a failed check.
4. **Never branch on the language.** The same code runs three times; only the words change (`{"en": .., "az": .., "ar": ..}`).
5. **Small.** One situation, 2 to 6 agent turns. `converse(max_messages=...)` of 4 at most.
6. **Nothing real.** No real person's name, phone, email or address. A phone number in a text is an invented one of the form `03 000 0xx`.

## A scenario

```python
Scenario(
    id="find.rx_bare",  # family.name; the family is the module's name
    kind="normal",  # normal | edge | adversarial | past_failure | ambiguous | long_horizon | tool_failure
    title="A client names a prescription medicine and nothing else",
    expected="...",  # what a good agent does: the judge's reference. Plain, complete, in English.
    play=_rx_bare,  # def _rx_bare(s: Stage) -> None
    prescription="needed",  # needed | not_needed | both | none
    rules=("R-AG9", "R-F1"),
    facts=(
        "You need Concor 5 mg, one box.",
        "You will take it for 30 days.",
        ...,
    ),  # the played client, in English
    manner="You answer what you are asked, briefly, from your facts.",
    client_district="Beirut",  # Beirut, Matn, Baabda, Keserwan, Tripoli, Sidon, Aley, Zahle
    day=0,
    at="10:00",  # days after Monday 2026-11-16, Beirut time
    routing="none",  # "down": a routing service that never answers
)
```

The module ends with `SCENARIOS = [...]`. A new module in this folder is found by itself.

## The words

- **English** (`en`): plain.
- **Arabizi** (`az`): Lebanese Arabic in Latin letters, as people text: `baddi`, `3ande`, `fiyye`, `bukra`, `saydaliyye`, `la 7 iyyem`. No full English sentences.
- **Arabic** (`ar`): Lebanese Arabic in Arabic script (`بدي`, `فيني`, `بكرا`), not formal Arabic. A medicine's name is written as it sounds (`كونكور`, `بروفين`, `أوغمنتين`).
- The first message is written by hand in the three languages. What follows is written by the **played client** (`s.client.converse()`, `s.client.answer()`) from `facts` and `manner`: write the facts in English, the playing model says them in the run's language.

## The world when the story starts

- Monday 2026-11-16, 10:00 in Beirut, unless `day` and `at` say otherwise. Requests and watches start only from 08:00 to 20:00.
- 30 pharmacies (`s.pharmacies(district)`, `s.nearest(k)`), **all shelves empty**: the scenario stocks what it needs with `s.stock(...)`. A pharmacy's name is `"<District> Pharmacy <n>"`.
- Opening hours differ by pharmacy (`SCHEDULES` in `sim/world.py`): some close at 17:00, some at 13:00 with a second opening at 16:00, some never close. `s.set_pharmacy(p, closed_today=True)` closes one for the day.
- The main client (`s.client`) lives in `client_district`; their phone's location is shared when the chat opens (`open_chat(share_location=False)` or `s.forget_home()` change that).
- Every client and pharmacy is invented (`Sim Client 001`, `...@sim.dawalink.test`).

### Medicines to use

| Kind | Names (`s.medicine(name, strength)`) |
|---|---|
| Prescription notice | `concor 5mg` · `concor 10mg` · `augmentin 1g` · `glucophage 850mg` · `crestor 10mg` · `crestor 20mg` · `amaryl 2mg` · `nexium 40mg` · `cipromax 500mg` · `zyrtec 10mg` · `motilium 10mg` · `brufen 600mg` |
| No prescription notice | `brufen 400mg` · `adol 500mg` · `doliprane 500mg` · `aspicot 100mg` · `rennie` · `maalox plus` · `duphalac` · `finallerg 10mg` · `loratin 10mg` · `otipax` |
| Has other brands (`s.other_brand_of(m)`) | `concor 5mg` · `crestor 10mg` · `cipromax 500mg` · `brufen 400mg` · `adol 500mg` · `augmentin 1g` |
| Several strengths under one name | `concor` (5, 10) · `crestor` (5, 10, 20, 40) · `amaryl` (1, 2, 3, 4) · `brufen` (400, 600, syrup) |
| Controlled: never on DawaLink | `tramal` · `xanax` (don't stock them: a controlled product can't be listed) |

`s.medicine` raises a `StageError` when the catalog has no such product: check your names with a run.

**Names that need care** (found while the scenarios were written):
- `adol 500mg` (caplet and suppository), `maalox plus` (chewable tablet and suspension) and `nexium 40mg` (tablets and an injection) come in several forms: pass the form (`s.medicine("adol", "500mg", "caplet")`), and expect the agent to ask which form when the client doesn't say it (R-AG9).
- `doliprane 500mg` has two rows that differ only in the prescription mark, and `aspicot 100mg` comes in two box sizes: unsafe for a check of the notice. `find.checked_medicine` raises when the database disagrees with what the scenario says about the notice.
- A name written with its form word ("Adol 500 caplets") is the subject of [`names.py`](names.py). Elsewhere, name a medicine with one form.
- Two clients who wait for the same medicine need the clock to move between their watches (`s.advance(minutes=5)`): a claim's time is the app's clock, and two claims of the same instant are ordered by a random id.
- A plan's card (`reserve_group`) is never marked recommended. What a card's button does (its pickup day, its items) is in the `proposals` table (`memory.offers_of`).
- `routing="down"` only matters once the road times already stored are emptied (`where.routing_down`). Without it the agent has no routing service, so a place set by name always gets straight-line times.

### Expiry, in days from today (`s.stock(m, pharmacy, days=...)`)

- 0 to 180: listed (visible to clients), if the pharmacy's rule covers it (`set_pharmacy(p, auto_list_days=60)` holds back a box with more than 60 days left).
- 181 to 270: the early-release zone, private. The agent may ask the pharmacy for it.
- over 270: private.
- A box is offered only if it lasts the client's days of use from the pickup day (R-F1).

## The stage (`stage.py`)

**The client** (`s.client`, or `s.person(district=...)` for another one):

| Call | What it does |
|---|---|
| `say(text, in_request=None) -> Turn` | Writes one message (in the chat, or in a request's thread `Q-...`) and waits for the reply |
| `converse(until=None, max_messages=4) -> list[Turn]` | The played client writes until a card is shown (or `until(turn)` is true), it leaves, or the limit |
| `answer() -> Turn \| None` | The played client writes exactly one message |
| `tap(card_or_kind, items=None) -> Tap` | Presses a card's button; a kind (`"reserve"`) means the newest open card of that kind, the recommended one first |
| `cancel(ref)` · `offers()` · `accept_offer()` · `reservations()` · `new_chat()` · `thumbs_down(turn, reason)` | The rest of the website |
| `api(method, path, json=..., key=True)` | Any other route of the API, as this client (`key=True` adds the idempotency key) |

**A pharmacy** (`s.pharmacy(p)`): `not_available(ref, units=None)` · `picked_up(ref)` · `asks()` · `accept_ask(ask_id, qty=1, price_lbp=None)` · `decline_ask(ask_id, reason)` · `add_stock(medicine, days=120, qty=2)` (new stock while a client waits: it is matched at once) · `api(...)`.

**An admin** (`s.admin`): `escalations(state=None)` · `reply(escalation_id, text)` · `close(escalation_id, note="")` · `api(...)`.

**Time:** `s.advance(minutes=, hours=) -> list[Turn]` moves the clock and runs everything that is due (deadlines, the agent's own turns). `s.settle()` runs what is due without moving the clock. Both return what appeared in the clients' conversations.

**Faults** (`s.fault`): `tool(name, times=1)` (`times=None`: always) · `model(calls=N)` · `clear()`. With `routing="down"` on the scenario, the routing service never answers.

**Setting the scene:** `s.stock(...)`, `s.set_pharmacy(...)`, `s.forget_home()`, and `with s.setup() as session:` for anything else (a session that may write any table). What happens **in** the story goes through an actor, never through `setup()`.

**Reading what happened:** `s.orders()`, `s.claims()`, `s.asks()`, `s.requests()`, `s.escalations()` (lists of dicts; their keys are in each function's docstring), `s.stored_messages(conversation)`, `s.case_state(conversation)`, and `with s.read() as session:` for anything else.

### A `Turn`

`reply` (the agent's words) · `cards` (each: `kind`, `title`, `lines`, `recommended`, `prescription_notice`, `state`, `button`, `item_keys`, `mentions(words)`) · `kinds` · `card(kind)` · `quick_replies` · `system_cards` (template cards, no model) · `team_said` · `tools` (each: `name`, `arguments`, `ok`, `answer`) · `called(name)` · `tool_names()` · `status`, `error` (the API's code when it refused the message) · `with_team` · `agent_turns` · `outcomes` · `answered`.

Card kinds: `reserve`, `reserve_group` (a plan: [Reserve these]), `request_summary` ([Start sourcing]), `cancel`, `accept_offer`, `constraint_change`, `remove_item`, `other_brand` (no button).

The agent's tools: `search_catalog`, `get_equivalents`, `find_options`, `plan_basket`, `get_reservations`, `get_request_status`, `propose_reservation`, `show_other_brand`, `propose_plan`, `propose_cancellation`, `prepare_request_summary`, `propose_constraint_change`, `propose_remove_item`, `create_watch`, `set_area`, `open_claim`, `request_early_release`, `schedule_followup`, `escalate`.

## Checks

```python
s.check(
    "reserved_the_right_medicine",
    ok,
    level="end_to_end",
    family="task_success",
    detail="what was seen instead",
)
```

Use the shared ones of [`expect.py`](../expect.py) when they fit (`asks_before_searching`, `searches_without_asking`, `asked_once`, `searched`, `reserved`, `nothing_changed`, `no_card`, `called`, `did_not_call`): the same expectation then has the same name everywhere.

| `level` | The question (the course's chapter 9) | Examples |
|---|---|---|
| `component` | Did a building block work? | a tool returned the right boxes; the card carries the notice; a phone number was removed before storage; a guard caught a reply |
| `step` | Was one decision right? | the right tool, the right arguments, the right card |
| `trajectory` | Was the path good? | asked once, no loop, stopped at the right time, recovered from an error |
| `end_to_end` | Was the client's goal reached, within the rules? | the reservation exists, for the right day; nothing changed after a refusal |

| `family` | What it measures |
|---|---|
| `task_success` | completion, the goal, the client's constraints (days, day, area, budget) |
| `output_quality` | complete, true to the tools, nothing invented, the right card shown |
| `tool_use` | the right tool, the right arguments |
| `planning` | asking or not asking, the order of steps, adapting when something changes |
| `memory` | what was said earlier is used; what is stale is not |
| `efficiency` | time, model calls (most of it is counted automatically) |
| `reliability` | recovery from a failure |
| `safety` | nothing done without the client's tap, no medical advice, no leak, no special priority |

Every scenario also gets automatic checks (`checks.py`): the reply's language, no tool names or IDs in it, plain text, nothing invented, speed, tool errors, repeated calls, never "car or on foot?". Don't write those again.

When a story breaks one of them on purpose (a reply that must be in another language than the run's, a tool that must refuse), name it in the scenario's `not_automatic=("tool_calls_succeed",)`. A `tool_failure` scenario is never counted for `tool_calls_succeed` and `turn_ended_normally`.

## Running

Inside `backend/` (it costs a few cents; the limit is hard):

```
uv run --env-file ../.env python -m dawalink.evals.scenarios.run --model claude-haiku-5-5 --max-usd 0.30 --lang english --family find --suffix dev_find
```

`--only find.rx_bare` plays one scenario; `--judge-model claude-sonnet-5-5` adds the judge. The rows are in `eval/results/<date>_scenarios_<lang>_<model>_prompt-<version>_<suffix>/scenarios.jsonl`: each has the transcript, the tool calls, the checks, and `error` when the scenario itself broke.
