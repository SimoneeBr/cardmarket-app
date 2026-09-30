"""Derivations between internal statuses (single source of truth)."""

from cmc_shared.enums import CartStatus, OrderStatus, PaymentStatus, ShippingStatus

_PAYMENT_BY_ORDER: dict[OrderStatus, PaymentStatus] = {
    OrderStatus.UNPAID: PaymentStatus.UNPAID,
    OrderStatus.PAID: PaymentStatus.PAID,
    OrderStatus.SHIPPED: PaymentStatus.PAID,
    OrderStatus.COMPLETED: PaymentStatus.PAID,
}

_SHIPPING_BY_ORDER: dict[OrderStatus, ShippingStatus] = {
    OrderStatus.UNPAID: ShippingStatus.NOT_SHIPPED,
    OrderStatus.PAID: ShippingStatus.NOT_SHIPPED,
    OrderStatus.SHIPPED: ShippingStatus.SHIPPED,
    OrderStatus.COMPLETED: ShippingStatus.DELIVERED,
}

# Ordering used to detect regressions (a status going "backwards" is suspicious
# and is recorded as a generic status change, never as a payment/shipping event).
ORDER_PROGRESS: dict[OrderStatus, int] = {
    OrderStatus.UNPAID: 0,
    OrderStatus.PAID: 1,
    OrderStatus.SHIPPED: 2,
    OrderStatus.COMPLETED: 3,
}

CART_PROGRESS: dict[CartStatus, int] = {
    CartStatus.TO_PAY: 0,
    CartStatus.PAID: 1,
    CartStatus.COMPLETED: 2,
}


def derive_payment_status(status: OrderStatus) -> PaymentStatus:
    return _PAYMENT_BY_ORDER.get(status, PaymentStatus.UNKNOWN)


def derive_shipping_status(status: OrderStatus) -> ShippingStatus:
    return _SHIPPING_BY_ORDER.get(status, ShippingStatus.UNKNOWN)


def is_order_progress(old: OrderStatus, new: OrderStatus) -> bool:
    return ORDER_PROGRESS.get(new, -1) > ORDER_PROGRESS.get(old, 99)


def is_cart_progress(old: CartStatus, new: CartStatus) -> bool:
    return CART_PROGRESS.get(new, -1) > CART_PROGRESS.get(old, 99)
