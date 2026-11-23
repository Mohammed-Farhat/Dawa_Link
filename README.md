# DawaLink

DawaLink connects people who can't afford a medicine at full price with pharmacies selling
**near-expiry stock at a discount**. One AI agent brings each client's need to the right pharmacy:
it understands the request, decides where the client should go, and keeps searching for up to
six hours. Everything exact (stock, prices, deadlines, who gets scarce stock first) is plain code,
and every action that matters needs the client's tap.

Course project: Agentic Systems 503N/798S, Fall 2026 (Path A).

- **The plan and every decision:** [docs/README.md](docs/README.md)
- **Status:** the website, its API and the agent are built and tested. What is left: the agent's final evaluation, the deployment to AWS, the report and the demo.

## Run it on your machine

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/). Then:

```bash
cp .env.example .env
```

Then fill in two values in `.env`, each with the one-line command written above it in the file:
`APP_SECRET_KEY` (required: `docker compose` stops and says so while it is empty) and
`DEMO_ACCOUNTS_PASSWORD` (the demo accounts' password; empty, they can't log in).
`.env.example` leaves both empty because it is public.

Demo mode is on by default, and it needs the medicine catalog (see [The medicine catalog](#the-medicine-catalog)):
without it the database step stops. Build the catalog first, or set `DEMO_MODE=false` in `.env`.

```bash
docker compose up --build
```

| Open | What it is |
|---|---|
| http://localhost:5173 | The website |
| http://localhost:8000/api/v1/health | The API's health check |
| http://localhost:8000/api/v1/docs | The API's interactive documentation (local only) |
| http://localhost:8025 | Every email the app sends, caught locally (nothing leaves this machine): the links to confirm a new account and to set a new password ("Forgot your password?") arrive here |

**To log in:** create an account on the website (a client's, or a pharmacy's from "Are you a pharmacy?" on the welcome page) and open the confirmation email in the local mailbox above (the link confirms the email; then log in with your password), or use a demo account: `client01@demo.dawalink.test` to `client06@demo.dawalink.test`, or a demo pharmacy, `pharmacy01@demo.dawalink.test` to `pharmacy16@demo.dawalink.test` (it opens the pharmacy's portal), with the password you set as `DEMO_ACCOUNTS_PASSWORD` in `.env`. Without that setting the demo accounts can't log in.

**The assistant** answers only when `LLM_PROVIDER` is set in `.env` (`anthropic` spends API credit, a few cents per conversation). With `none`, the chat says the assistant isn't available, and everything else works.

Use `localhost` in the address bar, not `127.0.0.1`: the API only accepts browser calls from
the website's exact address.

Stop everything with `docker compose down`. Add `-v` to also delete the local database.

## Work on the code

You need [uv](https://docs.astral.sh/uv/) for the backend and [Node.js](https://nodejs.org/) 24
for the website. Start the database first:

```bash
docker compose up -d postgres
```

**Backend** (run these inside `backend/`):

| Task | Command |
|---|---|
| Install | `uv sync` |
| Tests | `uv run --env-file ../.env pytest` |
| Only the random requests against the API (about half a minute; they also run with the tests) | `uv run --env-file ../.env pytest -m fuzz` |
| Lint and format | `uv run ruff check .` and `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run the API | `uv run --env-file ../.env uvicorn dawalink.api.main:create_app --factory --reload` |
| Run the worker | `uv run --env-file ../.env python -m dawalink.worker` |
| Talk to the agent as a demo client (uses the model in `.env`; Claude spends credit) | `uv run --env-file ../.env python -m dawalink.ops.chat "baddi panadol"` |
| Prepare the database (logins, tables, catalog, demo data) | `uv run --env-file ../.env python -m dawalink.ops.prepare_db` |
| Create an admin (asks for a password, then shows once the key for an authenticator app) | `uv run --env-file ../.env python -m dawalink.ops.create_admin --email you@example.org --name "Your Name"` |
| Re-export the API description | `uv run python -m dawalink.ops.export_openapi ../docs/openapi.json` |

**Website** (run these inside `frontend/`):

| Task | Command |
|---|---|
| Install | `npm install` |
| Tests | `npm test` |
| Lint and type check | `npm run lint` and `npm run typecheck` |
| Run with live reload | `npm run dev` (stop the `web` container first: `docker compose stop web`) |
| Regenerate the API types | `npm run gen:api` |

## The medicine catalog

The catalog is the Ministry of Public Health's public price list, joined with its Lebanon
National Drugs Database (both on [moph.gov.lb](https://www.moph.gov.lb)). The Ministry's files
are **not in this repository**: download them once, inside `backend/`:

| Step | Command |
|---|---|
| 1. Download the price list and the database pages (about 5 minutes) | `uv run python -m dawalink.ops.fetch_moph --date 2026-11-11` |
| 2. Download the Ministry's list of medicines sold without a prescription (skip it, and every product shows the prescription notice) | `uv run python -m dawalink.ops.fetch_otc_list` |
| 3. Join them into `data/moph/catalog.csv` | `uv run python -m dawalink.ops.build_catalog` |
| 4. Load them (also done by "Prepare the database" when there are no products yet; when there are, "Prepare the database" only refreshes their prescription marks from the file) | `uv run --env-file ../.env python -m dawalink.ops.import_catalog` |

`--date` is the date of a list on the Ministry's
[price list page](https://www.moph.gov.lb/en/DynamicPages/index/3/37424/drugs-public-price-list-).
The team's own rules (controlled medicines, extra words for the no-prescription marks, corrections) are in
`backend/data/catalog_overrides.toml`. Without the catalog file everything still runs with
`DEMO_MODE=false`, with nothing to search for; in demo mode the database step stops.

## The places a client can name

A client who doesn't share their location can say where they are ("I'm in Zgharta"). The
names are looked up in two files of `backend/data/`: `areas.csv`, written by hand (the
districts, the well-known neighbourhoods and the ways people spell them), and
`areas_osm.csv`, generated from OpenStreetMap (every town and village with its centre).
Both are in this repository, so nothing needs downloading. To build the second one again,
inside `backend/`:

| Step | Command |
|---|---|
| 1. Download Lebanon's places (under 1 MB, into `data/osm/`) | `uv run python -m dawalink.ops.fetch_osm_places` |
| 2. Join them with `areas.csv` into `data/areas_osm.csv` | `uv run python -m dawalink.ops.build_areas` |

Place names, centres and road travel times are © [OpenStreetMap](https://www.openstreetmap.org/copyright)
contributors, available under the Open Database License.

## The evaluation

The plan is in [docs/08_evaluation.md](docs/08_evaluation.md); the data sheets are in
[eval/datasets/README.md](eval/datasets/README.md). Everything below is free: no command
here calls a paid model. Inside `backend/`:

| To | Command |
|---|---|
| Check the written cases (messages and attacks) | `uv run --env-file ../.env python -m dawalink.evals.validate` |
| Check the planner on the 50 baskets with known best plans | `uv run python -m dawalink.evals.plan_set` |
| Play simulated days with the search baseline, the policy with no AI, or the same policy asking first, `--contender rules_asking` (each run gets a database of its own, `dawalink_sim_...`) | `uv run --env-file ../.env python -m dawalink.sim.run --contender search --seeds 1-5` (or `--contender rules`) |
| Play a simulated day with the agent on Claude (**paid**: it refuses to start without a model and a spending limit; the evidence goes to `eval/results/`) | `uv run --env-file ../.env python -m dawalink.sim.run --contender agent --model claude-haiku-5-5 --max-usd 0.50 --requests 10` (add `--without planning`, `early_release` or `replanning` for an ablation) |
| Score the agent's understanding on the written cases (**paid**: one to three turns per case; when the agent asks before it searches, the case's client answers, and one client in four leaves one thing out first) | `uv run --env-file ../.env python -m dawalink.evals.run_understanding --model claude-haiku-5-5 --max-usd 1.00` |
| Try the written attacks on the agent and score them (**paid**: one or two turns per attack) | `uv run --env-file ../.env python -m dawalink.evals.run_safety --model claude-haiku-5-5 --max-usd 1.00` |
| Let a second model play the client and score the conversations (**paid** twice: the agent's turns and the playing model's messages) | `uv run --env-file ../.env python -m dawalink.evals.run_conversations --model claude-haiku-5-5 --max-usd 1.50` |
| Print the evaluation's tables from the saved runs, with their 95% intervals | `uv run python -m dawalink.evals.report` (add `--write` for `eval/results/REPORT.md`) |
| Play a day again with each assumption at its low and high value (free contenders) | `uv run --env-file ../.env python -m dawalink.sim.sweep --contender rules --seeds 1` |
| The free checks before committing a change (about 3 minutes) | `uv run --env-file ../.env python -m dawalink.evals.before_commit` |
| Only the scan of the saved results for an email, a phone number or coordinates (seconds; part of the checks above) | `uv run python -m dawalink.evals.scan_results` |

## What's where

```
backend/    the API, the agent and the worker (Python, FastAPI)
frontend/   the website (React, TypeScript, Mantine)
docs/       the plan: scope, rules, database, API, agent, evaluation, failures, threats, UI, deployment
eval/       the evaluation's data: the written cases, the simulated world, the results
```

## How this project uses AI

- **The product:** DawaLink's agent runs on a large language model. Tests use a scripted fake
  model, development uses Claude Haiku 5.5 (a local model is a spare for when there is no
  network), and the evaluation and demo use Anthropic's Claude API.
- **The code:** it is written with Claude Code (Anthropic's coding assistant), following the plan
  in `docs/`. The repository owner checks every change before committing it.
