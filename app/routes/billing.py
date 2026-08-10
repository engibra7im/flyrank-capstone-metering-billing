import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..constants import PLAN_NAMES
from ..database import get_db
from ..models import Tenant
from ..schemas import CheckoutRequest, CheckoutResponse
from ..services.stripe_service import StripeService
from .deps import get_tenant_id


router = APIRouter(
    prefix="/billing",
    tags=["billing"],
)


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    body: CheckoutRequest,
    tenant_id: int = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    if body.plan not in PLAN_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"plan must be one of {list(PLAN_NAMES)}",
        )

    tenant = db.get(Tenant, tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    try:
        result = StripeService().create_checkout_session(
            tenant_id=tenant.id,
            plan_name=body.plan,
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        )
    except stripe.error.StripeError as error:
        # A configured-but-invalid test key must not become an HTTP 500 or leak
        # any key material.
        raise HTTPException(
            status_code=503,
            detail="Stripe service unavailable; check STRIPE_SECRET_KEY",
        )

    return CheckoutResponse(**result)
