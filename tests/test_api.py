"""API-level behavior tests for the billable, usage and health endpoints."""

from app.models import UsageEvent
from app.services.cost import CostService


def test_health_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_successful_billable_request(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "key-1", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 3},
    )

    assert response.status_code == 200

    body = response.json()

    assert body["tenant_id"] == 1
    assert body["usage_type"] == "api_calls"
    assert body["quantity"] == 3
    assert body["usage_event_id"] is not None
    assert body["idempotent_replay"] is False


def test_duplicate_idempotency_key_counts_once(client, seed_data, db_session):
    payload = {"usage_type": "api_calls", "quantity": 5}
    headers = {"Idempotency-Key": "same-key-abc", "X-Tenant-ID": "1"}

    first = client.post("/generate", headers=headers, json=payload)
    second = client.post("/generate", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()

    # Same operation: same usage event id, no double counting.
    assert first_body["usage_event_id"] == second_body["usage_event_id"]
    assert first_body["quantity"] == second_body["quantity"]
    assert second_body["idempotent_replay"] is True

    events = db_session.query(UsageEvent).filter(
        UsageEvent.tenant_id == 1,
        UsageEvent.idempotency_key == "same-key-abc",
    ).all()

    assert len(events) == 1

    usage = client.get("/usage", headers={"X-Tenant-ID": "1"}).json()
    assert usage["api_calls_used"] == 5


def test_different_idempotency_keys_create_distinct_events(client, seed_data, db_session):
    headers = {"X-Tenant-ID": "1"}

    a = client.post(
        "/generate",
        headers={**headers, "Idempotency-Key": "key-A"},
        json={"usage_type": "api_calls", "quantity": 1},
    )
    b = client.post(
        "/generate",
        headers={**headers, "Idempotency-Key": "key-B"},
        json={"usage_type": "api_calls", "quantity": 1},
    )

    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["usage_event_id"] != b.json()["usage_event_id"]

    count = db_session.query(UsageEvent).filter(
        UsageEvent.tenant_id == 1
    ).count()

    assert count == 2


def test_same_key_allowed_for_different_tenants(client, seed_data, db_session):
    headers = {"Idempotency-Key": "shared-key", "X-Tenant-ID": "1"}
    tenant1 = client.post("/generate", headers=headers, json={"usage_type": "api_calls", "quantity": 1})
    tenant2 = client.post("/generate", headers={**headers, "X-Tenant-ID": "2"}, json={"usage_type": "api_calls", "quantity": 1})

    assert tenant1.status_code == 200
    assert tenant2.status_code == 200

    usage_tenant1 = client.get("/usage", headers={"X-Tenant-ID": "1"}).json()
    usage_tenant2 = client.get("/usage", headers={"X-Tenant-ID": "2"}).json()

    assert usage_tenant1["api_calls_used"] == 1
    assert usage_tenant2["api_calls_used"] == 1


def test_invalid_quantity_rejected(client, seed_data):
    for bad in [0, -1, -100]:
        response = client.post(
            "/generate",
            headers={"Idempotency-Key": f"bad-{bad}", "X-Tenant-ID": "1"},
            json={"usage_type": "api_calls", "quantity": bad},
        )

        assert response.status_code == 422, f"quantity={bad} must be rejected"


def test_non_integer_quantity_rejected(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "bad-type", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": "three"},
    )

    assert response.status_code == 422


def test_invalid_usage_type_rejected(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "bad-usage", "X-Tenant-ID": "1"},
        json={"usage_type": "galaxies", "quantity": 1},
    )

    assert response.status_code == 422


def test_missing_idempotency_key_rejected(client, seed_data):
    response = client.post(
        "/generate",
        json={"usage_type": "api_calls", "quantity": 1},
    )

    assert response.status_code == 422


def test_ai_tokens_requires_positive_tokens(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "zero-tokens", "X-Tenant-ID": "1"},
        json={"usage_type": "ai_tokens"},
    )

    assert response.status_code == 422


def test_quota_just_below_limit(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "below-limit", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 999},
    )

    assert response.status_code == 200


def test_quota_exactly_at_limit(client, seed_data):
    client.post(
        "/generate",
        headers={"Idempotency-Key": "fill-to-limit", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 1000},
    )

    usage = client.get("/usage", headers={"X-Tenant-ID": "1"}).json()

    assert usage["api_calls_used"] == 1000
    assert usage["api_calls_remaining"] == 0


