# DawaLink

DawaLink connects people who can't afford a medicine at full price with pharmacies selling
**near-expiry stock at a discount**. One AI agent brings each client's need to the right pharmacy:
it understands the request, decides where the client should go, and keeps searching for up to
six hours. Everything exact (stock, prices, deadlines, who gets scarce stock first) is plain code,
and every action that matters needs the client's tap.

Course project: Agentic Systems 503N/798S, Fall 2026 (Path A).

- **The plan and every decision:** [docs/README.md](docs/README.md)
- **Status:** the build has started. The code skeleton is in place; features come next.

## Run it on your machine

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/). Then:

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

| Open | What it is |
|---|---|
| http://localhost:5173 | The website |
| http://localhost:8000/api/v1/health | The API's health check |
| http://localhost:8000/api/v1/docs | The API's interactive documentation (local only) |
| http://localhost:8025 | Every email the app sends, caught locally (nothing leaves this machine) |

**To log in:** create an account on the website (a client's, or a pharmacy's from "Are you a pharmacy?" on the welcome page) and open the confirmation email in the local mailbox above, or use a demo account: `client01@demo.dawalink.test` to `client06@demo.dawalink.test`, or a demo pharmacy, `pharmacy01@demo.dawalink.test` to `pharmacy16@demo.dawalink.test` (it opens the pharmacy's portal), with the password you set as `DEMO_ACCOUNTS_PASSWORD` in `.env` (`.env.example` has one for your own machine). Without that setting the demo accounts can't log in.

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
| Lint and format | `uv run ruff check .` and `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run the API | `uv run --env-file ../.env uvicorn dawalink.api.main:create_app --factory --reload` |
| Run the worker | `uv run --env-file ../.env python -m dawalink.worker` |
| Talk to the agent as a demo client (uses the model in `.env`; Claude spends credit) | `uv run --env-file ../.env python -m dawalink.ops.chat "baddi panadol"` |
| Prepare the database (logins, tables, catalog, demo data) | `uv run --env-file ../.env python -m dawalink.ops.prepare_db` |
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
| 2. Join them into `data/moph/catalog.csv` | `uv run python -m dawalink.ops.build_catalog` |
| 3. Load them (also done by "Prepare the database" when there are no products yet) | `uv run --env-file ../.env python -m dawalink.ops.import_catalog` |

`--date` is the date of a list on the Ministry's
[price list page](https://www.moph.gov.lb/en/DynamicPages/index/3/37424/drugs-public-price-list-).
The team's own rules (controlled medicines, the no-prescription list, corrections) are in
`backend/data/catalog_overrides.toml`. Without the catalog file everything still runs, with
nothing to search for.

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

## What's where

```
backend/    the API, the agent and the worker (Python, FastAPI)
frontend/   the website (React, TypeScript, Mantine)
docs/       the plan: scope, rules, database, API, agent, evaluation, failures, threats, UI, deployment
eval/       the evaluation's data: the written cases, the simulated world, the results
```

## How this project uses AI

- **The product:** DawaLink's agent runs on a large language model. Tests use a scripted fake
  model, development uses a local model, and the evaluation and demo use Anthropic's Claude API.
- **The code:** it is written with Claude Code (Anthropic's coding assistant), following the plan
  in `docs/`. The repository owner checks every change before committing it.
