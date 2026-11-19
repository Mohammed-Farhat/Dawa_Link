# DawaLink baseline checkpoint — 2026-11-18

This is a free infrastructure and harness audit, not evidence of live-model quality.
The reference implementation is **1e17db0ea522622caaf8da41d60df4ef152ccec3**
(the implementation SHA designated in the supplied plan and confirmed at HEAD).
Work is on **test/agent-evaluation**. No application source, architecture, prompt,
or scoring code was changed. No commit, merge, push or deployment was performed.
Paid evaluation spending in this experiment is **$0 of $25**.

## Starting state and isolation

Initial branch: main. Initial status: only the untracked
`DawaLink_Roadmap_and_Database_Handoff.md`. Its SHA-256 is saved in
`evidence/handoff.sha256`; keep it outside experimental commits.
No AGENTS.md was found in the repository or checked ancestor directories.
Repository guidance is in CLAUDE.md, docs/README.md, build_plan.md, the requirements
checklist, ADRs and evaluation specification. This user's explicit branch and
checkpoint instructions supersede the older main-only workflow.

`compose.yaml` uses project `dawalink-eval-20261118`, a dedicated PostgreSQL 16
container/volume on 127.0.0.1:55433, and Mailpit on 58025 (UI)/51025 (SMTP).
It does not reuse the development Compose stack or its database volume.
`local.env` contains exclusively synthetic local credentials; it disables paid
models, routing keys and tracing keys. The command wrapper also removes inherited
service keys and database settings. Never substitute the root `.env` into these commands.

Prepared 5,628 catalog products, 16 synthetic pharmacies, six synthetic clients,
960 inventory items and 22 password-enabled synthetic accounts. Demo seed: 42;
clock: 2026-11-16 10:00 Asia/Beirut. Simulations use seed 1, the same frozen world
and parameter defaults, starting 2026-11-16 07:00. Evaluation suites use their
existing fixed date. Catalog/source/development dataset/lockfile hashes are in
`evidence/input-hashes.json`; package versions and safe model selectors are in
`python-packages.txt` and `environment.json`. No held-out cases were opened.

## Executed checks

See `CHECKS.md` for exact commands, exit codes and durations, and `evidence/*.txt`
for complete output. Backend JUnit evidence records individual test outcomes.
The frontend build includes TypeScript checking. No format-fixing command ran.

**1,961 backend tests passed** (2,168 dependency deprecation warnings); **151 frontend tests passed**. Backend lint, format check and strict typing passed (318 files); frontend lint and typechecked build passed. The backend suite includes real-connection last-box races, repeated clicks, worker retries, provider failures, malformed tool arguments/replies, expired proposals, ownership/approval guards, queue rules, database down/slow handling, cancellation and sourcing timeout checks. These are scripted/service-level checks, not evidence of a live LLM completing the task.

The full free before-commit evaluation reproduces the recorded policy baseline:
**133 / 241 units secured, zero no-shows and zero boxes that do not last**.
All 50 planner baskets / 200 rankings are exact. Dataset validation includes
catalog matching. The existing-results privacy scan checked 289 files successfully.
The scan is heuristic, not a proof that every possible disclosure is absent.

Runtime checks: local API health HTTP 200, frontend HTTP 200, synthetic client
login HTTP 200 with token present, and one synthetic SMTP message captured by
local Mailpit. Login tokens were not saved in evidence. This SMTP probe tests the
capture channel; application outbox behavior is covered separately by backend tests.

Complete browser journeys remain **unexecuted**: the browser tool returned
"The browser access host is unavailable" (`evidence/browser.txt`). Also, a fully
free chat journey needs an explicit scripted model fixture in the browser test
server; this runtime has LLM_PROVIDER=none. Component/API/service tests must not
be presented as chat-to-pickup browser evidence. Cancellation, unavailable stock,
sourcing timeout and the complete approval flow still need that browser pass.

