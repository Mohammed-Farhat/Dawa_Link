"""How amounts, times and days are written for the model and on cards (docs/07 §4.1).

The model never computes a price, a currency conversion or a date: it is given them
already written, in Beirut time and in LBP with the USD amount beside it.
"""

from datetime import date, datetime
from decimal import Decimal

from dawalink.agent.state import Money
from dawalink.domain.clock import beirut
from dawalink.domain.money import to_lbp, usd_approx
from dawalink.services.errors import Code, ServiceError


def money(amount_lbp: int, lbp_per_usd: Decimal | None) -> str:
    """ "716,000 LBP (about $8.00)", or without the USD part when no rate is known."""
    text = f"{amount_lbp:,} LBP"
    if lbp_per_usd:
        text += f" (about ${usd_approx(amount_lbp, int(lbp_per_usd)):,.2f})"
    return text


def when(moment: datetime) -> str:
    """ "Tue 21:00", in Beirut time."""
    return beirut(moment).strftime("%a %H:%M")


def day(value: date) -> str:
    """ "Thu 12 Nov"."""
    return f"{value:%a} {value.day} {value:%b}"


def in_lbp(amount: Money | None, lbp_per_usd: Decimal | None) -> int | None:
    """A budget the client gave in either currency, in whole LBP (R-C3)."""
    if amount is None:
        return None
    if amount.currency == "USD" and not lbp_per_usd:
        raise ServiceError(Code.VALIDATION_ERROR, "No exchange rate is known for USD amounts.")
    return to_lbp(Decimal(str(amount.amount)), amount.currency, int(lbp_per_usd or 1))
