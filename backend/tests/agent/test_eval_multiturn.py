"""Exercise the fixed multi-turn runner through the real agent and disposable DB."""

from pathlib import Path
from types import SimpleNamespace

from dawalink.agent.llm.scripted import reply
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import read
from dawalink.evals.run_multiturn import CASES, MCase, converse
from dawalink.sim.save import FileTracer
from tests.agent.conftest import Scene


def test_one_chat_keeps_all_fixed_client_turns_and_raw_evidence(
    scene: Scene, tmp_path: Path
) -> None:
    case = read(CASES, MCase)[0]
    agent = scene.agent(
        reply("Car or on foot? Which day and how many days?"),
        reply("Which pickup day and for how many days?"),
        reply("For how many days?"),
        reply("Please review the options."),
        tracer=FileTracer(tmp_path),
    )
    who = SimpleNamespace(id=scene.client, lat=33.8961, lon=35.4832)
    row = converse(agent, case, who, tmp_path, CatalogNames(()), 89500)
    assert row["outcome"] == "ok"  # execution completed, separate from quality
    assert [e["client"] for e in row["exchanges"]] == [s.text for s in case.turns]
    assert all(e["checks"]["clarifies_before_action"] for e in row["exchanges"][:3])
    assert row["exchanges"][-1]["checks"]["gives_proposal"] is False
    assert len((tmp_path / "turns.jsonl").read_text().splitlines()) == 4
    assert all("review" in e and "gold" in e for e in row["exchanges"])