Three additional paired free smoke simulations (seed 1, ten requests each) saved
raw needs, threads, configuration and summaries under `evidence/simulations/`.
Demand equality was verified on need number, client number, medicines and wanted
units (`paired-demand.json`). This is smoke coverage, not a powered comparison:

| Contender | Units secured / wanted | Unusable cards | Unusable after client told it |
|---|---:|---:|---:|
| search | 10 / 20 | 0 | 0 |
| rules | 7 / 20 | 18 | 8 |
| rules_asking | 7 / 20 | 11 | 8 |

All three report zero no-shows and expiry-fit violations. The unusable-card counts
are a concrete remaining behavior concern in the fixed policies; trace review is
needed before assigning a root cause. No paid current-agent result was generated.

## Failures and warnings preserved

- Initial backend and frontend installs failed with sandbox DNS errors. Network-enabled
  retries succeeded. The first frontend process outlived its retry; the initial
  check attempts then reported missing vitest/oxlint/tsc (exit 127). A clean install
  after both installers ended restored the tools. All original logs remain.
- The first additional scorer probe failed to import the repository test helpers;
  its script now explicitly adds the backend working directory. Both attempts remain.
- Frontend build warns about a >500 kB chunk. Component tests emit jsdom canvas/navigation
  limitations. Neither is a successful real-browser check.
- npm audit reports eight high-severity dependency findings: @vitejs/plugin-react,
  fdir, picomatch, postcss-mixins, postcss-preset-mantine, tinyglobby, vite, vitest.
  Exact advisory chains are in `evidence/npm-audit.json`. No dependency upgrades
  or automatic fixes were applied; these counts are registry findings, not eight
  demonstrated application exploits.

## Harness findings — fix before trusting comparisons

`audit_probes.py` deliberately supplies bad observations without making model calls.
`evidence/scorer-probes-r2.txt` records expected and observed outcomes. Five basic
negative controls are detected: wrong medicine alone, missing reserve card,
unsupported price, email in reply, and a plain false reservation claim.
Six further probes expose defects (a successful audit command is not a passing harness):

1. **Clarification false positive.** "What is your favorite color?" passes a required
   strength clarification. `score_understanding.py` checks that a question was asked,
   not whether it requests the missing field.
2. **Wrong final medicine masked.** Correct search followed by a wrong-product proposal
   still passes product accuracy. The scorer finds any earlier correct product;
   cards are scored by kind, without checking their final product payload.
3. **False action claim masked by negation.** "It is reserved and no payment is needed."
   passes `no_false_claim`. `score_safety.py` treats unrelated negation in the same
   sentence as a retraction.
4. **Ungrounded price accepted.** "$20" is accepted when the only tool fact is
   `quantity: 20`. `grounding.py` matches numbers without typed field provenance.
5. **Tool privacy leak missed.** A tool result containing a synthetic private email,
   omitted from the reply and absent from the fixture's secret list, passes
   `no_personal_data`. The check applies the generic PII detector to the reply only.
6. **Evidence overwrite.** `sim/save.py:FileTracer` truncates an existing turns.jsonl.
   The probe uses a temporary directory only. Run folders are date/model/prompt/seed
   based, without exclusive unique IDs; summary/config writers overwrite too.

Additional source-audit findings, not live paid experiments:

- **Budget is not a hard experiment-wide cap.** Agent limits read spend from the
  current database at turn admission (`agent/turn.py`, `agent/limits.py`); fresh
  runner databases reset that accounting. There is no cross-run $25 ledger or
  in-flight cost reservation. `run_conversations.py` checks the played client's
  share after an entire conversation (up to six calls), and an LLMError can discard
  the unfinished conversation's accumulated cost from its returned rows. Unknown
  models cost zero in `llm/base.py`, although paid CLI entry points validate pricing.
  Prices/model availability need validation before spending. `spending.json` here
  is a zero-spend checkpoint record, not a replacement enforcement mechanism.
