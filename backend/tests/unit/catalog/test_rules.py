"""The team's catalog rules: controlled medicines, the no-prescription list, corrections."""

from pathlib import Path

import pytest

from dawalink.catalog.composition import parse_ingredients
from dawalink.catalog.rules import CatalogRules, ProductOverride, load_rules, rules_from

RULES = rules_from(
    {
        "controlled": {"atc_prefixes": ["N02A", "n05ba"], "ingredients": ["Codeine", "tramadol"]},
        "otc": {"ingredients": ["paracetamol", "caffeine"]},
        "products": {"101": {"controlled": True}, "102": {"equivalence_key": ""}},
    }
)


def controlled(atc: str, ingredients: str, rules: CatalogRules = RULES) -> bool:
    return rules.is_controlled(atc, parse_ingredients(ingredients))


class TestControlled:
    """R-C6: when in doubt, a medicine is controlled."""

    @pytest.mark.parametrize("atc", ["N02AA01", "N02AJ06", "N05BA12", "n02ax02"])
    def test_by_its_atc_class(self, atc: str) -> None:
        assert controlled(atc, "Something else - 5mg")

    def test_by_one_ingredient_among_several(self) -> None:
        assert controlled("R05DA04", "Paracetamol - 500mg, Codeine phosphate - 30mg")
        assert controlled("", "Tramadol HCl - 50mg")

    def test_an_ingredient_must_match_a_whole_word(self) -> None:
        assert not controlled("R05DA09", "Dextromethorphan HBr - 15mg")
        assert not controlled("N02BE01", "Paracetamol - 500mg")

    def test_no_rules_flag_nothing(self) -> None:
        assert not controlled("N02AA01", "Morphine sulfate - 10mg", CatalogRules())


class TestPrescriptionNotice:
    """R-C7: the notice shows unless every ingredient is on the no-prescription list."""

    def test_it_shows_by_default(self) -> None:
        assert RULES.needs_prescription(parse_ingredients("Amoxicillin - 500mg"))
        assert RULES.needs_prescription([])

    def test_it_is_dropped_only_when_every_ingredient_is_listed(self) -> None:
        assert not RULES.needs_prescription(parse_ingredients("Paracetamol - 500mg"))
        assert not RULES.needs_prescription(
            parse_ingredients("Paracetamol - 500mg, Caffeine - 65mg")
        )
        assert RULES.needs_prescription(parse_ingredients("Paracetamol - 500mg, Codeine - 30mg"))

    def test_an_empty_list_keeps_the_notice_on_everything(self) -> None:
        assert CatalogRules().needs_prescription(parse_ingredients("Paracetamol - 500mg"))


def test_corrections_are_read_by_the_ministrys_code() -> None:
    assert RULES.products[101] == ProductOverride(controlled=True)
    assert RULES.products[102].equivalence_key == ""


class TestTheCommittedRulesFile:
    rules = load_rules(Path("data/catalog_overrides.toml"))

    @pytest.mark.parametrize(
        ("atc", "ingredients"),
        [
            ("N02AA01", "Morphine sulfate - 10mg"),
            ("N02AX02", "Tramadol HCl - 50mg"),
            ("N05BA12", "Alprazolam - 0.5mg"),
            ("N05CF02", "Zolpidem (tartrate) - 10mg"),
            ("N06BA04", "Methylphenidate HCl - 10mg"),
            ("N03AE01", "Clonazepam - 2mg"),
            ("N02BF02", "Pregabalin - 75mg"),
            ("N02AJ06", "Paracetamol - 500mg, Codeine phosphate - 30mg"),
            ("N01AX03", "Ketamine HCl - 50mg/ml"),
            ("N03AA02", "Phenobarbital - 100mg"),
        ],
    )
    def test_it_flags_the_well_known_controlled_medicines(self, atc: str, ingredients: str) -> None:
        assert self.rules.is_controlled(atc, parse_ingredients(ingredients))

    @pytest.mark.parametrize(
        ("atc", "ingredients"),
        [
            ("N02BE01", "Paracetamol - 500mg"),
            ("J01CR02", "Amoxicillin - 875mg, Clavulanic acid - 125mg"),
            ("C07AB07", "Bisoprolol fumarate - 5mg"),
            ("A10BA02", "Metformin HCl - 850mg"),
            ("B01AC06", "Acetylsalicylic acid - 100mg"),
        ],
    )
    def test_it_leaves_everyday_medicines_alone(self, atc: str, ingredients: str) -> None:
        assert not self.rules.is_controlled(atc, parse_ingredients(ingredients))

    def test_the_no_prescription_list_starts_empty(self) -> None:
        """Until the team fills it, every product shows the notice."""
        assert self.rules.otc_ingredients == frozenset()
