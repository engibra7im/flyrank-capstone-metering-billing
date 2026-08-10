"""Background job: monthly usage aggregation (rollup).

Every run aggregates each tenant's usage events into per-(tenant, usage_type,
period) snapshots. The job is designed to be safe to run repeatedly:

  * it is idempotent - it recomputes the same snapshot values and writes them
    back (upsert), never appending;
  * the unique constraint (tenant_id, usage_type, period) makes duplicates
    impossible, so two concurrent runs cannot corrupt data;
  * a partial failure leaves the previous snapshot untouched and the job can
    simply be re-run.

Run once from the CLI:

    python -m app.jobs.rollup

Or start it on a schedule with a scheduler/cron. The FastAPI app also starts a
lightweight in-process daemon thread that calls this job periodically.
"""

from datetime import datetime

from sqlalchemy import select

from ..constants import USAGE_TYPE_AI_TOKENS, USAGE_TYPE_API_CALLS
from ..database import SessionLocal
from ..models import Tenant, UsageEvent, UsageSnapshot


def _usage_types():
    return (USAGE_TYPE_API_CALLS, USAGE_TYPE_AI_TOKENS)


def run_rollup(db=None) -> int:
    """Aggregate usage into snapshots. Returns the number of snapshots written."""
    own_session = db is None
    db = db or SessionLocal()

    written = 0

    try:
        tenants = db.scalars(select(Tenant)).all()

        for tenant in tenants:
            for usage_type in _usage_types():
                events = db.scalars(
                    select(UsageEvent).where(
                        UsageEvent.tenant_id == tenant.id,
                        UsageEvent.usage_type == usage_type,
                    )
                ).all()

                buckets: dict[str, int] = {}

                for event in events:
                    created: datetime = event.created_at
                    period = created.strftime("%Y-%m")
                    buckets[period] = buckets.get(period, 0) + event.quantity

                for period, quantity in buckets.items():
                    snapshot = db.scalar(
                        select(UsageSnapshot).where(
                            UsageSnapshot.tenant_id == tenant.id,
                            UsageSnapshot.usage_type == usage_type,
                            UsageSnapshot.period == period,
                        )
                    )

                    if snapshot is None:
                        snapshot = UsageSnapshot(
                            tenant_id=tenant.id,
                            usage_type=usage_type,
                            period=period,
                            quantity=quantity,
                        )
                        db.add(snapshot)
                    else:
                        snapshot.quantity = quantity

                    written += 1

        db.commit()
    finally:
        if own_session:
            db.close()

    return written


if __name__ == "__main__":
    count = run_rollup()
    print(f"Rollup completed. {count} snapshot rows written.")
