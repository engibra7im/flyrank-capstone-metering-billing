"""Shared domain constants for the metering & billing engine.

Keeping these in one module prevents magic strings from being scattered
throughout the application.
"""

USAGE_TYPE_API_CALLS = "api_calls"
USAGE_TYPE_AI_TOKENS = "ai_tokens"

VALID_USAGE_TYPES = (
    USAGE_TYPE_API_CALLS,
    USAGE_TYPE_AI_TOKENS,
)

# Token categories accepted on the billable endpoint.
TOKEN_INPUT = "input_tokens"
TOKEN_CACHED_INPUT = "cached_input_tokens"
TOKEN_OUTPUT = "output_tokens"
TOKEN_REASONING = "reasoning_tokens"

VALID_TOKEN_CATEGORIES = (
    TOKEN_INPUT,
    TOKEN_CACHED_INPUT,
    TOKEN_OUTPUT,
    TOKEN_REASONING,
)

PLAN_FREE = "Free"
PLAN_PRO = "Pro"

PLAN_NAMES = (PLAN_FREE, PLAN_PRO)

# Stripe subscription statuses relevant to local synchronization.
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_CANCELED = "canceled"
SUBSCRIPTION_STATUS_PAST_DUE = "past_due"
SUBSCRIPTION_STATUS_UNPAID = "unpaid"
SUBSCRIPTION_STATUS_INCOMPLETE = "incomplete"

# Stripe webhook events we care about.
WEBHOOK_CHECKOUT_COMPLETED = "checkout.session.completed"
WEBHOOK_SUBSCRIPTION_UPDATED = "customer.subscription.updated"
WEBHOOK_SUBSCRIPTION_DELETED = "customer.subscription.deleted"

HANDLED_WEBHOOK_EVENTS = (
    WEBHOOK_CHECKOUT_COMPLETED,
    WEBHOOK_SUBSCRIPTION_UPDATED,
    WEBHOOK_SUBSCRIPTION_DELETED,
)

# Header used to select the tenant on the demo API.
TENANT_HEADER = "X-Tenant-ID"
IDEMPOTENCY_HEADER = "Idempotency-Key"

DEFAULT_TENANT_ID = 1
