"""Ingredients, form groups and "the same medicine" (docs/04 R-C5).

The rule errs on the side of not matching: a wrong equivalent could hurt someone.
"""

from decimal import Decimal

import pytest

from dawalink.catalog.composition import (
    equivalence_key,
    form_group,
    normalize,
    parse_ingredients,
)


def key(ingredients: str, form: str, atc: str | None = "N02BE01") -> str | None:
    return equivalence_key(parse_ingredients(ingredients), form_group(form), atc)


class TestNormalize:
    def test_it_keeps_letters_and_digits_only(self) -> None:
        assert normalize("  AUGMENTIN® 1g / Comprimés  ") == "augmentin 1g comprimes"

    def test_empty_text_stays_empty(self) -> None:
        assert normalize(" - ") == ""


class TestIngredients:
    def test_one_ingredient_with_its_strength(self) -> None:
        (paracetamol,) = parse_ingredients("Paracetamol - 500mg")

        assert paracetamol.name == "Paracetamol"
        assert paracetamol.name_normalized == "paracetamol"
        assert (paracetamol.strength_value, paracetamol.strength_unit) == (Decimal(500), "mg")

    def test_several_ingredients(self) -> None:
        found = parse_ingredients("Candesartan cilexetil - 8mg, Amlodipine - 5mg")

        assert [i.name for i in found] == ["Candesartan cilexetil", "Amlodipine"]
        assert [i.strength_key for i in found] == ["8mg", "5mg"]

    def test_a_name_may_contain_a_comma(self) -> None:
        found = parse_ingredients(
            "Fibrinogen, human (clottable protein) (I) - 91mg/ml, "
            "Aprotinin, synthetic (I) - 3000KIU/ml"
        )

        assert [i.name for i in found] == [
            "Fibrinogen, human (clottable protein) (I)",
            "Aprotinin, synthetic (I)",
        ]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("1g", "1000mg"), ("1000mg", "1000mg"), ("500 mcg", "0.5mg"), ("0.5mg", "0.5mg")],
    )
    def test_mass_units_are_brought_to_milligrams(self, text: str, expected: str) -> None:
        (ingredient,) = parse_ingredients(f"Metformin HCl - {text}")

        assert ingredient.strength_key == expected

    def test_a_concentration_is_kept_exactly_as_written(self) -> None:
        (ingredient,) = parse_ingredients("Cefadroxil - 250mg/5ml")

        assert ingredient.strength_key == "250mg/5ml"
        assert ingredient.strength_value is None

    @pytest.mark.parametrize("strength", ["?2.5Lf/0.5ml", "", "as needed"])
    def test_a_strength_that_cannot_be_read_gives_no_key(self, strength: str) -> None:
        """A lost character or no number: the product gets no equivalents."""
        (ingredient,) = parse_ingredients(f"Tetanus toxoid - {strength}")

        assert ingredient.strength_key is None

    @pytest.mark.parametrize("text", ["Water for injection", "Sodium chloride 0.9%", "- 5mg"])
    def test_text_outside_the_pattern_is_one_ingredient_with_no_strength(self, text: str) -> None:
        (ingredient,) = parse_ingredients(text)

        assert ingredient.strength_key is None

    def test_nothing_gives_no_ingredients(self) -> None:
        assert parse_ingredients(None) == []
        assert parse_ingredients("   ") == []


class TestFormGroup:
    @pytest.mark.parametrize(
        "form",
        [
            "Tablet",
            "Tablet, film coated",
            "Tablet, coated",
            "Tablet, scored",
            "Tablet, sugar coated",
            "Caplet",
            "Caplet, film coated",
            "Tablet, film coated, scored",
        ],
    )
    def test_coating_variants_of_a_tablet_are_one_group(self, form: str) -> None:
        assert form_group(form) == "tablet"

    @pytest.mark.parametrize("form", ["Capsule", "Capsule, hard", "Capsule, soft gelatin"])
    def test_hard_and_soft_capsules_are_one_group(self, form: str) -> None:
        assert form_group(form) == "capsule"

    @pytest.mark.parametrize(
        ("form", "group"),
        [
            ("Tablet, prolonged release", "tablet_mr"),
            ("Tablet, extended release", "tablet_mr"),
            ("Tablet, modified release", "tablet_mr"),
            ("Capsule, prolonged release", "capsule_mr"),
            ("Tablet, enteric coated", "tablet_gr"),
            ("Tablet, gastroresistant", "tablet_gr"),
            ("Capsule, delayed release", "capsule_gr"),
            ("Capsule, hard, gastro-resistant", "capsule_gr"),
            ("Tablet, orodispersible", "tablet_orodispersible"),
            ("Tablet, effervescent", "tablet_effervescent"),
            ("Tablet, chewable", "tablet_chewable"),
            ("Capsule, inhalation", "capsule_inhalation"),
        ],
    )
    def test_a_different_release_or_use_is_never_merged(self, form: str, group: str) -> None:
        assert form_group(form) == group
        assert group not in ("tablet", "capsule")

    def test_every_other_form_is_a_group_of_its_own(self) -> None:
        assert form_group("Injectable solution") == "injectable_solution"
        assert form_group("Syrup") == "syrup"
        assert form_group("Tablet, vaginal") == "tablet_vaginal"

    def test_no_form_gives_no_group(self) -> None:
        assert form_group(None) is None
        assert form_group("  ") is None


