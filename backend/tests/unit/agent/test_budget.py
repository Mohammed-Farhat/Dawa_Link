import pytest

from dawalink.agent.guards.budget import explicit_budget


@pytest.mark.parametrize(
    ("messages", "amount", "currency"),
    [
        (["My budget is 300,000 LBP"], 300_000, "LBP"),
        (["بدي دواء، ميزانيتي ٣٠٠ ألف ليرة"], 300_000, "LBP"),
        (["mizaniyyte ta7t 400 alf lira"], 400_000, "LBP"),
        (["I can pay at most $4.50"], 4.5, "USD"),
        (["My maximum is 5 USD"], 5, "USD"),
        (["My budget is 300k LBP", "2 boxes", "Actually my budget is 500k LBP"], 500_000, "LBP"),
        (["Pharmacy One costs 300,000 LBP"], None, None),
        (["My budget is 4"], None, None),
        (["My budget is about 300k LBP"], None, None),
        (["My budget is 300k LBP if possible"], None, None),
        (["My budget is 400k LBP but this costs 500k LBP"], None, None),
    ],
)
def test_explicit_client_budget(
    messages: list[str], amount: float | None, currency: str | None
) -> None:
    result = explicit_budget(messages)
    if amount is None:
        assert result is None
    else:
        assert result is not None
        assert result.amount == amount
        assert result.currency == currency
