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

## What's where

```
backend/    the API, the agent and the worker (Python, FastAPI)
frontend/   the website (React, TypeScript, Mantine)
docs/       the plan: scope, rules, database, API, agent, evaluation, failures, threats, UI, deployment
```

## How this project uses AI

- **The product:** DawaLink's agent runs on a large language model. Tests use a scripted fake
  model, development uses a local model, and the evaluation and demo use Anthropic's Claude API.
- **The code:** it is written with Claude Code (Anthropic's coding assistant), following the plan
  in `docs/`. The repository owner checks every change before committing it.
