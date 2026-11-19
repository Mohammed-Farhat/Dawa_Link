"""Build an exact command index without changing saved results."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
lines = ["# Executed commands and failure inventory", "",
         "Run from repository root: `python3 eval/checkpoints/2026-11-18-reconciliation/check.py NEW-NAME backend|frontend COMMAND...`.", "",
         "The wrapper strips inherited provider/database settings, loads only synthetic local.env, and refuses existing evidence files. "
         "Arguments below run in the indicated repository subdirectory. No command in this checkpoint supplied a paid provider key. "
         "Database/container commands require local sandbox permission. Each output starts with the exact directory and argument vector.", "",
         "| Evidence | Directory | Exact argument vector | Exit | Seconds |",
         "|---|---|---|---:|---:|"]
indexed = set()
failures = []
for path in sorted(EVIDENCE.glob("*.json")):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or "command" not in data or "exit_code" not in data:
        continue
    name = path.name.removesuffix(".command.json").removesuffix(".json")
    output = name + ".txt"
    indexed.add(output)
    command = json.dumps(data["command"], ensure_ascii=False).replace("|", "&#124;")
    lines.append(f"| [{name}](evidence/{output}) | {data['cwd']} | `{command}` | {data['exit_code']} | {data['seconds']} |")
    if data["exit_code"]:
        failures.append((name, data["exit_code"]))
lines += ["", "## Nonzero outcomes", "",
          "Nonzero commands are retained below, including expected negative controls and intentional server shutdowns. "
          "Intermediate failures were fixed and later successful checks are also indexed. See REPORT.md for unresolved gaps.", ""]
for name, code in failures:
    lines.append(f"- [{name}](evidence/{name}.txt): exit {code}.")
lines += ["", "The logout reproduction intentionally failed before the fix; 204/503 regressions then passed. "
          "Browser API/frontend SIGTERM exits -15/143 are intentional cleanup. browser-api-r2 exited 3 because the prior server still held the port; "
          "the subsequent restart succeeded. reviewed-entrypoint-no-key deliberately refused missing credentials and saved an incomplete run with no new calls. "
          "Its import double-load warning was subsequently fixed and the free dispatch run passed.", "",
          "## Outputs without completed wrapper metadata", ""]
orphans = []
for path in sorted(EVIDENCE.glob("*.txt")):
    if path.name in indexed:
        continue
    content = path.read_text()
    header = content.splitlines()[:2]
    if header and header[0].startswith("cwd:"):
        orphans.append(path.name)
        lines.append(f"- [{path.stem}](evidence/{path.name}): " + " / ".join(f"`{h}`" for h in header) + ".")
lines += ["", "Missing metadata is not silently treated as an executed pass. The development-label-audit report was written successfully "
          "but the original wrapper then collided with that report filename, leaving no completed wrapper metadata. The report and command output are preserved. "
          "Metadata now uses .command.json. Initial account/lint/type/format failures and every retry remain saved.", "",
          "Native Safari operations are recorded in [browser-journeys.md](evidence/browser-journeys.md); they were UI actions rather than shell commands. "
          "The fixture/clock commands appear in the table. No provider billing reconciliation or paid rerun was executed.", "",
          "Sealing commands, from repository root: `python3 eval/checkpoints/2026-11-18-reconciliation/index_checks.py` "
          "writes this new index and evidence-hashes.json exclusively. The source script is preserved. Existing checkpoint files and result folders are not rewritten."]
with (HERE / "CHECKS.md").open("x") as out:
    out.write("\n".join(lines) + "\n")
hashes = {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(HERE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts
          and p.name != "local.env"}
with (EVIDENCE / "evidence-hashes.json").open("x") as out:
    json.dump(hashes, out, indent=2)
print("CHECKS.md created;", len(indexed), "commands,", len(orphans), "unindexed logs; artifact hashes saved.")
