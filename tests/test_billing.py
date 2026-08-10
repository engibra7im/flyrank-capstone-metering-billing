"""Stripe Checkout endpoint tests (Stripe API calls are mocked)."""

from types import SimpleNamespace

import app.services.stripe_service as stripe_service


def test_checkout_session_created(client, seed_data, monkeypatch):
    fake_session = SimpleNamespace(
        id="cs_test_123",
        url="https://checkout.stripe.com/c/pay/cs_test_123",
    )

    def fake_create(**kwargs):
        return fake_session

    monkeypatch.setattr(
        stripe_service.stripe.checkout.Session, "create", fake_create
    )
    monkeypatch.setattr(
        stripe_service.settings, "stripe_secret_key", "sk_test_fake"
    )

    response = client.post(
        "/billing/checkout",
        headers={"X-Tenant-ID": "1"},
        json={"plan": "Pro"},
    )

    assert response.status_code == 200

    body = response.json()

    assert body["session_id"] == "cs_test_123"
    assert body["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_123"
    assert body["tenant_id"] == 1
    assert body["plan"] == "Pro"


def test_checkout_invalid_plan_rejected(client, seed_data):
    response = client.post(
        "/billing/checkout",
        headers={"X-Tenant-ID": "1"},
        json={"plan": "Enterprise"},
    )

    assert response.status_code == 422


def test_checkout_requires_stripe_key(client, seed_data):
    # stripe_secret_key is "" in tests by default -> service refuses.
    response = client.post(
        "/billing/checkout",
        headers={"X-Tenant-ID": "1"},
        json={"plan": "Pro"},
    )

    assert response.status_code == 503


def test_checkout_handles_stripe_api_error(client, seed_data, monkeypatch):
    import stripe

    def boom(**kwargs):
        raise stripe.error.AuthenticationError("invalid key")

    monkeypatch.setattr(
        stripe_service.stripe.checkout.Session, "create", boom
    )
    monkeypatch.setattr(
        stripe_service.settings, "stripe_secret_key", "sk_test_bad"
    )

    response = client.post(
        "/billing/checkout",
        headers={"X-Tenant-ID": "1"},
        json={"plan": "Pro"},
    )

    assert response.status_code == 503
    assert "STRIPE_SECRET_KEY" in response.json()["detail"]


def test_checkout_for_unknown_tenant_returns_404(client, seed_data):
    response = client.post(
        "/billing/checkout",
        headers={"X-Tenant-ID": "999"},
        json={"plan": "Pro"},
    )

    assert response.status_code == 404
