from pydantic import BaseModel, Field, field_validator, model_validator

from .constants import (
    USAGE_TYPE_API_CALLS,
    USAGE_TYPE_AI_TOKENS,
    VALID_USAGE_TYPES,
)


class GenerateRequest(BaseModel):
    """Body for the billable POST /generate endpoint.

    Two usage modes:

      * api_calls  -> requires ``quantity`` (number of API calls)
      * ai_tokens  -> requires at least one token category > 0
    """

    usage_type: str = USAGE_TYPE_API_CALLS
    quantity: int | None = Field(default=None, gt=0)

    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)

    @field_validator("usage_type")
    @classmethod
    def validate_usage_type(cls, value: str) -> str:
        if value not in VALID_USAGE_TYPES:
            raise ValueError(
                f"usage_type must be one of {list(VALID_USAGE_TYPES)}"
            )
        return value

    @model_validator(mode="after")
    def validate_usage_specific_fields(self) -> "GenerateRequest":
        if self.usage_type == USAGE_TYPE_API_CALLS:
            if self.quantity is None:
                raise ValueError("quantity is required for usage_type 'api_calls'")

        if self.usage_type == USAGE_TYPE_AI_TOKENS:
            token_total = (
                self.input_tokens
                + self.cached_input_tokens
                + self.output_tokens
                + self.reasoning_tokens
            )

            if token_total <= 0:
                raise ValueError(
                    "ai_tokens requests must include at least one token category "
                    "with a value greater than zero"
                )

        return self


class GenerateResponse(BaseModel):
    message: str
    tenant_id: int
    usage_type: str
    quantity: int
    usage_event_id: int
    cost_micros: int
    cost_cents: int
    idempotent_replay: bool = False


class UsageResponse(BaseModel):
    tenant_id: int
    plan: str
    subscription_status: str
    api_calls_used: int
    api_calls_limit: int
    api_calls_remaining: int
    ai_tokens_used: int
    ai_tokens_limit: int
    ai_tokens_remaining: int
    cost_micros: int
    cost_cents: int


class CheckoutRequest(BaseModel):
    plan: str = "Pro"


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    tenant_id: int
    plan: str
