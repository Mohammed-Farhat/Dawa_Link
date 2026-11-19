"""Read-only publication checks; never print credential values."""
import hashlib
import io
import json
import re
import sqlite3
import subprocess
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HANDOFF = "DawaLink_Roadmap_and_Database_Handoff.md"
names = subprocess.check_output(
    ["git", "ls-files", "--modified", "--others", "--exclude-standard", "-z"], cwd=ROOT
).decode().split("\0")
paths = sorted(set(name for name in names if name and name != HANDOFF))
secrets = []
for line in (ROOT / ".env").read_text().splitlines():
    key, sep, value = line.partition("=")
    if sep and key in ("ANTHROPIC_API_KEY", "ORS_API_KEY", "LANGFUSE_SECRET_KEY"):
        value = value.strip().strip("\"'")
        if len(value) > 20:
            secrets.append(value.encode())
assert secrets
pattern = re.compile(rb"(?:sk-ant-[A-Za-z0-9_-]{30,}|sk-lf-[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
bad = []
archives = 0
def scan(label, data):
    if any(secret in data for secret in secrets) or pattern.search(data):
        bad.append(label)
for name in paths:
    path = ROOT / name
    assert not path.is_symlink(), name
    assert path.name != "local.env" and not name.startswith(("backend/data/moph/", "backend/data/osm/"))
    data = path.read_bytes()
    scan(name, data)
    if name.endswith(".tar.gz"):
        archives += 1
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                assert member.isfile() and not member.name.startswith("/") and ".." not in Path(member.name).parts
                assert ".env" not in Path(member.name).parts
                scan(name + ":" + member.name, archive.extractfile(member).read())
assert not bad, "credential candidates in files: " + repr(bad)
old = json.loads((HERE.parent / "2026-11-18-reconciliation/evidence/final-integrity-v2.json").read_text())
assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
           for name, value in old["run_files_sha256"].items())
assert hashlib.sha256((ROOT / HANDOFF).read_bytes()).hexdigest() == old["handoff_sha256"]
def rows(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        return db.execute("SELECT * FROM calls ORDER BY id").fetchall()
assert rows(ROOT / "eval/experiments/architecture-20261118/budget.sqlite") == rows(
    HERE.parent / "2026-11-18-reconciliation/evidence/ledger-before.sqlite")
result = {"files_scanned": len(paths), "source_archives_inspected": archives,
          "configured_credentials_and_token_patterns": "clean", "old_run_hashes_verified": True,
          "handoff_unchanged_excluded": True, "ledger_call_rows_unchanged": True,
          "paths": paths}
with (HERE / "evidence/publication-audit.json").open("x") as out:
    json.dump(result, out, indent=2)
print("Publication audit passed:", len(paths), "files,", archives, "source archives; original evidence preserved.")
