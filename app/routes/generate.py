from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..constants import (
    USAGE_TYPE_AI_TOKENS,
    USAGE_TYPE_API_CALLS,
)
from ..database import get_db
from ..models import Tenant, UsageEvent
from ..schemas import GenerateRequest, GenerateResponse
from ..services.cost import CostService
from ..services.metering import MeteringService
from ..services.quota import QuotaExceededError, check_quota
from ..services.subscription import SubscriptionService
from .deps import get_tenant_id


router = APIRouter(
    prefix="/generate",
    tags=["billing"],
)


@router.post("", response_model=GenerateResponse)
def generate(
    body: GenerateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    tenant_id: int = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key header is required and cannot be blank",
        )

    tenant = db.get(Tenant, tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    subscription_service = SubscriptionService(db)
    subscription_plan = subscription_service.get_subscription_and_plan(tenant.id)

    if subscription_plan is None:
        raise HTTPException(
            status_code=402,
            detail="Payment required: no active subscription for this tenant",
        )

    _, plan = subscription_plan

    metering = MeteringService(db)
    cost_service = CostService()

    existing = metering.get_existing(tenant.id, idempotency_key)

    if existing is not None:
        # Idempotent retry: return the exact original operation, never double-count.
        return _build_response(existing, plan.name, cost_service, replay=True)

    usage_type, quantity, metadata = _requested_usage(body, cost_service)

    # Quota check BEFORE recording usage.
    if usage_type == USAGE_TYPE_API_CALLS:
        limit = plan.api_call_limit
        current = metering.get_usage(tenant.id, usage_type)
    else:
        limit = plan.ai_token_limit
        current = metering.get_usage(tenant.id, USAGE_TYPE_AI_TOKENS)

    try:
        check_quota(
            current_usage=current,
            requested_quantity=quantity,
            limit=limit,
            usage_type=usage_type,
        )
    except QuotaExceededError as error:
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"{usage_type} quota exceeded",
                "usage_type": usage_type,
                "used": error.used,
                "requested": error.requested,
                "limit": error.limit,
            },
        )

    event = metering.record_usage(
        tenant_id=tenant.id,
        usage_type=usage_type,
        quantity=quantity,
        idempotency_key=idempotency_key,
        payload=metadata,
    )

    return _build_response(event, plan.name, cost_service, replay=False)


def _requested_usage(body: GenerateRequest, cost_service: CostService):
    """Determine (usage_type, quantity, metadata) from a validated request."""
    if body.usage_type == USAGE_TYPE_API_CALLS:
        return (
            USAGE_TYPE_API_CALLS,
            body.quantity,
            None,
        )

    metadata = {
        "input_tokens": body.input_tokens,
        "cached_input_tokens": body.cached_input_tokens,
        "output_tokens": body.output_tokens,
        "reasoning_tokens": body.reasoning_tokens,
        "cost_micros": cost_service.cost_micros(
            input_tokens=body.input_tokens,
            cached_input_tokens=body.cached_input_tokens,
            output_tokens=body.output_tokens,
            reasoning_tokens=body.reasoning_tokens,
        ),
    }

    return (
        USAGE_TYPE_AI_TOKENS,
        cost_service.total_tokens(
            input_tokens=body.input_tokens,
            cached_input_tokens=body.cached_input_tokens,
            output_tokens=body.output_tokens,
            reasoning_tokens=body.reasoning_tokens,
        ),
        metadata,
    )


def _build_response(
    event: UsageEvent,
    plan_name: str,
    cost_service: CostService,
    replay: bool,
) -> GenerateResponse:
    cost_micros = 0

    if event.usage_type == USAGE_TYPE_AI_TOKENS and event.payload:
        cost_micros = cost_service.cost_from_event_metadata(event.payload)

    return GenerateResponse(
        message="Generation request accepted",
        tenant_id=event.tenant_id,
        usage_type=event.usage_type,
        quantity=event.quantity,
        usage_event_id=event.id,
        cost_micros=cost_micros,
        cost_cents=cost_service.micros_to_cents(cost_micros),
        idempotent_replay=replay,
    )
