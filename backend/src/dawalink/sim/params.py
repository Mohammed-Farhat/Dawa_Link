"""The simulation's assumptions, in one place (docs/08 §2.4).

Nobody measured how pharmacies and clients in Lebanon really behave on DawaLink: it
doesn't exist yet. Every number here is a **stated assumption**, with a base value, and
suite E6 runs the same day again with other values to show how much the conclusions
depend on it.
"""

from dataclasses import dataclass
from datetime import date, time, timedelta


@dataclass(frozen=True)
class Params:
    # --- the day ---
    day: date = date(2026, 11, 16)  # a Monday: every pharmacy is open
    first_request: time = time(8, 0)  # request hours (R-T3)
    last_request: time = time(20, 0)
    requests: int = 100
    tick: timedelta = timedelta(minutes=5)  # how often the worker's clock check runs

    # --- pharmacies (docs/08 §2.4) ---
    not_available: float = 0.10  # a reservation whose box was already gone
    answers_ask: float = 0.60  # answers an early-release ask within its 2 hours
    accepts_ask: float = 0.50  # releases the box, given that it answered
    new_listings_per_pharmacy: float = 6.0  # about one every 2 hours of the day
    # The share of a shelf that is 181 to 270 days from expiry: private, but a pharmacy
    # may release it when asked (decision log BLD-D22).
    early_release_share: float = 0.25

    # --- clients (docs/08 §2.4) ---
    taps_card: float = 0.90
    accepts_offer: float = 0.80
    react_after_min: tuple[int, int] = (5, 30)  # how long a client takes to tap
    # How long a client takes to answer a question of the agent: they have just written
    # and are still in the chat (the owner, 2026-11-15, build plan Q35; it was 5 to 30).
    answers_after_min: tuple[int, int] = (1, 3)
    # Shown another brand (BLD-D17): thanks and stops, asks to reserve it, keeps looking.
    other_brand_reserve: float = 0.40
    other_brand_keep_looking: float = 0.20
    # Who writes a sentence about themselves, and who writes again later.
    says_preference: float = 0.30
    writes_again: float = 0.15
    hears_other_brands: float = 0.50  # agreed to hear about other brands
    has_budget: float = 0.20

    def but(self, **changes: object) -> "Params":
        """The same assumptions with some changed: what a sweep of E6 does."""
        values = {**self.__dict__, **changes}
        return Params(**values)
