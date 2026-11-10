"""Numbers from docs/04_domain_rules.md §5, by ID.

This is their only home in code: everything else imports these names and never repeats a value.
"""

from datetime import time, timedelta

# --- Expiry zones and prices ---
NEAR_EXPIRY_MAX_DAYS = 180  # N-1: published when 0-180 days are left
EARLY_RELEASE_MAX_DAYS = 270  # N-3: 181-270 days is the early-release zone
# N-4: (fewest days left, most days left, discount %), the same for every pharmacy
DISCOUNT_TIERS: tuple[tuple[int, int, int], ...] = ((91, 180, 25), (31, 90, 40), (0, 30, 60))
PRICE_STEP_LBP = 1_000  # SM-3, R-PR2: policy prices are rounded down to this
EARLY_RELEASE_SUGGESTED_DISCOUNT_PCT = 25  # R-PR3: the mildest tier

# --- Time ---
REQUEST_HOURS_START = time(8, 0)  # N-5, Beirut time
REQUEST_HOURS_END = time(20, 0)  # N-5
PICKUP_TIME_MIN_DAYS = 1  # N-6
PICKUP_TIME_MAX_DAYS = 3  # N-6
PICKUP_TIME_DEFAULT_DAYS = 1  # N-6
SAME_DAY_PICKUP_MIN_OPEN = timedelta(hours=1)  # N-42
SEARCH_WINDOW = timedelta(hours=6)  # N-11
OFFER_VALIDITY = timedelta(hours=2)  # N-12
WINDOW_CHECK_BEFORE_END = timedelta(hours=1)  # N-24
DEFAULT_DAYS_OF_USE = 1  # N-44

# --- Client limits (N-10) ---
MAX_OPEN_ORDERS = 5
MAX_UNITS_PER_GROUP = 3
MAX_OPEN_REQUESTS = 2
MAX_ITEMS_PER_REQUEST = 5
MAX_WATCHES = 5
MAX_OPEN_EARLY_RELEASE_REQUESTS = 5

# --- No-shows (N-9) ---
NO_SHOW_WINDOW = timedelta(days=30)
NO_SHOWS_BEFORE_PAUSE = 2
NO_SHOW_PAUSE = timedelta(days=7)

# --- Early release (N-13) ---
EARLY_RELEASE_MAX_PHARMACIES = 3
EARLY_RELEASE_ANSWER_TIME = timedelta(hours=2)
EARLY_RELEASE_MAX_ASKS_PER_PHARMACY_PER_DAY = 10
EARLY_RELEASE_DECLINE_MEMORY = timedelta(days=7)

# --- Matching, search and plans ---
AUTOMATIC_REACH_CAR_MIN = 30  # N-23: how far matching offers and early-release asks reach
OFFER_SKIP_AFTER_DECLINE = timedelta(hours=24)  # SM-5 O10
MAX_AVAILABILITY_SHOWN = 5  # R-S5: shown exactly up to 5, then "5+"
PLAN_MAX_PHARMACIES = 4  # N-48: a plan visits at most this many pharmacies
PLAN_MAX_CANDIDATE_PHARMACIES = 16  # N-48: the planner weighs at most this many pharmacies

# --- The system ---
CLOCK_CHECK_INTERVAL_S = 5  # N-26
CLOCK_CHECK_LATE_AFTER_S = 120  # N-21 (R-AL): the clock check counts as late after 2 min
DB_STATEMENT_TIMEOUT_S = 5  # N-40
DB_CONNECT_TIMEOUT_S = 2  # N-40
