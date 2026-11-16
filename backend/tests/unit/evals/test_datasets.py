"""The evaluation datasets: the format, the medicine names, and the files as committed
(docs/08 §2). Each rule has a case that must be refused."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dawalink.evals import catalog_match, validate
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import DATASETS, DatasetError, Gold, Match, RCase, UCase, read


def u_case(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "U-0001",
        "lang": "arabizi",
        "category": "clear",
        "text": "baddi concor 5",
        "gold": {
            "intent": "find",
            "items": [{"match": {"name": "concor", "strength": "5mg"}}],
            "expected": "propose_options",
        },
        "author": "test",
    }
    return case | changes


def write(path: Path, *cases: dict[str, Any] | str) -> Path:
    lines = [case if isinstance(case, str) else json.dumps(case) for case in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestTheFormat:
    def test_a_file_is_read_with_its_comments_skipped(self, tmp_path: Path) -> None:
        file = write(tmp_path / "u.jsonl", "// a comment", u_case(), "", u_case(id="U-0002"))

        cases = read(file, UCase)

        assert [case.id for case in cases] == ["U-0001", "U-0002"]
        assert cases[0].gold.items[0].qty == 1

    @pytest.mark.parametrize(
        ("line", "says"),
        [
            ("{not json", "line 1"),
            (json.dumps(u_case(id="U-1")), "line 1"),
            (json.dumps(u_case(surprise=1)), "line 1"),
            (json.dumps(u_case(lang="french")), "line 1"),
        ],
    )
    def test_a_bad_line_is_named(self, tmp_path: Path, line: str, says: str) -> None:
        with pytest.raises(DatasetError, match=says):
            read(write(tmp_path / "u.jsonl", line), UCase)

    def test_an_id_is_used_once(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetError, match="U-0001 is used twice"):
            read(write(tmp_path / "u.jsonl", u_case(), u_case()), UCase)

    @pytest.mark.parametrize(
        "gold",
        [
            {"intent": "find", "expected": "propose_options"},  # no medicine named
            {
                "intent": "find",
                "items": [{"match": {"name": "concor"}}],
                "expected": "propose_plan",  # a plan is for several
            },
            {"intent": "clinical", "expected": "refuse_clinical"},  # not marked clinical
            {"intent": "find", "situation": ["free_after"], "expected": "ask"},  # no hour
            {"intent": "find", "free_before_hour": 9, "expected": "ask"},  # an hour alone
            {"intent": "find", "pickup_in_days": 5, "expected": "ask"},  # 3 open days at most
        ],
    )
    def test_a_label_that_contradicts_itself_is_refused(self, gold: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            Gold.model_validate(gold)

    def test_a_safety_case_needs_a_check_and_a_place(self) -> None:
        case = {"id": "R-0001", "lang": "english", "category": "clinical", "author": "test"}

        ok = RCase.model_validate(case | {"text": "x", "checks": ["no_clinical_advice"]})

        assert ok.where == ["chat"]
        assert ok.setup == "none"
        for bad in ({"text": "x", "checks": []}, {"text": "x", "checks": ["made_up"]}):
            with pytest.raises(ValidationError):
                RCase.model_validate(case | bad)


def names(*rows: tuple[str, str | None, str | None]) -> tuple[CatalogNames, list[uuid.UUID]]:
    ids = [uuid.uuid4() for _ in rows]
    catalog = CatalogNames(
        tuple(
            (product_id, name, "".join((strength or "").lower().split()), (form or "").lower())
            for product_id, (name, strength, form) in zip(ids, rows, strict=True)
        )
    )
    return catalog, ids


class TestNamingAMedicine:
    """Invented products: the Ministry's list is never in a test."""

    def test_the_name_is_the_whole_name(self) -> None:
        catalog, (plain, _plus) = names(
            ("zorvex", "5mg", "Tablet"), ("zorvex plus", None, "Tablet")
        )

        assert catalog.products_for(Match(name="Zorvex")) == [plain]

    def test_the_strength_and_the_form_narrow_it(self) -> None:
        catalog, (five, ten, syrup) = names(
            ("zorvex", "5 mg", "Tablet, film coated"),
            ("zorvex", "10mg", "Tablet, film coated"),
            ("zorvex", "5mg", "Syrup"),
        )

        assert catalog.products_for(Match(name="zorvex")) == [five, ten, syrup]
        assert catalog.products_for(Match(name="zorvex", strength="5mg")) == [five, syrup]
        assert catalog.products_for(Match(name="zorvex", strength="5MG", form="tablet")) == [five]
        assert catalog.products_for(Match(name="zorvex", strength="20mg")) == []

    def test_a_label_that_fits_nothing_or_too_much_is_reported(self) -> None:
        many = [("commonex", f"{n}mg", "Tablet") for n in range(13)]
        catalog, _ = names(("zorvex", "5mg", "Tablet"), *many)
        cases = [
            UCase.model_validate(u_case()),  # concor: not in this catalog
            UCase.model_validate(
                u_case(
                    id="U-0002",
                    gold={
                        "intent": "find",
                        "items": [{"match": {"name": "commonex"}}],
                        "expected": "propose_options",
                    },
                )
            ),
            UCase.model_validate(
                u_case(
                    id="U-0003",
                    gold={
                        "intent": "find",
                        "items": [{"match": {"name": "zorvex"}}],
                        "expected": "propose_options",
                    },
                )
            ),
        ]

        found = catalog_match.problems(catalog, cases)

        assert [line.split(":")[0] for line in found] == ["U-0001", "U-0002"]
        assert "no product" in found[0]
        assert "13 products" in found[1]


class TestTheCommittedFiles:
    def test_the_development_files_are_well_formed(self) -> None:
        """The format only: the names are checked against the catalog by the command."""
        assert validate.check(DATASETS, with_catalog=False) == []

    def test_no_case_holds_a_catalog_id_an_email_or_a_phone_number(self) -> None:
        """The datasets are in a public repository (BLD-D3, G-7)."""
        for name in ("understanding.jsonl", "safety.jsonl"):
            text = (DATASETS / name).read_text(encoding="utf-8")
            assert "@" not in text, name
            assert "+961" not in text, name
            assert "product_id" not in text, name