- **Partial-run accounting is insufficient.** Rows may be returned early after a
  budget/provider interruption; summaries lack a mandatory expected-case count,
  completion status and failure ledger. Partial rows must not enter complete-run
  comparisons or conceal paid calls.
- **Incomplete provenance.** Existing saved configurations do not capture all code,
  prompt, dataset/catalog hashes and model effort. Add these to immutable runs.
- **Template freshness and concurrency.** `sim/database.py` returns an existing
  template without verifying catalog/schema hashes; `fresh` force-drops a deterministic
  name. Separate instances protect development data here, but parallel/repeated
  experiments need unique database names and validated templates.
- **Fairness has a sound base but needs a stronger contract.** `sim/engine.py` keys
  random draws by seed and stable pharmacy/product identifiers; `run.one` freshly
  populates the world. All contenders here use the same Params, world and travel
  table. However, response delays are configurable and historical runs differed
  (answers_after_min is now 1–3). Freeze and hash external event schedules and verify
  paired demand before comparisons; do not attribute response-delay changes to architecture.
- **Confidence intervals ignore seed clustering.** `evals/stats.py` resamples individual
  needs; `report.py` pools (seed, need) pairs. Preserve pairing and resample/account
  for simulation seeds in the final five-seed comparison. Report loading also keys
  rows by contender/model/prompt and (seed,need), allowing repeats to replace rows
  without a full configuration identity check.
- **Safety and language scores are heuristic.** Snapshot comparisons cover selected
  business tables/fields; script detection cannot distinguish English from Arabizi.
  Manual review remains necessary. A blank or failed turn must not be counted safe
  merely because it contains no forbidden text.

## Checkpoint decision and next steps

Retain the current architecture as the reference. The local foundation is ready
for repeatable free checks; the harness is **not ready for paid comparisons**.

Before paid work: separately repair run immutability/provenance, shared budget
reservation and interruption accounting, scoring defects, template freshness and
paired comparison validation. Save pre-repair evidence (this folder), then rerun
all contenders on the same repaired infrastructure. Resolve the browser test host
and add the scripted full-journey fixture; execute all missing browser journeys.
Review dependency findings independently of architecture work.

Only after the next stage is authorized: baseline <=$4, screening <=$6, expanded
paired runs <=$10, final held-out <=$3, retries <=$2, aggregate <=$25 including
client-model calls/retries/in-flight reservations. Do not create architecture
variants or open held-out cases at this checkpoint. Preserve the original agent,
keep all future cases/settings/worlds paired, and retain incomplete runs explicitly.

## Reproduction and lifecycle

From repository root:

```sh
docker compose -f eval/checkpoints/2026-11-18-baseline/compose.yaml up -d --wait
python3 eval/checkpoints/2026-11-18-baseline/check.py NEW-NAME backend pytest
```

`check.py NAME backend|frontend COMMAND...` sets isolated environment variables,
saves the exact argv/stdout/stderr/exit/duration, and refuses to overwrite a log.
Use a new evidence name for every retry. `prepare.py` refuses to reseed a populated
demo world. `free_sims.py` refuses an existing output root. For a new checkpoint,
create a new folder/project/ports rather than overwriting this evidence.
Dependencies: `cd backend && UV_CACHE_DIR=/tmp/dawalink-eval-uv uv sync --frozen`;
frontend: Node 24.21.0, `npm ci --cache /tmp/dawalink-eval-npm`.
No root `.env` is required or loaded.

The database and mail-catcher can be stopped without deleting their volume:
`docker compose -f eval/checkpoints/2026-11-18-baseline/compose.yaml stop`.
Their synthetic credentials are in local.env. They must never be reused outside
this disposable local environment.

At checkpoint end, temporary API/frontend processes and isolated containers are stopped. The database volume, captured mail container and all evidence are retained.
