"""Shared helpers for building fake (but correctly signed) Stripe webhooks."""

import hashlib
import hmac
import json
import time
import uuid

from tests.conftest import TEST_WEBHOOK_SECRET


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
        "object": "event",
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
