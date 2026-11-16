"""The evaluation's statistics and its report (docs/08 §4, §5)."""

import json
from pathlib import Path
from typing import Any

import pytest

from dawalink.evals import report, stats
from dawalink.sim.params import Params


class TestTheStatistics:
    def test_a_share_lies_inside_its_interval_and_is_the_same_twice(self) -> None:
        got = [1.0, 0.0, 2.0, 1.0, 0.0, 3.0, 1.0, 1.0]
        wanted = [1.0, 1.0, 2.0, 2.0, 1.0, 3.0, 1.0, 2.0]

        one, again = stats.share(got, wanted), stats.share(got, wanted)

        assert one.value == pytest.approx(9 / 13)
        assert one.low <= one.value <= one.high
        assert 0 <= one.low < one.high <= 1
        assert one == again

    def test_more_cases_make_a_narrower_interval(self) -> None:
        few = stats.share([1.0, 0.0] * 5, [1.0] * 10)
        many = stats.share([1.0, 0.0] * 200, [1.0] * 400)

        assert many.high - many.low < few.high - few.low

    def test_a_paired_difference_sees_what_two_separate_intervals_hide(self) -> None:
        """The second contender gets one unit less on every fourth client, and never more.
        Their own intervals overlap widely; on the same clients the difference is clear."""
        wanted = [2.0] * 80
        first = [2.0, 0.0, 1.0, 2.0] * 20
        second = [2.0, 0.0, 1.0, 1.0] * 20

        gap = stats.difference(first, second, wanted)

        assert gap.value == pytest.approx(20 / 160)
        assert gap.excludes_zero
        assert stats.share(second, wanted).high > stats.share(first, wanted).low
        assert not stats.difference(first, first, wanted).excludes_zero

    def test_the_two_contenders_must_have_served_the_same_cases(self) -> None:
        with pytest.raises(ValueError, match="same cases"):
            stats.difference([1.0], [1.0, 1.0], [1.0])


def save_day(results: Path, name: str, secured: list[int], **config: Any) -> None:
    folder = results / name
    folder.mkdir()
    about = {"contender": name, "model": None, "prompt_version": None, "seed": 1} | config
    about["params"] = {"requests": Params().requests} | about.get("params", {})
    (folder / "config.json").write_text(json.dumps(about), encoding="utf-8")
    needs = [
        {"n": n, "units_wanted": 2, "units_secured": units, "fulfilled": units == 2}
        for n, units in enumerate(secured)
    ]
    (folder / "needs.jsonl").write_text(
        "".join(json.dumps(need) + "\n" for need in needs), encoding="utf-8"
    )