class TestEquivalenceKey:
    def test_another_brand_of_the_same_medicine_has_the_same_key(self) -> None:
        assert key("Paracetamol - 500mg", "Tablet") == key(
            "Paracetamol - 500mg", "Tablet, film coated"
        )
        assert key("Paracetamol - 500mg", "Tablet") == "paracetamol=500mg | tablet | N02BE01"

    def test_the_order_of_the_ingredients_does_not_matter(self) -> None:
        assert key("Amlodipine - 5mg, Valsartan - 160mg", "Tablet") == key(
            "Valsartan - 160mg, Amlodipine - 5mg", "Tablet"
        )

    def test_the_way_a_salt_is_written_does_not_matter(self) -> None:
        assert key("Amlodipine (besylate) - 5mg", "Tablet") == key(
            "Amlodipine besylate - 5mg", "Tablet"
        )

    @pytest.mark.parametrize(
        ("one", "other"),
        [
            # a different strength
            (("Paracetamol - 500mg", "Tablet"), ("Paracetamol - 1g", "Tablet")),
            # modified release against immediate release
            (("Metformin HCl - 1g", "Tablet"), ("Metformin HCl - 1g", "Tablet, prolonged release")),
            # a different salt, or the salt not stated
            (("Diclofenac sodium - 50mg", "Tablet"), ("Diclofenac potassium - 50mg", "Tablet")),
            (("Amlodipine - 5mg", "Tablet"), ("Amlodipine (besylate) - 5mg", "Tablet")),
            # a different route or form
            (("Paracetamol - 500mg", "Tablet"), ("Paracetamol - 500mg", "Suppository")),
            (("Omeprazole - 20mg", "Capsule"), ("Omeprazole - 20mg", "Tablet")),
            # one more ingredient
            (("Paracetamol - 500mg", "Tablet"), ("Paracetamol - 500mg, Caffeine - 65mg", "Tablet")),
            # the same concentration written differently stays apart
            (("Cefadroxil - 250mg/5ml", "Suspension"), ("Cefadroxil - 50mg/ml", "Suspension")),
        ],
    )
    def test_anything_that_differs_gives_a_different_key(
        self, one: tuple[str, str], other: tuple[str, str]
    ) -> None:
        assert key(*one) is not None
        assert key(*one) != key(*other)

    @pytest.mark.parametrize(
        ("ingredients", "form", "one_use", "another_use"),
        [
            # eye drops against ear drops
            ("Ofloxacin - 3mg/ml", "Drops solution", "S01AE01", "S02AA16"),
            # a gel for the mouth against a gel for the skin
            ("Miconazole nitrate - 20mg/g", "Gel", "A01AB09", "D01AC02"),
            # an intermediate-acting insulin against a long-acting one
            ("Insulin human - 100IU/ml", "Injectable suspension", "A10AD01", "A10AE01"),
        ],
    )
    def test_the_same_ingredient_and_form_for_another_use_is_not_an_equivalent(
        self, ingredients: str, form: str, one_use: str, another_use: str
    ) -> None:
        """Found in the Ministry's real list: the form alone doesn't say what a product is for."""
        assert key(ingredients, form, one_use) is not None
        assert key(ingredients, form, one_use) != key(ingredients, form, another_use)
        assert key(ingredients, form, one_use) == key(ingredients, form, one_use.lower())

    def test_without_an_atc_code_there_are_no_equivalents(self) -> None:
        assert key("Paracetamol - 500mg", "Tablet", None) is None
        assert key("Paracetamol - 500mg", "Tablet", "  ") is None

    @pytest.mark.parametrize(
        ("ingredients", "form"),
        [
            ("", "Tablet"),
            ("Paracetamol - 500mg", ""),
            ("Water for injection", "Injectable solution"),
            ("Tetanus toxoid - ?5Lf/0.5ml", "Injectable suspension"),
            ("Paracetamol - 500mg, Codeine - ?", "Tablet"),
        ],
    )
    def test_anything_unreadable_has_no_equivalents(self, ingredients: str, form: str) -> None:
        assert key(ingredients, form) is None
