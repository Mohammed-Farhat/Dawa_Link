"""Every table model, in the seven areas of docs/05 §3.

Importing this package registers all 34 tables on `Base.metadata`, which Alembic and the
tests read.
"""

from dawalink.db.models.admin import AbuseFlag, Escalation
from dawalink.db.models.agent import (
    AgentRun,
    AgentToolCall,
    AnswerReport,
    ChatMessage,
    Conversation,
    Proposal,
)
from dawalink.db.models.catalog import CatalogImport, PricingTier, Product, ProductIngredient
from dawalink.db.models.identity import (
    ClientProfile,
    District,
    EmailVerificationToken,
    Pharmacy,
    PharmacyHours,
    Session,
    User,
)
from dawalink.db.models.inventory import InventoryItem, InventoryUpload, InventoryUploadRow
from dawalink.db.models.operations import (
    AppState,
    AuditEvent,
    EmailOutbox,
    Notification,
    TravelTimeCache,
)
from dawalink.db.models.orders import Order
from dawalink.db.models.sourcing import (
    Claim,
    ClaimSkip,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    RequestItem,
    SourcingRequest,
)

__all__ = [
    "AbuseFlag",
    "AgentRun",
    "AgentToolCall",
    "AnswerReport",
    "AppState",
    "AuditEvent",
    "CatalogImport",
    "ChatMessage",
    "Claim",
    "ClaimSkip",
    "ClientProfile",
    "Conversation",
    "District",
    "EarlyReleaseAsk",
    "EarlyReleaseRequest",
    "EmailOutbox",
    "EmailVerificationToken",
    "Escalation",
    "InventoryItem",
    "InventoryUpload",
    "InventoryUploadRow",
    "Notification",
    "Order",
    "Pharmacy",
    "PharmacyHours",
    "PricingTier",
    "Product",
    "ProductIngredient",
    "Proposal",
    "RequestItem",
    "Session",
    "SourcingRequest",
    "TravelTimeCache",
    "User",
]
