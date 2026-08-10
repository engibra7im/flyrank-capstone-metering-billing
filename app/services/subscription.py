from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, Subscription, Tenant
from ..constants import (
    PLAN_FREE,
    PLAN_PRO,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_ACTIVE,
)


class SubscriptionService:
    """Resolves tenant plans and synchronizes Stripe subscription state.

    The local database is a *mirror* of Stripe. All state-changing writes
    performed here happen only after a verified Stripe webhook event has been
    processed (see app/routes/webhooks.py).
    """

    def __init__(self, db: Session, stripe_pro_price_id: str | None = None):
        self.db = db
        self.stripe_pro_price_id = stripe_pro_price_id

    def get_active_subscription(self, tenant_id: int) -> Subscription | None:
        return self.db.scalar(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id,
                Subscription.status == SUBSCRIPTION_STATUS_ACTIVE,
            )
        )

    def get_subscription_and_plan(self, tenant_id: int) -> tuple[Subscription, Plan] | None:
        """Return (subscription, plan) for a tenant with an active subscription."""
        subscription = self.get_active_subscription(tenant_id)

        if subscription is None:
            return None

        plan = self.db.scalar(
            select(Plan).where(Plan.id == subscription.plan_id)
        )

        if plan is None:
            return None

        return subscription, plan

    def plan_by_name(self, name: str) -> Plan | None:
        return self.db.scalar(select(Plan).where(Plan.name == name))

    def plan_from_price_ids(self, price_ids: set[str]) -> str | None:
        """Map a Stripe price id to a local plan name.

        Only the Pro plan has a Stripe price. Anything that is not the Pro
        price maps to the Free plan.
        """
        if not price_ids:
            return None

        if self.stripe_pro_price_id and self.stripe_pro_price_id in price_ids:
            return PLAN_PRO

        return PLAN_FREE

    def sync_checkout_completed(
        self, tenant_id: int, plan_name: str, stripe_subscription_id: str | None,
        stripe_customer_id: str | None,
    ) -> Subscription | None:
        """Create (or reactivate) the tenant's subscription after checkout."""
        plan = self.plan_by_name(plan_name)
        if plan is None:
            return None

        subscription = self.db.scalar(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id,
                Subscription.stripe_subscription_id == stripe_subscription_id,
            )
        )

        if subscription is None:
            subscription = self.db.scalar(
                select(Subscription).where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.stripe_subscription_id.is_(None),
                )
            )

        if subscription is None:
            subscription = Subscription(tenant_id=tenant_id)

        subscription.plan_id = plan.id
        subscription.status = SUBSCRIPTION_STATUS_ACTIVE
        subscription.stripe_subscription_id = stripe_subscription_id
        subscription.stripe_customer_id = stripe_customer_id
        subscription.end_date = None

        self.db.add(subscription)

        return subscription

    def sync_subscription_status(
        self,
        stripe_subscription_id: str,
        status: str,
        plan_name: str | None = None,
    ) -> Subscription | None:
        """Synchronize status/plan for an existing Stripe subscription."""
        subscription = self.db.scalar(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id,
            )
        )

        if subscription is None:
            return None

        subscription.status = status

        if plan_name is not None:
            plan = self.plan_by_name(plan_name)
            if plan is not None:
                subscription.plan_id = plan.id

        return subscription

    def cancel_subscription(self, stripe_subscription_id: str) -> Subscription | None:
        subscription = self.db.scalar(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id,
            )
        )

        if subscription is None:
            return None

        subscription.status = SUBSCRIPTION_STATUS_CANCELED
        subscription.end_date = datetime.now(timezone.utc)

        return subscription
