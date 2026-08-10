from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import UsageEvent


class MeteringService:
    """Records and aggregates billable usage for tenants.

    Idempotency is guaranteed by the database unique constraint on
    (tenant_id, idempotency_key), not by a SELECT-then-INSERT. Two concurrent
    requests with the same key can both pass a SELECT, but only one INSERT can
    succeed. The loser catches IntegrityError, rolls back, and returns the row
    created by the winner.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_usage(self, tenant_id: int, usage_type: str) -> int:
        total = self.db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.usage_type == usage_type,
            )
        )

        return int(total)

    def get_existing(
        self, tenant_id: int, idempotency_key: str
    ) -> UsageEvent | None:
        """Return the stored event for a key, or None if the key is new."""
        return self.db.scalar(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.idempotency_key == idempotency_key,
            )
        )

    def record_usage(
        self,
        tenant_id: int,
        usage_type: str,
        quantity: int,
        idempotency_key: str,
        payload: dict | None = None,
    ) -> UsageEvent:
        """Create a usage event exactly once for (tenant, idempotency_key).

        Fast path: if the key already exists, return the stored event.

        Otherwise try the INSERT. If a concurrent request wins the race, the
        unique constraint raises IntegrityError; we roll back and return the
        winner's event. This is what makes duplicate usage impossible even
        under real concurrency.
        """
        existing = self.get_existing(tenant_id, idempotency_key)
        if existing is not None:
            return existing

        event = UsageEvent(
            tenant_id=tenant_id,
            usage_type=usage_type,
            quantity=quantity,
            idempotency_key=idempotency_key,
            payload=payload,
        )

        self.db.add(event)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()

            winner = self.get_existing(tenant_id, idempotency_key)
            if winner is not None:
                return winner

            raise

        self.db.refresh(event)

        return event
