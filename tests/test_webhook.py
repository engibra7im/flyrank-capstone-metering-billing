"""Stripe webhook behavior: signature verification, dedup, plan sync."""

from app.models import StripeWebhookEvent, Subscription

from tests.helpers import (
    checkout_completed_data,
    make_stripe_event,
    sign_event_payload,
    subscription_object,
)


def test_webhook_missing_signature_rejected(client, seed_data):
    body, _ = make_stripe_event("checkout.session.completed", checkout_completed_data())

    response = client.post("/webhooks/stripe", content=body)

    assert response.status_code == 400


def test_forged_webhook_rejected_and_state_unchanged(client, seed_data, db_session):
    event = {
        "id": "evt_forged",
        "type": "checkout.session.completed",
        "data": {"object": checkout_completed_data(plan="Pro")},
    }

    import json

    body = json.dumps(event).encode()
    header = sign_event_payload(body, secret="wrong_secret")

    response = client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": header},
    )

    assert response.status_code == 400

    # State unchanged: tenant still on Free plan, no stripe sub id recorded.
    subscription = db_session.query(Subscription).filter(
        Subscription.tenant_id == 1
    ).first()

    assert subscription.plan.name == "Free"
    assert subscription.stripe_subscription_id is None

    processed = db_session.query(StripeWebhookEvent).count()
    assert processed == 0


def test_invalid_payload_rejected(client, seed_data):
    response = client.post(
        "/webhooks/stripe",
        content=b"not-json",
        headers={"Stripe-Signature": "t=0,v1=abc"},
    )

    assert response.status_code == 400


def test_checkout_completed_upgrades_tenant_to_pro(client, seed_data, db_session):
    body, header = make_stripe_event(
        "checkout.session.completed",
        checkout_completed_data(
            tenant_id=1, subscription_id="sub_test_123",
            customer_id="cus_test_123", plan="Pro",
        ),
    )

    response = client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": header},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    usage = client.get("/usage", headers={"X-Tenant-ID": "1"}).json()

    assert usage["plan"] == "Pro"
    assert usage["ai_tokens_limit"] == 1_000_000
    assert usage["api_calls_limit"] == 10_000

    subscription = db_session.query(Subscription).filter(
        Subscription.tenant_id == 1
    ).first()

    assert subscription.stripe_subscription_id == "sub_test_123"
    assert subscription.stripe_customer_id == "cus_test_123"
    assert subscription.status == "active"


def test_duplicate_webhook_event_ignored(client, seed_data, db_session):
    body, header = make_stripe_event(
        "checkout.session.completed",
        checkout_completed_data(tenant_id=1, subscription_id="sub_dup_1", plan="Pro"),
    )

    first = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})
    second = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    assert first.status_code == 200
    assert first.json()["status"] == "processed"

    assert second.status_code == 200
    assert second.json()["status"] == "ignored"

    # Only one marker row, and only one subscription row for the tenant.
    processed = db_session.query(StripeWebhookEvent).all()
    assert len(processed) == 1

    subscriptions = db_session.query(Subscription).filter(
        Subscription.tenant_id == 1
    ).all()

    assert len(subscriptions) == 1
    assert subscriptions[0].stripe_subscription_id == "sub_dup_1"


def test_subscription_updated_syncs_status(client, seed_data):
    body, header = make_stripe_event(
        "checkout.session.completed",
        checkout_completed_data(tenant_id=1, subscription_id="sub_abc", plan="Pro"),
    )
    client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    body, header = make_stripe_event(
        "customer.subscription.updated",
        subscription_object(subscription_id="sub_abc", status="past_due", price_id="price_pro_test"),
    )
    response = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    # A past-due subscription is no longer considered active -> 402 on usage.
    usage = client.get("/usage", headers={"X-Tenant-ID": "1"})
    assert usage.status_code == 402

    # Reactivate.
    body, header = make_stripe_event(
        "customer.subscription.updated",
        subscription_object(subscription_id="sub_abc", status="active", price_id="price_pro_test"),
    )
    client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    usage = client.get("/usage", headers={"X-Tenant-ID": "1"})
    assert usage.status_code == 200
    assert usage.json()["plan"] == "Pro"


def test_subscription_deleted_cancels_tenant(client, seed_data, db_session):
    body, header = make_stripe_event(
        "checkout.session.completed",
        checkout_completed_data(tenant_id=1, subscription_id="sub_del", plan="Pro"),
    )
    client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    body, header = make_stripe_event(
        "customer.subscription.deleted",
        subscription_object(subscription_id="sub_del", status="canceled"),
    )
    response = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    subscription = db_session.query(Subscription).filter(
        Subscription.tenant_id == 1
    ).first()

    assert subscription.status == "canceled"
    assert subscription.end_date is not None

    # Canceled subscription -> no billable requests.
    generate = client.post(
        "/generate",
        headers={"Idempotency-Key": "after-cancel", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 1},
    )

    assert generate.status_code == 402


def test_plan_downgrade_via_subscription_updated(client, seed_data):
    body, header = make_stripe_event(
        "checkout.session.completed",
        checkout_completed_data(tenant_id=1, subscription_id="sub_dn", plan="Pro"),
    )
    client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    assert client.get("/usage", headers={"X-Tenant-ID": "1"}).json()["plan"] == "Pro"

    # New price not matching Pro -> Free plan.
    body, header = make_stripe_event(
        "customer.subscription.updated",
        subscription_object(subscription_id="sub_dn", status="active", price_id="price_free_x"),
    )
    response = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    assert response.status_code == 200

    usage = client.get("/usage", headers={"X-Tenant-ID": "1"}).json()
    assert usage["plan"] == "Free"
    assert usage["api_calls_limit"] == 1000


def test_unhandled_event_type_is_ignored_but_recorded(client, seed_data):
    body, header = make_stripe_event(
        "invoice.payment_succeeded",
        {"id": "in_123"},
    )

    response = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": header})

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
