"""Prints a run's scenarios as text a person can read:
python -m dawalink.evals.scenarios.show <result folder> [part of an id] [--short] [--failed]

For each scenario: the conversation with the agent's tool calls, the checks, and the
judge's scores. `--failed` shows only the scenarios with a failed check or an error.
"""

import json
import sys
from pathlib import Path
from typing import Any


def text_of(row: dict[str, Any], *, short: bool = False) -> str:
    lines = [
        "=" * 100,
        f"{row['id']}  [{row['lang']}, run {row['rep']}, {row['kind']}]  "
        f"passed: {row.get('passed')}  error: {row.get('error')}",
        f"   {row['title']}",
    ]
    for entry in row.get("transcript") or []:
        if entry["who"] == "trace":
            lines.append(f"   ({entry['text']})")
            for tool in entry.get("tools") or []:
                arguments = json.dumps(tool["arguments"], ensure_ascii=False, default=str)
                result = "ok" if tool["ok"] else "FAILED"
                answer = tool["answer"][: 300 if short else 1500]
                lines.append(f"      tool {tool['name']}({arguments}) -> {result}: {answer}")
            continue
        lines.append(f"[{entry['at']}] {entry['who'].upper()}: {entry['text']}")
        lines += [f"      [card] {card}" for card in entry.get("cards") or []]
        if entry.get("quick_replies"):
            lines.append(f"      [quick replies] {' / '.join(entry['quick_replies'])}")
    lines.append("-- checks")
    for check in row.get("checks") or []:
        mark = "ok  " if check["ok"] else "FAIL"
        lines.append(
            f"   {mark} {check['level']:11s} {check['family']:14s} {check['id']}  {check['detail']}"
        )
    for check in row.get("auto_checks") or []:
        if not check["ok"]:
            lines.append(f"   AUTO FAIL {check['id']}  {check['detail']}")
    verdict = row.get("judge")
    if verdict:
        error = verdict.get("error") or ""
        lines.append(f"-- judge {verdict['scores']}  accepted: {verdict['passed']}  {error}")
        lines += [f"   {name}: {why}" for name, why in verdict["reasons"].items()]
        lines += [
            f"   PROBLEM [{p.get('layer')}/{p.get('severity')}] {p.get('what')}"
            for p in verdict["problems"]
        ]
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    arguments = [word for word in sys.argv[1:] if not word.startswith("--")]
    if not arguments:
        print((__doc__ or "").strip())
        raise SystemExit(2)
    folder, want = Path(arguments[0]), (arguments[1] if len(arguments) > 1 else "")
    for line in (folder / "scenarios.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if want not in row["id"]:
            continue
        failed = row.get("error") or not row.get("passed")
        if "--failed" in sys.argv and not failed:
            continue
        print(text_of(row, short="--short" in sys.argv))


if __name__ == "__main__":
    main()
