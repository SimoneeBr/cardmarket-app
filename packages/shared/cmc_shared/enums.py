"""Domain enums shared by API, agent and (via OpenAPI) the web app.

All values are stable strings: they are persisted in PostgreSQL and exposed in
the public API, so renaming a value requires a data migration.
"""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    STAFF = "STAFF"


class ConnectionStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    ERROR = "ERROR"


class OrderStatus(StrEnum):
    """Internal order lifecycle, independent from Cardmarket wording."""

    UNPAID = "UNPAID"  # bought, awaiting payment
    PAID = "PAID"  # paid, awaiting shipment ("da spedire")
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"  # arrived / received
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    UNKNOWN = "UNKNOWN"


class ShippingStatus(StrEnum):
    NOT_SHIPPED = "NOT_SHIPPED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    UNKNOWN = "UNKNOWN"


class CartStatus(StrEnum):
    TO_PAY = "TO_PAY"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class SyncEntity(StrEnum):
    ORDERS = "ORDERS"
    CONVERSATIONS = "CONVERSATIONS"
    CARTS = "CARTS"
    FULL = "FULL"


class SyncRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ActionType(StrEnum):
    SEND_MESSAGE = "SEND_MESSAGE"
    MARK_ORDER_SHIPPED = "MARK_ORDER_SHIPPED"
    PAIR_SESSION = "PAIR_SESSION"
    VERIFY_SESSION = "VERIFY_SESSION"


# Actions that change data on Cardmarket. They must always be verified after
# execution and must never be blindly re-executed after a crash.
WRITE_ACTIONS: frozenset[ActionType] = frozenset(
    {ActionType.SEND_MESSAGE, ActionType.MARK_ORDER_SHIPPED}
)


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class ActionOutcome(StrEnum):
    """What the agent reports back after trying an action."""

    SUCCESS = "SUCCESS"  # executed AND verified
    FAILED = "FAILED"  # definitely not executed
    RETRY = "RETRY"  # transient failure, safe to retry (not executed)
    UNVERIFIED = "UNVERIFIED"  # executed (maybe) but verification failed
    UNSAFE = "UNSAFE"  # UI not recognised, refused to act


class ErrorCode(StrEnum):
    AUTH_ERROR = "AUTH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    CARDMARKET_CHANGED = "CARDMARKET_CHANGED"
    # Refused by an external firewall/WAF (e.g. a Cloudflare "you have been blocked"
    # page) before Cardmarket was reached. Not transient, not an auth problem, and
    # not something the agent may try to get around.
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    SELECTOR_NOT_FOUND = "SELECTOR_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    ACTION_FAILED = "ACTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    DATABASE_ERROR = "DATABASE_ERROR"
    UNKNOWN = "UNKNOWN"


class NotificationType(StrEnum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_PAID = "ORDER_PAID"
    ORDER_SHIPPED = "ORDER_SHIPPED"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    CART_CREATED = "CART_CREATED"
    CART_PAID = "CART_PAID"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SYNC_ERROR = "SYNC_ERROR"
    ACTION_FAILED = "ACTION_FAILED"


class DomainEventType(StrEnum):
    ORDER_CREATED = "OrderCreated"
    ORDER_PAID = "OrderPaid"
    ORDER_SHIPPED = "OrderShipped"
    ORDER_STATUS_CHANGED = "OrderStatusChanged"
    MESSAGE_RECEIVED = "MessageReceived"
    MESSAGE_SENT = "MessageSent"
    CART_CREATED = "CartCreated"
    CART_PAID = "CartPaid"
    CART_STATUS_CHANGED = "CartStatusChanged"
    SESSION_EXPIRED = "SessionExpired"
    CONNECTION_RESTORED = "ConnectionRestored"
    SYNC_FAILED = "SyncFailed"
    ACTION_FAILED = "ActionFailed"


class EntityType(StrEnum):
    ORDER = "ORDER"
    CONVERSATION = "CONVERSATION"
    MESSAGE = "MESSAGE"
    CART = "CART"
    CONNECTION = "CONNECTION"
    SYNC_RUN = "SYNC_RUN"
    ACTION = "ACTION"
    USER = "USER"
    TEMPLATE = "TEMPLATE"
    SETTINGS = "SETTINGS"


class AgentMode(StrEnum):
    MOCK = "MOCK"
    LIVE = "LIVE"


class AgentCommandType(StrEnum):
    """Out-of-band commands delivered with the heartbeat response.

    The SIMULATE_* commands are honoured only by the mock adapter.
    """

    SIMULATE_SESSION_EXPIRED = "SIMULATE_SESSION_EXPIRED"
    SIMULATE_SYNC_ERROR = "SIMULATE_SYNC_ERROR"
    SIMULATE_NEW_ACTIVITY = "SIMULATE_NEW_ACTIVITY"
    SYNC_NOW = "SYNC_NOW"
    DISCONNECT = "DISCONNECT"
