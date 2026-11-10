"""Numbers from docs/04_domain_rules.md §5, by ID.

This is their only home in code: everything else imports these names and never repeats a value.
"""

CLOCK_CHECK_INTERVAL_S = 5  # N-26
CLOCK_CHECK_LATE_AFTER_S = 120  # N-21 (R-AL): the clock check counts as late after 2 min
DB_STATEMENT_TIMEOUT_S = 5  # N-40
DB_CONNECT_TIMEOUT_S = 2  # N-40
