"""Processes verified Stripe events and keeps local subscription state in sync.

Payment truth lives in Stripe. This service only ever runs after a webhook
signature has been verified, and it guarantees each Stripe event is applied at
most once by relying on the unique constraint on ``stripe_webhook_events``.

Stripe SDK objects (v15+) do not subclass ``dict``; they expose fields through
``obj["field"]`` / ``obj.field``. All access here goes through the ``_get``
helper so missing fields degrade to ``None`` instead of raising.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import (
    HANDLED_WEBHOOK_EVENTS,
    WEBHOOK_CHECKOUT_COMPLETED,
    WEBHOOK_SUBSCRIPTION_UPDATED,
    WEBHOOK_SUBSCRIPTION_DELETED,
)
from ..models import StripeWebhookEvent
from .subscription import SubscriptionService


def _get(obj, key, default=None):
    """Field access that works for Stripe objects, dicts and ``None``."""
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(key, default)

    try:
        value = obj[key]
    except (KeyError, TypeError, AttributeError):
        return default

    return value


def _as_dict(obj) -> dict:
    """Best-effort dict conversion for Stripe objects and plain dicts."""
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    return obj._data if hasattr(obj, "_data") else {}


class WebhookSyncService:
    def __init__(self, db: Session, stripe_pro_price_id: str | None = None):
        self.db = db
        self.subscriptions = SubscriptionService(
            db, stripe_pro_price_id=stripe_pro_price_id
        )

    def handle(self, event) -> dict:
        """Process a verified Stripe event exactly once.

        The marker row (stripe_webhook_events.event_id) is inserted in the same
        transaction as the state change. If two deliveries arrive concurrently,
        only the first commit wins; the loser hits the unique constraint and is
        reported as ignored.
        """
        event_id = event["id"]
        event_type = event["type"]

        if self.db.scalar(
            select(StripeWebhookEvent).where(
                StripeWebhookEvent.event_id == event_id
            )
        ):
            return {"status": "ignored", "reason": "duplicate event", "event_id": event_id}

        marker = StripeWebhookEvent(event_id=event_id, event_type=event_type)
        self.db.add(marker)

        try:
            if event_type in HANDLED_WEBHOOK_EVENTS:
                self._apply(event_type, _as_dict(_get(event["data"], "object")))

            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return {"status": "ignored", "reason": "duplicate event", "event_id": event_id}

        return {"status": "processed", "event_id": event_id, "event_type": event_type}

    def _apply(self, event_type: str, data: dict) -> None:
        if event_type == WEBHOOK_CHECKOUT_COMPLETED:
            self._apply_checkout_completed(data)
        elif event_type == WEBHOOK_SUBSCRIPTION_UPDATED:
            self._apply_subscription_updated(data)
        elif event_type == WEBHOOK_SUBSCRIPTION_DELETED:
            self._apply_subscription_deleted(data)

    def _apply_checkout_completed(self, data: dict) -> None:
        metadata = _as_dict(_get(data, "metadata"))

        raw_tenant = metadata.get("tenant_id") or _get(data, "client_reference_id")

        if raw_tenant is None:
            return

        try:
            tenant_id = int(raw_tenant)
        except (TypeError, ValueError):
            return

        plan_name = metadata.get("plan") or "Pro"

        self.subscriptions.sync_checkout_completed(
            tenant_id=tenant_id,
            plan_name=plan_name,
            stripe_subscription_id=_get(data, "subscription"),
            stripe_customer_id=_get(data, "customer"),
        )

    def _apply_subscription_updated(self, data: dict) -> None:
        subscription_id = _get(data, "id")

        if not subscription_id:
            return

        plan_name = self._plan_name_from_subscription(data)

        self.subscriptions.sync_subscription_status(
            stripe_subscription_id=subscription_id,
            status=_get(data, "status") or "active",
            plan_name=plan_name,
        )

    def _apply_subscription_deleted(self, data: dict) -> None:
        subscription_id = _get(data, "id")

        if not subscription_id:
            return

        self.subscriptions.cancel_subscription(
            stripe_subscription_id=subscription_id
        )

    def _plan_name_from_subscription(self, data: dict) -> str | None:
        """Derive the local plan name from the Stripe subscription's price ids."""
        price_ids = set()

        items = _get(data, "items") or {}
        item_list = _get(items, "data") or []

        for item in item_list:
            price = _get(item, "price") or {}
            price_id = _get(price, "id")

            if price_id:
                price_ids.add(price_id)

        return self.subscriptions.plan_from_price_ids(price_ids)
