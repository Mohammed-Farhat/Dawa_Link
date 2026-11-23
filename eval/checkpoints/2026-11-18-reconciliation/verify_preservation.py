"""Verify immutable previous results and save final local source/input provenance."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
old = json.loads((HERE.parent / "2026-11-18-readiness/evidence/integrity.json").read_text())
failures = [name for name, digest in old["run_files_sha256"].items()
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
handoff = hashlib.sha256((ROOT / "DawaLink_Roadmap_and_Database_Handoff.md").read_bytes()).hexdigest()
assert not failures and handoff == old["handoff_sha256"]
paths = [p for base in ("backend/src", "backend/tests", "backend/migrations", "frontend/src", "eval/datasets", "eval/world")
         for p in (ROOT / base).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
paths += [ROOT / p for p in ("backend/uv.lock", "frontend/package-lock.json",
                            "backend/data/moph/catalog.csv", "backend/data/catalog_overrides.toml")]
report = {"old_run_files_verified": len(old["run_files_sha256"]), "failures": failures,
          "handoff_sha256": handoff, "source_and_inputs_sha256": {
              str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(paths) if p.exists()}}
with (HERE / "evidence/final-integrity.json").open("x") as stream:
    json.dump(report, stream, indent=2)
with (HERE / "evidence/final-code.diff").open("xb") as stream:
    stream.write(subprocess.check_output(["git", "diff", "--", "backend", "frontend"], cwd=ROOT))
print("Historical run files verified:", report["old_run_files_verified"])
print("Handoff checksum unchanged; current source/input hashes saved")