def test_quota_above_limit_returns_429(client, seed_data):
    client.post(
        "/generate",
        headers={"Idempotency-Key": "fill-to-limit-2", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 1000},
    )

    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "over-limit-2", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 1},
    )

    assert response.status_code == 429

    body = response.json()["detail"]

    assert body["message"] == "api_calls quota exceeded"
    assert body["used"] == 1000
    assert body["limit"] == 1000


def test_quota_over_limit_single_request_returns_429(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "over-limit-single", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 1001},
    )

    assert response.status_code == 429


def test_ai_token_quota_enforced(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "tokens-at-limit", "X-Tenant-ID": "1"},
        json={
            "usage_type": "ai_tokens",
            "input_tokens": 100_000,
        },
    )

    assert response.status_code == 200

    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "tokens-over-limit", "X-Tenant-ID": "1"},
        json={
            "usage_type": "ai_tokens",
            "input_tokens": 1,
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"]["usage_type"] == "ai_tokens"


def test_tenant_isolation(client, seed_data):
    client.post(
        "/generate",
        headers={"Idempotency-Key": "tenant1-only", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 42},
    )

    usage1 = client.get("/usage", headers={"X-Tenant-ID": "1"}).json()
    usage2 = client.get("/usage", headers={"X-Tenant-ID": "2"}).json()

    assert usage1["api_calls_used"] == 42
    assert usage2["api_calls_used"] == 0


def test_unknown_tenant_returns_404(client, seed_data):
    response = client.get("/usage", headers={"X-Tenant-ID": "999"})

    assert response.status_code == 404


def test_invalid_tenant_header_returns_422(client, seed_data):
    response = client.get("/usage", headers={"X-Tenant-ID": "abc"})

    assert response.status_code == 422


def test_usage_rollup_shape(client, seed_data):
    client.post(
        "/generate",
        headers={"Idempotency-Key": "rollup-1", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 6},
    )
    client.post(
        "/generate",
        headers={"Idempotency-Key": "rollup-2", "X-Tenant-ID": "1"},
        json={
            "usage_type": "ai_tokens",
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 500,
            "reasoning_tokens": 100,
        },
    )

    response = client.get("/usage", headers={"X-Tenant-ID": "1"})

    assert response.status_code == 200

    body = response.json()

    assert body["tenant_id"] == 1
    assert body["plan"] == "Free"
    assert body["subscription_status"] == "active"
    assert body["api_calls_used"] == 6
    assert body["api_calls_limit"] == 1000
    assert body["api_calls_remaining"] == 994
    assert body["ai_tokens_used"] == 1800
    assert body["ai_tokens_limit"] == 100_000
    assert body["ai_tokens_remaining"] == 98_200

    expected_cost = CostService().cost_micros(
        input_tokens=1000,
        cached_input_tokens=200,
        output_tokens=500,
        reasoning_tokens=100,
    )

    assert body["cost_micros"] == expected_cost
    assert body["cost_cents"] == CostService().micros_to_cents(expected_cost)


def test_ai_tokens_generate_response_includes_exact_cost(client, seed_data):
    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "cost-response", "X-Tenant-ID": "1"},
        json={
            "usage_type": "ai_tokens",
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 500,
            "reasoning_tokens": 100,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["usage_type"] == "ai_tokens"
    assert body["quantity"] == 1800
    assert body["cost_micros"] == 12_200
    assert body["cost_cents"] == 1

    # Idempotent replay returns the same cost.
    replay = client.post(
        "/generate",
        headers={"Idempotency-Key": "cost-response", "X-Tenant-ID": "1"},
        json={
            "usage_type": "ai_tokens",
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 500,
            "reasoning_tokens": 100,
        },
    )

    assert replay.status_code == 200
    assert replay.json()["usage_event_id"] == body["usage_event_id"]
    assert replay.json()["cost_micros"] == body["cost_micros"]
    assert replay.json()["idempotent_replay"] is True


def test_no_active_subscription_returns_402(client, seed_data, db_session):
    from app.models import Subscription

    subscription = db_session.query(Subscription).filter(
        Subscription.tenant_id == 1
    ).first()
    subscription.status = "canceled"
    db_session.commit()

    response = client.post(
        "/generate",
        headers={"Idempotency-Key": "no-sub", "X-Tenant-ID": "1"},
        json={"usage_type": "api_calls", "quantity": 1},
    )

    assert response.status_code == 402
