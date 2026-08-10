import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Plan, Subscription, Tenant

TEST_WEBHOOK_SECRET = "whsec_test_secret_value"


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    return engine


@pytest.fixture()
def db_session(db_engine):
    session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


@pytest.fixture()
def client(db_engine, monkeypatch):
    session_factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Deterministic webhook secret + pro price id for signature/plan tests.
    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "stripe_pro_price_id", "price_pro_test")

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def seed_data(db_session):
    free = Plan(name="Free", api_call_limit=1000, ai_token_limit=100_000)
    pro = Plan(name="Pro", api_call_limit=10_000, ai_token_limit=1_000_000)

    db_session.add_all([free, pro])
    db_session.commit()
    db_session.refresh(free)
    db_session.refresh(pro)

    tenant1 = Tenant(name="Demo Tenant")
    tenant2 = Tenant(name="Other Tenant")

    db_session.add_all([tenant1, tenant2])
    db_session.commit()
    db_session.refresh(tenant1)
    db_session.refresh(tenant2)

    sub1 = Subscription(tenant_id=tenant1.id, plan_id=free.id, status="active")
    sub2 = Subscription(tenant_id=tenant2.id, plan_id=free.id, status="active")

    db_session.add_all([sub1, sub2])
    db_session.commit()

    return {
        "free": free,
        "pro": pro,
        "tenant1": tenant1,
        "tenant2": tenant2,
        "sub1": sub1,
        "sub2": sub2,
    }


def sign_event_payload(payload_bytes: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Build a valid Stripe signature header for the given payload bytes."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload_bytes.decode()}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return f"t={timestamp},v1={signature}"


def make_stripe_event(
    event_type: str,
    data: dict,
    secret: str = TEST_WEBHOOK_SECRET,
) -> tuple[bytes, str]:
    """Return (raw body, valid Stripe-Signature header) for a fake Stripe event."""
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "data": {"object": data},
    }

    body = json.dumps(event).encode()

    return body, sign_event_payload(body, secret)


def checkout_completed_data(
    tenant_id: int = 1,
    subscription_id: str = "sub_test_123",
    customer_id: str = "cus_test_123",
    plan: str = "Pro",
) -> dict:
    return {
        "id": "cs_test_checkout",
        "metadata": {"tenant_id": str(tenant_id), "plan": plan},
        "client_reference_id": str(tenant_id),
        "subscription": subscription_id,
        "customer": customer_id,
        "mode": "subscription",
    }


def subscription_object(
    subscription_id: str = "sub_test_123",
    status: str = "active",
    price_id: str = "price_pro_test",
) -> dict:
    return {
        "id": subscription_id,
        "status": status,
        "items": {
            "data": [
                {"id": "si_test_1", "price": {"id": price_id, "type": "recurring"}}
            ]
        },
    }
