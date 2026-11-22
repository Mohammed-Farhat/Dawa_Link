"""Append case outcomes before the next paid case; stop at case boundaries on request."""

import json
import os
from pathlib import Path
from typing import Any


def stop_requested() -> bool:
    path = os.environ.get("EVAL_STOP_FILE")
    return bool(path and Path(path).exists())


def save_case(folder: Path, row: dict[str, Any]) -> None:
    """The run folder is unique. Final summaries never replace this incremental stream."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "case-checkpoints.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
