"""Background rollup job: aggregation correctness and retry-safety."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.jobs.rollup import run_rollup
from app.models import UsageEvent, UsageSnapshot


def _add_event(db, tenant_id, usage_type, quantity, idempotency_key, created_at):
    event = UsageEvent(
        tenant_id=tenant_id,
        usage_type=usage_type,
        quantity=quantity,
        idempotency_key=idempotency_key,
        created_at=created_at,
    )

    db.add(event)
    db.commit()

    return event


def test_rollup_aggregates_usage(db_session, seed_data):
    now = datetime.now(timezone.utc)
    previous = datetime(2020, 1, 15, 12, 0, tzinfo=timezone.utc)

    _add_event(db_session, 1, "api_calls", 3, "k1", now)
    _add_event(db_session, 1, "api_calls", 4, "k2", now)
    _add_event(db_session, 1, "api_calls", 5, "k3", previous)

    count = run_rollup(db_session)

    # Two periods for tenant 1 api_calls (current month + 2020-01).
    assert count >= 2

    current_period = now.strftime("%Y-%m")

    snapshot = db_session.scalar(
        select(UsageSnapshot).where(
            UsageSnapshot.tenant_id == 1,
            UsageSnapshot.usage_type == "api_calls",
            UsageSnapshot.period == current_period,
        )
    )

    assert snapshot is not None
    assert snapshot.quantity == 7

    snapshot = db_session.scalar(
        select(UsageSnapshot).where(
            UsageSnapshot.tenant_id == 1,
            UsageSnapshot.usage_type == "api_calls",
            UsageSnapshot.period == "2020-01",
        )
    )

    assert snapshot is not None
    assert snapshot.quantity == 5


def test_rollup_is_idempotent_when_run_twice(db_session, seed_data):
    now = datetime.now(timezone.utc)

    _add_event(db_session, 1, "ai_tokens", 100, "t1", now)
    _add_event(db_session, 2, "api_calls", 7, "t2", now)

    first = run_rollup(db_session)
    second = run_rollup(db_session)

    rows = db_session.query(UsageSnapshot).all()

    # Running twice never duplicates snapshot rows.
    assert len(rows) == first
    assert len(rows) == second

    totals = {}
    for row in rows:
        key = (row.tenant_id, row.usage_type, row.period)
        totals[key] = totals.get(key, 0) + row.quantity

    assert totals[(1, "ai_tokens", now.strftime("%Y-%m"))] == 100
    assert totals[(2, "api_calls", now.strftime("%Y-%m"))] == 7
