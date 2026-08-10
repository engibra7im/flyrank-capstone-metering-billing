from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    api_call_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active"
    )
    stripe_customer_id: Mapped[str] = mapped_column(
        String(255), nullable=True, default=None
    )
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(255), nullable=True, default=None
    )
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    plan: Mapped["Plan"] = relationship("Plan")
    tenant: Mapped["Tenant"] = relationship("Tenant")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    usage_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_tenant_idempotency_key"
        ),
    )


class StripeWebhookEvent(Base):
    """A Stripe event that has already been processed.

    The unique event_id is what guarantees a given Stripe event is only ever
    processed once, even if Stripe delivers the same webhook multiple times.
    """

    __tablename__ = "stripe_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class UsageSnapshot(Base):
    """Aggregated monthly usage produced by the background rollup job.

    One row per (tenant, usage_type, period). The unique constraint makes the
    job idempotent: running it twice can never create duplicate rows.
    """

    __tablename__ = "usage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    usage_type: Mapped[str] = mapped_column(String(30), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "usage_type", "period",
            name="uq_tenant_type_period",
        ),
    )
