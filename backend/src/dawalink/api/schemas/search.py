"""The catalog, search results and reserving from them (docs/06 §5.3, §6.2, §6.3)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from dawalink.api.schemas.chat import LocationSummary
from dawalink.api.schemas.common import (
    MAX_SKIP,
    In,
    Lbp,
    LocationIn,
    Money,
    MoneyIn,
    Out,
    PharmacyCard,
    ProductSummary,
    Travel,
)


class Ingredient(Out):
    name: str
    strength: str | None


class ProductDetail(ProductSummary):
    ingredients: list[Ingredient]
    atc_code: str | None
    manufacturer: str | None


class Products(Out):
    items: list[ProductSummary]
    # Close names to offer when nothing matched well: "Did you mean Augmentin?"
    did_you_mean: list[str]


class Listing(Out):
    """One visible box a client can reserve (docs/04 SM-3)."""

    id: uuid.UUID
    product: ProductSummary
    pharmacy: PharmacyCard
    price: Money
    # What the client saves against the public price, for one pack.
    saving: Money
    discount_pct: int
    expiry_date: date
    days_left: int
    # Shown exactly up to 5, then "5+" (R-S5).
    available: int
    more_available: bool
    travel: Travel
    # Lasts the client's days of use. None: the client didn't say, so a warning shows.
    fits: bool | None
    # The days this box can be picked up and still last (R-F3).
    pickup_days_allowed: list[date]
    # The pharmacy accepts a later day, but the box wouldn't last from it (R-F6).
    expiry_limits_pickup: bool


class NoMatch(Out):
    """Boxes exist, but none lasts the client's days or can be had on their day (R-F4)."""

    latest_expiry: date
    latest_pickup_day: date | None


class SearchListings(In):
    """A search. **It is a POST so that the client's location travels in the body**, never
    in an address that a browser's history or a server's log keeps."""

    product_id: uuid.UUID
    # None: the profile's home district is used (R-S2).
    location: LocationIn | None = None
    days_of_use: int | None = Field(default=None, ge=1, le=365)
    pickup_day: date | None = None
    max_price: MoneyIn | None = None
    sort: Literal["best", "nearest", "cheapest", "latest_expiry"] = "best"
    on_foot: bool = False
    # Only pharmacies that are open at this moment.
    open_now: bool = False
    cursor: int = Field(default=0, ge=0, le=MAX_SKIP)
    limit: int = Field(default=20, ge=1, le=50)


class SearchResult(Out):
    product: ProductSummary
    items: list[Listing]
    total_found: int
    # Boxes that an earlier pickup day would add (R-F6).
    left_out_by_pickup_day: int
    no_match: NoMatch | None
    next_cursor: int | None
    # Where the travel times were counted from, in words.
    location: LocationSummary
    # The days a client may say they'll come, for the "Pick up" choice (N-49).
    upcoming_days: list[date]
    server_now: datetime


class SearchByName(In):
    """A search by a typed name: every medicine it stands for, with its boxes in stock.
    A POST for the same reason as `SearchListings`: the location travels in the body."""

    q: str = Field(min_length=1, max_length=100)
    location: LocationIn | None = None
    days_of_use: int | None = Field(default=None, ge=1, le=365)
    pickup_day: date | None = None
    max_price: MoneyIn | None = None
    sort: Literal["best", "nearest", "cheapest", "latest_expiry"] = "best"
    on_foot: bool = False
    # Only pharmacies that are open at this moment.
    open_now: bool = False
    # How many boxes each medicine shows; the medicine's own page has them all.
    per_medicine: int = Field(default=3, ge=1, le=5)


class MedicineGroup(Out):
    """One medicine of a search by name: a catalog product under its own name."""

    product: ProductSummary
    # It matched by what it contains, not by its name.
    by_ingredient: bool
    items: list[Listing]
    total_found: int
    no_match: NoMatch | None


class NameSearchResult(Out):
    groups: list[MedicineGroup]
    # No medicine is written exactly like `q`: these are the closest names.
    closest: bool
    did_you_mean: list[str]
    location: LocationSummary
    upcoming_days: list[date]
    server_now: datetime


class Searched(In):
    """A name the client searched, to keep in their list of last searches."""

    q: str = Field(min_length=1, max_length=100)


class Searches(Out):
    """The client's last searches, the newest first."""

    items: list[str]


class ViewListing(In):
    location: LocationIn | None = None
    days_of_use: int | None = Field(default=None, ge=1, le=365)


class DayHours(Out):
    day: date
    # "08:00-13:00, 16:00-21:00", or "closed".
    hours: str


class ListingDetail(Out):
    listing: Listing
    # The pharmacy's opening hours for the next 7 days, today first.
    week: list[DayHours]
    location: LocationSummary
    server_now: datetime


class Reserve(In):
    listing_id: uuid.UUID
    qty: int = Field(ge=1, le=3)
    # The price the client was shown: if it went up since, nothing is reserved (API-D4).
    expected_price_lbp: Lbp
    pickup_day: date
    days_of_use: int = Field(default=1, ge=1, le=365)
