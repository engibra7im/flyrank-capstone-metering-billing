from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import UsageEvent


class MeteringService:
    def __init__(self, db: Session):
        self.db = db

    def get_usage(self, tenant_id: int, usage_type: str) -> int:
        total = self.db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0))
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.usage_type == usage_type,
            )
        )

        return int(total)

    def record_usage(
        self,
        tenant_id: int,
        usage_type: str,
        quantity: int,
        idempotency_key: str,
    ) -> UsageEvent:

        existing = self.db.scalar(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.idempotency_key == idempotency_key,
            )
        )

        if existing:
            return existing

        event = UsageEvent(
            tenant_id=tenant_id,
            usage_type=usage_type,
            quantity=quantity,
            idempotency_key=idempotency_key,
        )

        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)

        return event