class TestTheReport:
    def test_contenders_are_compared_on_the_same_clients(self, tmp_path: Path) -> None:
        save_day(tmp_path, "search", [2, 2, 1, 2] * 25)
        save_day(tmp_path, "rules", [2, 1, 0, 2] * 25)

        (search, rules) = sorted(report.simulation_table(report.simulation(tmp_path))[2:])[::-1]

        assert "175 of 200" in search
        assert "125 of 200" in rules
        assert "-25.0%" in rules  # against search, and the interval excludes zero
        assert "not a clear difference" not in rules

    def test_a_pilot_and_a_sweep_are_not_a_full_day(self, tmp_path: Path) -> None:
        save_day(tmp_path, "search", [2] * Params().requests)
        save_day(tmp_path, "pilot", [2] * 10, contender="search", params={"requests": 10})
        save_day(
            tmp_path,
            "sweep",
            [0] * Params().requests,
            contender="search",
            params={"answers_ask": 0.2},
        )

        days = report.simulation(tmp_path)

        assert list(days) == ["search"]
        assert sum(need["units_secured"] for need in days["search"].values()) == 200

    def test_an_agents_day_is_named_by_its_model_and_prompt(self, tmp_path: Path) -> None:
        save_day(
            tmp_path, "day", [2] * 100, contender="agent", model="claude-x", prompt_version="v9"
        )

        assert list(report.simulation(tmp_path)) == ["agent (claude-x, prompt v9)"]

    def test_days_played_with_the_slower_answers_are_told_apart(self) -> None:
        """Build plan Q35: a client now answers a question within 1 to 3 minutes."""
        old = {"contender": "rules_asking", "params": {"requests": 100}}
        new = {"contender": "rules_asking", "params": {"answers_after_min": [1, 3]}}

        def agent(version: str) -> dict[str, Any]:
            return {"contender": "agent", "prompt_version": version, "params": {}}

        assert report._answered_slowly(old) is True
        assert report._answered_slowly(new) is False
        assert report._answered_slowly(agent("v1.10")) is True
        # Before prompt v1.9 the simulated client never answered: nothing to tell apart.
        assert report._answered_slowly(agent("v1.8")) is False
        assert report._answered_slowly({"contender": "search", "params": {}}) is False

    def test_a_run_of_conversations_is_a_column_of_its_table(self, tmp_path: Path) -> None:
        assert report.conversations_table(tmp_path) == ["No run of suite E7 is saved."]
        folder = tmp_path / "2026-11-15_conversations_dev_claude-x_prompt-v9"
        folder.mkdir()
        summary = {
            "conversations": 4,
            "agent_cost_usd": 0.02,
            "client_cost_usd": 0.004,
            "checks": {"gets_cards": {"cases": 4, "yes": 3, "share": 0.75}},
            "by_style": {
                "bare": {
                    "conversations": 2,
                    "ended_with_cards": 1,
                    "client_messages_to_cards": 2.0,
                }
            },
        }
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

        lines = report.conversations_table(tmp_path)

        assert lines[0] == "| Check | dev_claude-x_prompt-v9 |"
        assert "| gets_cards | 3 of 4 (75%) |" in lines
        assert "| asks_again (lower is better) | - |" in lines
        assert "| bare | 1 of 2 got cards, after 2.0 client messages |" in lines
        assert lines[-1] == "| conversations · cost (agent + playing model) | 4 · $0.020 + $0.004 |"

    def test_an_ablation_is_compared_with_the_whole_agent_on_the_same_prompt(
        self, tmp_path: Path
    ) -> None:
        setup = {"model": "claude-x", "prompt_version": "v9"}
        save_day(tmp_path, "whole", [2, 2, 1, 2] * 25, contender="agent", **setup)
        save_day(tmp_path, "less", [2, 1, 0, 2] * 25, contender="agent_without_planning", **setup)
        save_day(
            tmp_path,
            "older",
            [0] * 100,
            contender="agent",
            model="claude-x",
            prompt_version="v8",
        )

        days = report.simulation(tmp_path)
        (row,) = report.ablation_table(days)[2:]

        assert row.startswith("| planning (claude-x, prompt v9) | 1 | 125 of 200")
        assert "175 of 200" in row
        assert "+25.0%" in row
        # The ablation is not a contender of the main table.
        assert not any("without" in line for line in report.simulation_table(days))
        assert report.ablation_table({}) == ["No ablation day is saved."]

    def test_the_chart_has_a_bar_and_an_interval_for_every_contender(self, tmp_path: Path) -> None:
        save_day(tmp_path, "search", [2, 2, 1, 2] * 25)
        save_day(tmp_path, "rules", [2, 1, 0, 2] * 25)

        chart = report.simulation_chart(report.simulation(tmp_path))

        assert chart.startswith("<svg")
        assert chart.rstrip().endswith("</svg>")
        assert ">search</text>" in chart
        assert ">rules</text>" in chart
        assert ">88%</text>" in chart
        assert ">62%</text>" in chart
        assert chart.count("<rect") == 3  # the background and one bar each

    def test_the_whole_report_is_written_from_whatever_is_saved(self, tmp_path: Path) -> None:
        text = report.report(tmp_path)

        assert "## The simulation (E2)" in text
        assert "No run of suite E1 is saved." in text
        assert "No run of suite E4 is saved." in text
