"""Fixed lists of values that have no state machine of their own yet (docs/05 §3).

The database checks every one of these lists, and a test keeps the two in step. The lists
that do have a state machine live next to it (orders.py, claims.py, requests.py, ...).
"""

from enum import StrEnum


class UserRole(StrEnum):
    CLIENT = "client"
    PHARMACIST = "pharmacist"
    ADMIN = "admin"


class LocationSource(StrEnum):
    """Where a client's location came from (docs/04 R-S2)."""

    SHARED = "shared"
    DISTRICT = "district"


class BrandOrGeneric(StrEnum):
    """How the Ministry classes a product."""

    BRAND = "B"
    GENERIC = "G"
    BIOTECH = "BioTech"
    BIOHUMAN = "BioHuman"


class UploadStatus(StrEnum):
    """An inventory upload (docs/04 SM-4)."""

    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    DISCARDED = "DISCARDED"
    FAILED = "FAILED"


class CloseReason(StrEnum):
    """Why an order ended without a pickup (docs/04 SM-5)."""

    NOT_AVAILABLE = "not_available"
    CLIENT_CANCEL = "client_cancel"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    SYSTEM = "system"


class ClaimKind(StrEnum):
    WATCH = "WATCH"
    REQUEST_ITEM = "REQUEST_ITEM"


class ClaimSource(StrEnum):
    """Where a claim was created, which decides where its events go (docs/04 R-AG5)."""

    SEARCH = "search"  # [Notify me] on the search page: notifications only
    ASSISTANT = "assistant"  # the agent's watch in a chat: the client's chat
    REQUEST = "request"  # a waiting request item: the request's thread


class ConversationKind(StrEnum):
    CHAT = "chat"
    REQUEST = "request"


class ConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MessageAuthor(StrEnum):
    CLIENT = "client"
    AGENT = "agent"
    SYSTEM = "system"
    ADMIN = "admin"


class MessageKind(StrEnum):
    TEXT = "text"
    CARD = "card"
    TIMELINE = "timeline"
    EVENT = "event"


class ProposalKind(StrEnum):
    """The cards a tool can create (docs/04 R-AG7)."""

    RESERVE = "reserve"
    RESERVE_GROUP = "reserve_group"
    ACCEPT_OFFER = "accept_offer"
    CANCEL = "cancel"
    REQUEST_SUMMARY = "request_summary"
    CONSTRAINT_CHANGE = "constraint_change"
    REMOVE_ITEM = "remove_item"


class AgentMode(StrEnum):
    ASSISTANT = "assistant"
    SOURCING = "sourcing"


class TurnTrigger(StrEnum):
    CLIENT_MESSAGE = "client_message"
    REQUEST_SUBMITTED = "request_submitted"
    DECISION_EVENT = "decision_event"
    FOLLOWUP = "followup"
    WINDOW_CHECK = "window_check"


class RunOutcome(StrEnum):
    OK = "ok"
    FALLBACK = "fallback"
    ERROR = "error"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"


class ReportState(StrEnum):
    """A reported answer (docs/04 SM-10)."""

    NEW = "NEW"
    DISMISSED = "DISMISSED"
    CONFIRMED = "CONFIRMED"


class EscalationReason(StrEnum):
    CLIENT_ASKED_HUMAN = "client_asked_human"
    EMERGENCY_CLAIM = "emergency_claim"
    CANNOT_RESOLVE = "cannot_resolve"
    WINDOW_ENDING = "window_ending"
    SUSPICIOUS = "suspicious"
    COMPLAINT = "complaint"


class EscalationState(StrEnum):
    """An escalation to a person (docs/04 SM-9)."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class FlagSubject(StrEnum):
    CLIENT = "client"
    PHARMACY = "pharmacy"


class FlagRule(StrEnum):
    NO_SHOW_PAUSE = "no_show_pause"
    GUARDRAIL_REPEAT = "guardrail_repeat"


class FlagSeverity(StrEnum):
    LOW = "low"
    HIGH = "high"


class FlagState(StrEnum):
    """An abuse flag (docs/04 SM-11)."""

    OPEN = "OPEN"
    DISMISSED = "DISMISSED"
    ACTIONED = "ACTIONED"


class OutboxState(StrEnum):
    """An email waiting to be sent (docs/04 SM-12)."""

    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    DEAD = "DEAD"


class TravelMode(StrEnum):
    CAR = "car"
    WALK = "walk"


class TravelSource(StrEnum):
    """A road time from the routing service, or a straight-line estimate (docs/04 R-RT1)."""

    ROAD = "road"
    STRAIGHT = "straight"
