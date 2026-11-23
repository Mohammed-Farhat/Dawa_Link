"""Index successful integration checks and preserve exact evidence hashes."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EVIDENCE = HERE / "evidence"
old_folder = HERE.parent / "2026-11-18-reconciliation"
old = json.loads((old_folder / "evidence/evidence-hashes.json").read_text())
assert all(hashlib.sha256((old_folder / path).read_bytes()).hexdigest() == value
           for path, value in old.items())
lines = ["# Integration check commands", "",
         "From repository root, use `python3 eval/checkpoints/2026-11-19-git-integration/check.py NEW-NAME backend|frontend COMMAND...`. "
         "Only synthetic ignored local.env is loaded, provider keys stripped, output files exclusive. No paid evaluations.", "",
         "| Evidence | Directory | Exact argument vector | Exit | Seconds |",
         "|---|---|---|---:|---:|"]
for path in sorted(EVIDENCE.glob("*.command.json")):
    data = json.loads(path.read_text())
    name = path.name.removesuffix(".command.json")
    assert data["exit_code"] == 0, name
    command = json.dumps(data["command"], ensure_ascii=False).replace("|", "&#124;")
    lines.append(f"| [{name}](evidence/{name}.txt) | {data['cwd']} | `{command}` | {data['exit_code']} | {data['seconds']} |")
lines += ["", "Git operations in order (repository root):", "",
          "1. `git fetch origin --prune` (first approval timed out; one retry succeeded).",
          "2. Separate `git add -- <explicit paths>` and commits: `Fix logout session state`; "
          "`Harden evaluation scoring and budget tracking`; `Save baseline evidence and readiness findings`.",
          "3. `git merge --no-ff --no-commit origin/main` reported two conflicts (exit 1). "
          "Resolved SessionProvider and simulation/database.py; staged only the resolutions. Other upstream changes retained.",
          "4. After tests, `git fetch origin --prune` confirmed `origin/main` still at `28cf4f1`. "
          "`git diff --check -- backend frontend docs .gitignore` and its cached form passed; "
          "`git diff --name-only --diff-filter=U` is empty. Raw terminal evidence retains its original whitespace.",
          "5. `python3 eval/checkpoints/2026-11-19-git-integration/seal.py` indexes these results and verifies "
          "all 209 earlier checkpoint artifact hashes without rewriting them.",
          "6. Final merge commit: `git commit -m 'Merge main into evaluation branch'`. "
          "Publication uses `git push --set-upstream origin test/agent-evaluation`; no force or main push. "
          "Confirm with `git ls-remote origin refs/heads/test/agent-evaluation refs/heads/main` and local status/log.", "",
          "Initial staged whitespace scan flagged only unchanged captured terminal whitespace. Those outputs were preserved, "
          "and source checks were scoped explicitly. No failed tests or scoring controls were suppressed. "
          "Browser journeys were not repeated; prior browser findings are historical."]
with (HERE / "CHECKS.md").open("x") as out:
    out.write("\n".join(lines) + "\n")
hashes = {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(HERE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.name != "local.env"}
with (EVIDENCE / "evidence-hashes.json").open("x") as out:
    json.dump({"previous_checkpoint_files_verified": len(old), "sha256": hashes,
               "merge_base_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "incoming_main": subprocess.check_output(["git", "rev-parse", "MERGE_HEAD"], cwd=ROOT, text=True).strip()}, out, indent=2)
print("Saved command index and", len(hashes), "artifact hashes; verified", len(old), "previous artifacts.")
