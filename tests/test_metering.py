from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Tenant, Plan, Subscription
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