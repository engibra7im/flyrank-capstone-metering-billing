"""Stripe integration (test mode only).

This module isolates everything Stripe-specific from the core business logic.
The rest of the application never talks to the Stripe API directly.

Secrets always come from the environment (settings). They are never logged.
"""

from __future__ import annotations

import stripe

from ..config import settings


class StripeService:
    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key or settings.stripe_secret_key

        if self.secret_key:
            stripe.api_key = self.secret_key

    def create_checkout_session(self, tenant_id: int, plan_name: str) -> dict:
        """Create a Stripe Checkout session for a subscription (test mode)."""
        if not self.secret_key:
            raise RuntimeError(
                "STRIPE_SECRET_KEY is not configured; Checkout is unavailable"
            )

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": settings.stripe_pro_price_id,
                    "quantity": 1,
                }
            ],
            metadata={
                "tenant_id": str(tenant_id),
                "plan": plan_name,
            },
            client_reference_id=str(tenant_id),
            success_url=settings.stripe_success_url,
            cancel_url=settings.stripe_cancel_url,
        )

        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "tenant_id": tenant_id,
            "plan": plan_name,
        }

    def construct_event(self, payload: bytes, signature_header: str):
        """Verify a Stripe webhook signature and return the event object.

        Raises ``ValueError`` or ``stripe.error.SignatureVerificationError``
        when the signature is invalid.
        """
        return stripe.Webhook.construct_event(
            payload,
            signature_header,
            settings.stripe_webhook_secret,
        )


# Re-export so tests/webhook code can reference the verification error type.
SignatureVerificationError = stripe.error.SignatureVerificationError
