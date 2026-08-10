"""Unit tests for the MeteringService, including concurrency safety."""

import threading

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Plan, Subscription, Tenant, UsageEvent
from app.services.metering import MeteringService
from app.services.quota import QuotaExceededError, check_quota


def create_test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
    )

    return SessionLocal()


def create_test_tenant(db):
    tenant = Tenant(name="Test Tenant")

    plan = Plan(
        name="Test Plan",
        api_call_limit=1000,
        ai_token_limit=100000,
    )

    db.add(tenant)
    db.add(plan)
    db.commit()

    db.refresh(tenant)
    db.refresh(plan)

    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status="active",
        end_date=None,
    )

    db.add(subscription)
    db.commit()

    return tenant, plan


def test_record_usage():
    db = create_test_db()

    tenant, _ = create_test_tenant(db)

    service = MeteringService(db)

    event = service.record_usage(
        tenant_id=tenant.id,
        usage_type="api_calls",
        quantity=1,
        idempotency_key="test-key-1",
    )

    assert event.id is not None
    assert event.tenant_id == tenant.id
    assert event.usage_type == "api_calls"
    assert event.quantity == 1


def test_duplicate_idempotency_key_does_not_double_count():
    db = create_test_db()

    tenant, _ = create_test_tenant(db)

    service = MeteringService(db)

    first = service.record_usage(
        tenant_id=tenant.id,
        usage_type="api_calls",
        quantity=1,
        idempotency_key="same-key",
    )

    second = service.record_usage(
        tenant_id=tenant.id,
        usage_type="api_calls",
        quantity=1,
        idempotency_key="same-key",
    )

    assert first.id == second.id

    usage = service.get_usage(
        tenant_id=tenant.id,
        usage_type="api_calls",
    )

    assert usage == 1


def test_concurrent_same_key_creates_exactly_one_event(tmp_path):
    """Real concurrency: two threads race to record the same key.

    Exactly one UsageEvent must exist afterwards; the loser of the race must
    return the winner's event rather than inserting a duplicate.
    """
    db_path = tmp_path / "concurrency.db"

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    seed = SessionLocal()
    tenant = Tenant(name="Race Tenant")
    seed.add(tenant)
    seed.commit()
    tenant_id = tenant.id
    seed.close()

    barrier = threading.Barrier(2)
    results = []

    def worker():
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            event = MeteringService(db).record_usage(
                tenant_id=tenant_id,
                usage_type="api_calls",
                quantity=1,
                idempotency_key="race-key",
            )
            results.append(event)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=30)

    db = SessionLocal()

    events = db.scalars(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == "race-key",
        )
    ).all()

    assert len(events) == 1

    total = db.scalar(select(UsageEvent.quantity).where(UsageEvent.tenant_id == tenant_id))

    assert total == 1
    assert len(results) == 2

    # Both callers observed the same event.
    assert results[0].id == results[1].id

    db.close()


def test_same_key_different_tenants_is_allowed():
    db = create_test_db()

    tenant_a, _ = create_test_tenant(db)

    tenant_b = Tenant(name="Tenant B")
    db.add(tenant_b)
    db.commit()
    db.refresh(tenant_b)

    service = MeteringService(db)

    event_a = service.record_usage(
        tenant_id=tenant_a.id,
        usage_type="api_calls",
        quantity=1,
        idempotency_key="shared-key",
    )

    event_b = service.record_usage(
        tenant_id=tenant_b.id,
        usage_type="api_calls",
        quantity=1,
        idempotency_key="shared-key",
    )

    assert event_a.id != event_b.id

    assert service.get_usage(tenant_a.id, "api_calls") == 1
    assert service.get_usage(tenant_b.id, "api_calls") == 1


def test_tenant_isolation_in_get_usage():
    db = create_test_db()

    tenant_a, _ = create_test_tenant(db)

    tenant_b = Tenant(name="Tenant B")
    db.add(tenant_b)
    db.commit()
    db.refresh(tenant_b)

    service = MeteringService(db)

    service.record_usage(
        tenant_id=tenant_a.id,
        usage_type="api_calls",
        quantity=5,
        idempotency_key="key-a",
    )

    assert service.get_usage(tenant_a.id, "api_calls") == 5
    assert service.get_usage(tenant_b.id, "api_calls") == 0


def test_quota_allows_request_at_exact_limit():
    check_quota(
        current_usage=999,
        requested_quantity=1,
        limit=1000,
        usage_type="api_calls",
    )


def test_quota_rejects_request_over_limit():
    try:
        check_quota(
            current_usage=1000,
            requested_quantity=1,
            limit=1000,
            usage_type="api_calls",
        )

        assert False, "Expected quota to be exceeded"

    except QuotaExceededError as error:
        assert error.used == 1000
        assert error.limit == 1000


def test_quota_rejects_request_that_crosses_limit():
    try:
        check_quota(
            current_usage=999,
            requested_quantity=2,
            limit=1000,
            usage_type="api_calls",
        )

        assert False, "Expected quota to be exceeded"

    except QuotaExceededError as error:
        assert error.used == 999
        assert error.limit == 1000
