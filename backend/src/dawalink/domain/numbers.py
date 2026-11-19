"""Numbers from docs/04_domain_rules.md §5, by ID.

This is their only home in code: everything else imports these names and never repeats a value.
"""

from datetime import time, timedelta

# --- Expiry zones and prices ---
NEAR_EXPIRY_MAX_DAYS = 180  # N-1: published when 0-180 days are left
EARLY_RELEASE_MAX_DAYS = 270  # N-3: 181-270 days is the early-release zone
# N-54: a pharmacy lists its boxes by themselves when they have this many days left
# or fewer. It chooses one of these; 0 is "never by themselves, I list each box".
# Nothing with more than N-1's days left is ever listed.
AUTO_LIST_CHOICES = (0, 30, 60, 90, NEAR_EXPIRY_MAX_DAYS)
DEFAULT_AUTO_LIST_DAYS = NEAR_EXPIRY_MAX_DAYS
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
UPCOMING_DAYS_NAMED = 7  # N-49: the days given to the agent, one of each weekday

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

# --- Locations and travel (N-43, N-50) ---
LOCATION_DECIMALS = 3  # N-43: a client's location is rounded to about 100 m
TRAVEL_CACHE_TTL = timedelta(hours=24)  # N-43
# N-50: the straight-line estimate used when no road time is known (R-RT1).
STRAIGHT_LINE_ROAD_FACTOR = 1.4  # a road is about this much longer than the straight line
STRAIGHT_LINE_CAR_KMH = 30
STRAIGHT_LINE_WALK_KMH = 4.5
DEFAULT_PAGE_SIZE = 20  # R-S1
MAX_PAGE_SIZE = 50  # N-31
# N-8 (the owner, 2026-11-18): a reminder every 12 hours while reserved, a last one
# 2 hours before the deadline, and none in the first hour (nor two within an hour).
PICKUP_REMINDER_EVERY = timedelta(hours=12)
PICKUP_REMINDER_LAST_BEFORE = timedelta(hours=2)
PICKUP_REMINDER_QUIET = timedelta(hours=1)
SAME_PRODUCT_EARLY_RELEASE_WAIT = timedelta(hours=24)  # R-E5

# --- The system ---
CLOCK_CHECK_INTERVAL_S = 5  # N-26
CLOCK_CHECK_LATE_AFTER_S = 120  # N-21 (R-AL): the clock check counts as late after 2 min
DB_STATEMENT_TIMEOUT_S = 5  # N-40
DB_CONNECT_TIMEOUT_S = 2  # N-40
HTTP_TIMEOUT_S = 10  # N-41: outbound calls that aren't the LLM (email, routing, tracing)
# Inside an agent turn the routing service gets less: a tool must stay quick, and the
# straight-line estimate is ready if it doesn't answer (docs/07 §8).
ROUTING_TIMEOUT_S = 4
# SM-12: a failed email is tried again after each of these, then given up (DEAD).
EMAIL_RETRY_AFTER = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30))
STALE_INVENTORY_AFTER = timedelta(days=7)  # N-16

# --- The agent (N-17, N-27, N-30, N-32 to N-39, N-45, N-46; docs/04 R-AS) ---
MAX_MESSAGE_CHARS = 1_000  # N-17
MAX_TOOL_CALLS_PER_TURN = 6  # N-17: after these, the model may only reply
MAX_TURNS_PER_REQUEST = 20  # N-17, R-RQ10: above this, a person takes over
# R-AS. Every token a client's turns read or write in a day, cached ones included.
# Measured on Claude Haiku 5.5 (build step 5): a turn uses about 30,000, most of them
# the cached prompt. This allows about 100 turns, the same as the daily message limit.
DAILY_TOKEN_BUDGET_PER_CLIENT = 3_000_000
TURN_LEASE = timedelta(minutes=2)  # N-27: renewed while a turn runs
PROPOSAL_VALIDITY = timedelta(hours=2)  # N-30: a card can be tapped for this long, once
AGENT_HISTORY_MESSAGES = 20  # N-32
CASE_STATE_MAX_BYTES = 8_192  # N-33
MAX_LLM_CALLS_PER_TURN = 8  # N-34: tool calls + the reply + one repair
LLM_TIMEOUT_S = 30  # N-35
LLM_RETRY_BACKOFF_S = (1, 3)  # N-36: two retries, on timeouts, 429 and 5xx
TURN_TIME_LIMIT_CHAT_S = 60  # N-37
TURN_TIME_LIMIT_WORKER_S = 90  # N-37
# N-38: this many failed turns within the window put everyone in degraded mode for a while.
BREAKER_FAILURES = 3
BREAKER_WINDOW = timedelta(minutes=5)
BREAKER_OPEN_FOR = timedelta(minutes=2)
# SM-12: a worker turn that failed is tried again after each of these, then a person is told.
TURN_RETRY_AFTER = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))
FOLLOWUP_MIN = timedelta(minutes=15)  # N-39
FOLLOWUP_MAX = timedelta(minutes=300)  # N-39
MAX_FOLLOWUPS_PER_REQUEST = 4  # N-39
MAX_ALTERNATIVES_RECOMMENDED = 2  # N-45: one recommendation, and up to this many others
DAILY_SPEND_CAP_SHARE = 10  # N-46: a day may use this many % of the month's LLM budget

# --- Accounts and the API (R-AU, N-28, N-29, N-47; docs/06 §4) ---
# These limits protect logins, so they are counted in real time, never on the demo clock.
PASSWORD_MIN_CHARS = 10  # R-AU1
COMMON_PASSWORDS = 10_000  # R-AU1: a password among the most common ones is refused
FAILED_LOGINS_BEFORE_LOCK = 5  # R-AU2
LOGIN_LOCK = timedelta(minutes=15)  # R-AU2: both the counting window and the lock
FAILED_LOGINS_PER_ADDRESS = 30  # N-52: from one network address, on any accounts
FAILED_LOGINS_PER_ADDRESS_WINDOW = timedelta(minutes=15)  # N-52
SESSION_LIFETIME = timedelta(days=7)  # R-AU3
ADMIN_SESSION_LIFETIME = timedelta(hours=12)  # R-AU3
VERIFICATION_LINK_VALID = timedelta(hours=24)  # R-AU4
SIGNUPS_PER_ADDRESS_PER_HOUR = 5  # R-AU5
RESEND_VERIFICATION_EVERY = timedelta(minutes=1)  # N-47
RESEND_VERIFICATION_PER_DAY = 5  # N-47
API_CALLS_PER_MINUTE = 120  # N-29: per session
CHAT_MESSAGES_PER_MINUTE = 20  # N-17
CHAT_MESSAGES_PER_DAY = 100  # N-17
LOCATION_UPDATES_PER_HOUR = 10  # N-47
POLL_EVERY_S = 3  # N-28: how often an open chat or request page asks for new messages
MAX_JSON_BODY_BYTES = 64 * 1024  # docs/06 §1
SSE_HEARTBEAT_S = 15  # docs/06 §6.6.1

# --- Retention (N-19, R-RET) ---
CONVERSATION_RETENTION = timedelta(days=30)
# A client's last searches (BLD-D42): how many are shown, how many are kept, how long.
SEARCH_HISTORY_SHOWN = 8
SEARCH_HISTORY_KEPT = 20
SEARCH_HISTORY_RETENTION = timedelta(days=30)
NOTIFICATION_RETENTION = timedelta(days=90)
AUDIT_RETENTION = timedelta(days=365)
