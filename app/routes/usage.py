from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import USAGE_TYPE_AI_TOKENS, USAGE_TYPE_API_CALLS
from ..database import get_db
from ..models import Tenant, UsageEvent
from ..schemas import UsageResponse
from ..services.cost import CostService
from ..services.metering import MeteringService
from ..services.subscription import SubscriptionService
from .deps import get_tenant_id


router = APIRouter(
    prefix="/usage",
    tags=["billing"],
)


@router.get("", response_model=UsageResponse)
def get_usage(
    tenant_id: int = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    subscription_plan = SubscriptionService(db).get_subscription_and_plan(tenant.id)

    if subscription_plan is None:
        raise HTTPException(
            status_code=402,
            detail="Payment required: no active subscription for this tenant",
        )

    subscription, plan = subscription_plan

    metering = MeteringService(db)
    cost_service = CostService()

    api_used = metering.get_usage(tenant.id, USAGE_TYPE_API_CALLS)
    token_used = metering.get_usage(tenant.id, USAGE_TYPE_AI_TOKENS)

    cost_micros = _total_cost_micros(db, tenant.id, cost_service)

    return UsageResponse(
        tenant_id=tenant.id,
        plan=plan.name,
        subscription_status=subscription.status,
        api_calls_used=api_used,
        api_calls_limit=plan.api_call_limit,
        api_calls_remaining=plan.api_call_limit - api_used,
        ai_tokens_used=token_used,
        ai_tokens_limit=plan.ai_token_limit,
        ai_tokens_remaining=plan.ai_token_limit - token_used,
        cost_micros=cost_micros,
        cost_cents=cost_service.micros_to_cents(cost_micros),
    )


def _total_cost_micros(db: Session, tenant_id: int, cost_service: CostService) -> int:
    """Sum the exact cost of every AI token event belonging to the tenant."""
    events = db.scalars(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == USAGE_TYPE_AI_TOKENS,
        )
    ).all()

    total = 0

    for event in events:
        metadata = event.payload or {}

        if "cost_micros" in metadata:
            total += int(metadata["cost_micros"])
        else:
            total += cost_service.cost_from_event_metadata(metadata)

    return total
