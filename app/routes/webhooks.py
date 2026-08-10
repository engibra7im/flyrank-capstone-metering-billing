from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..services.stripe_service import SignatureVerificationError, StripeService
from ..services.webhook_sync import WebhookSyncService


router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
)


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature", "")

    if not signature_header:
        raise HTTPException(
            status_code=400,
            detail="Missing stripe-signature header",
        )

    try:
        event = StripeService().construct_event(payload, signature_header)
    except (ValueError, SignatureVerificationError):
        # Never reveal secret material; just reject.
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe signature",
        )

    result = WebhookSyncService(
        db, stripe_pro_price_id=settings.stripe_pro_price_id
    ).handle(event)

    return result
