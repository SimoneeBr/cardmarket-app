"""Unit tests for pure logic (no database)."""

import os
from datetime import timedelta
from decimal import Decimal

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

from cmc_shared.enums import (
    NotificationType,
    OrderStatus,
    PaymentStatus,
    ShippingStatus,
    UserRole,
)
from cmc_shared.models import NormalizedMessage, NormalizedOrderSummary
from cmc_shared.status_mapping import (
    derive_payment_status,
    derive_shipping_status,
    is_order_progress,
)
from cmc_shared.templating import render_template, unknown_variables

from app.security.passwords import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.security.permissions import Permission, has_permission
from app.security.rate_limit import RateLimiter
from app.services.action_queue import backoff_delay
from app.services.notifications import default_enabled
from app.services.sync_engine import message_key


class TestPermissions:
    def test_staff_can_operate_but_not_administer(self) -> None:
        assert has_permission(UserRole.STAFF, Permission.SEND_MESSAGE)
        assert has_permission(UserRole.STAFF, Permission.UPDATE_ORDER)
        assert not has_permission(UserRole.STAFF, Permission.MANAGE_USERS)
        assert not has_permission(UserRole.STAFF, Permission.VIEW_OPERATIONS)

    def test_manager_sees_operations_but_cannot_pair(self) -> None:
        assert has_permission(UserRole.MANAGER, Permission.VIEW_OPERATIONS)
        assert has_permission(UserRole.MANAGER, Permission.MANAGE_TEMPLATES)
        assert not has_permission(UserRole.MANAGER, Permission.MANAGE_CONNECTION)
        assert not has_permission(UserRole.MANAGER, Permission.PURGE_DATA)

    def test_admin_has_everything(self) -> None:
        assert all(has_permission(UserRole.ADMIN, p) for p in Permission)


class TestPasswords:
    def test_hash_and_verify(self) -> None:
        h = hash_password("a-strong-pass-1")
        assert h.startswith("$argon2id$")
        assert verify_password(h, "a-strong-pass-1")
        assert not verify_password(h, "wrong")

    def test_missing_hash_never_verifies(self) -> None:
        assert not verify_password(None, "anything")

    @pytest.mark.parametrize("pwd", ["short1", "onlyletterslong", "1234567890123"])
    def test_weak_passwords_rejected(self, pwd: str) -> None:
        with pytest.raises(ValueError):
            validate_password_strength(pwd)


class TestStatusMapping:
    def test_derivations(self) -> None:
        assert derive_payment_status(OrderStatus.SHIPPED) == PaymentStatus.PAID
        assert derive_shipping_status(OrderStatus.COMPLETED) == ShippingStatus.DELIVERED
        assert derive_payment_status(OrderStatus.UNKNOWN) == PaymentStatus.UNKNOWN

    def test_progress_detection(self) -> None:
        assert is_order_progress(OrderStatus.UNPAID, OrderStatus.PAID)
        assert not is_order_progress(OrderStatus.SHIPPED, OrderStatus.PAID)
        assert not is_order_progress(OrderStatus.PAID, OrderStatus.CANCELLED)


class TestTemplating:
    def test_render_and_missing(self) -> None:
        text, missing = render_template(
            "Ciao {{buyer_name}}, ordine #{{ order_id }} tracking {{tracking_number}}",
            {"buyer_name": "Mario", "order_id": "123", "tracking_number": None},
        )
        assert text == "Ciao Mario, ordine #123 tracking {{tracking_number}}"
        assert missing == {"tracking_number"}

    def test_unknown_variables(self) -> None:
        assert unknown_variables("{{buyer_name}} {{password}}") == {"password"}


class TestFingerprints:
    def test_fingerprint_changes_only_on_relevant_fields(self) -> None:
        a = NormalizedOrderSummary(
            cardmarket_id="1", buyer_name="x", status=OrderStatus.PAID, total_amount=Decimal("1.00")
        )
        b = a.model_copy(update={"buyer_name": "y"})
        c = a.model_copy(update={"status": OrderStatus.SHIPPED})
        assert a.fingerprint() == b.fingerprint()
        assert a.fingerprint() != c.fingerprint()

    def test_synthetic_message_key_is_stable(self) -> None:
        m = NormalizedMessage(direction="INBOUND", sender="a", body=" hi ")
        assert message_key(m) == message_key(m.model_copy())
        assert message_key(m).startswith("h:")
        assert message_key(m.model_copy(update={"cardmarket_id": "42"})) == "42"


class TestNotificationRules:
    def test_system_alerts_default_off_for_staff(self) -> None:
        assert default_enabled(UserRole.STAFF, NotificationType.ORDER_CREATED)
        assert not default_enabled(UserRole.STAFF, NotificationType.SESSION_EXPIRED)
        assert default_enabled(UserRole.ADMIN, NotificationType.SESSION_EXPIRED)


class TestBackoffAndRateLimit:
    def test_backoff_grows_and_is_capped(self) -> None:
        from app.config import get_settings

        s = get_settings()
        first, later = backoff_delay(1), backoff_delay(20)
        assert first >= timedelta(seconds=s.action_backoff_base_seconds)
        assert later <= timedelta(seconds=s.action_backoff_max_seconds * 1.2 + 1)

    def test_rate_limiter(self) -> None:
        rl = RateLimiter()
        assert all(rl.hit("k", 3, 60) for _ in range(3))
        assert not rl.hit("k", 3, 60)
        rl.reset("k")
        assert rl.hit("k", 3, 60)


class TestProductionValidation:
    def _prod(self, **kw: object) -> "object":
        from app.config import Settings

        base = {
            "environment": "production",
            "agent_api_token": "a" * 48,
            "cookie_secure": True,
            "database_url": "postgresql+psycopg://cmc:Str0ng-Secret-Pw@db:5432/cmc",
        }
        return Settings(**{**base, **kw})  # type: ignore[arg-type]

    def test_valid_production_config(self) -> None:
        self._prod().validate_for_runtime()  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        ("override", "message"),
        [
            ({"agent_api_token": "short"}, "at least 32"),
            ({"agent_api_token": "dev-only-agent-token-change-me-0123456789"}, "placeholder"),
            ({"cookie_secure": False}, "COOKIE_SECURE"),
            ({"database_url": "postgresql://cmc:cmc-dev-password@db/cmc"}, "DATABASE_URL"),
            ({"setup_token": "123"}, "SETUP_TOKEN"),
        ],
    )
    def test_insecure_production_config_is_refused(
        self, override: dict[str, object], message: str
    ) -> None:
        with pytest.raises(RuntimeError, match=message):
            self._prod(**override).validate_for_runtime()  # type: ignore[attr-defined]
