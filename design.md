# Usage Metering & Billing Engine — Design Document

## 1. Project Overview

### Project Name
LLM Usage Metering & Billing Engine

### Repository
`flyrank-capstone-metering-billing`

### Purpose
This project is a backend service for SaaS applications that need to track customer usage, enforce subscription quotas, calculate usage costs, and synchronize subscription state with Stripe.

The service answers three core questions:
1. How much has a customer used?
2. How much should that usage cost?
3. Has the customer reached their plan limit?

The system focuses on correctness under retries, quota boundaries, duplicate webhooks, and billing-related edge cases.

---

## 2. Problem

SaaS applications often need to limit and charge customers based on their usage.

For an LLM-powered SaaS product, usage may include:
- API calls
- Input tokens
- Cached input tokens
- Output tokens
- Reasoning tokens

A naive implementation can create serious problems:
- A retried request could count twice.
- A customer could exceed their plan quota.
- Two identical Stripe webhooks could update the subscription twice.
- Floating-point money calculations could produce incorrect results.
- A forged webhook could modify subscription status.

This service is designed to make usage, quotas, cost calculation, and subscription synchronization predictable and safe.

---

## 3. Goals

### 3.1 Usage Metering
Record billable usage for each tenant.

The system must guarantee:

> The same billable request with the same idempotency key creates only one usage event.

### 3.2 Quota Enforcement
Check the tenant's current usage against the limits of its subscription plan before allowing a billable action.

| Plan | API Calls / Month | AI Tokens / Month |
|---|---:|---:|
| Free | 1,000 | 100,000 |
| Pro | Higher limit | Higher limit |

The exact Pro limits will be defined in configuration.

### 3.3 Cost Calculation
Calculate monthly usage cost per tenant.

The system must correctly handle:
- input tokens
- cached input tokens
- output tokens
- reasoning tokens

Pricing values will be stored as configuration constants and covered by tests.

Money will be stored as integer cents or another integer micro-unit. Floating-point values will not be used for persisted monetary values.

### 3.4 Stripe Subscription Synchronization
The system will integrate with Stripe in test mode.

It will support:
- Stripe Checkout
- subscription creation
- subscription updates
- subscription deletion
- webhook signature verification
- duplicate webhook prevention
- synchronization of tenant plan/status

Stripe remains the source of truth for payment and subscription events.

---

## 4. Non-Goals

The following are intentionally outside the core scope:
- Real payments
- Stripe live mode
- Invoicing
- Proration
- Complex overage billing
- Calling a real LLM provider
- Building an LLM
- Full customer-facing billing UI

AI token usage will be simulated.

Stripe will only be used in test mode.

---

## 5. System Scope

The core system contains:
- 2 subscription plans
- 2 usage types
- 1 billable endpoint
- Usage metering
- Quota enforcement
- Cost calculation
- Stripe Checkout
- Stripe webhooks
- Idempotency
- Persistent storage
- Automated tests

### Usage Types

```text
API_CALL
AI_TOKENS
```

AI token usage can contain:

```text
input_tokens
cached_input_tokens
output_tokens
reasoning_tokens
```

No real AI model call is required.

---

## 6. High-Level Architecture

```text
                         ┌─────────────────┐
                         │     Client      │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   HTTP / API    │
                         │     Layer       │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Metering Service│
                         └────────┬────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
             ┌────────────┐ ┌────────────┐ ┌──────────────┐
             │ Idempotency│ │   Quota    │ │     Cost     │
             │   Check    │ │   Check    │ │  Calculator  │
             └────────────┘ └────────────┘ └──────────────┘
                    │             │             │
                    └─────────────┼─────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    Database     │
                         │ tenants         │
                         │ plans           │
                         │ subscriptions   │
                         │ usage_events    │
                         └─────────────────┘

        ┌────────────────────┐
        │       Stripe       │
        │    Test Mode       │
        └─────────┬──────────┘
                  │ signed webhook
                  ▼
        ┌────────────────────┐
        │ Webhook Handler    │
        └─────────┬──────────┘
                  │
          ┌───────┴────────┐
          ▼                ▼
    Signature Check   Event Deduplication
          │                │
          └───────┬────────┘
                  ▼
        ┌────────────────────┐
        │ Subscription Sync  │
        └─────────┬──────────┘
                  ▼
              Database
```

---

## 7. Application Layers

### 7.1 HTTP / API Layer
Responsible for receiving requests, validating input, extracting tenant information, reading the `Idempotency-Key`, returning HTTP responses, and translating business errors into status codes.

The HTTP layer should not contain core billing logic.

### 7.2 Service Layer
Contains the main business logic.

Examples:
```text
MeteringService
QuotaService
CostService
SubscriptionService
```

### 7.3 Data Layer
Responsible for database operations.

Examples:
```text
TenantRepository
PlanRepository
SubscriptionRepository
UsageEventRepository
```

The data layer isolates database-specific operations from business logic.

### 7.4 Stripe Integration Layer
Responsible for:
- creating Checkout sessions
- verifying webhook signatures
- parsing Stripe events
- detecting duplicate events
- synchronizing subscription state

Stripe-specific logic remains isolated from core metering logic.

---

## 8. Data Model

### 8.1 Tenant

```text
tenants
-------
id
name
created_at
```

Every usage event and subscription belongs to exactly one tenant.

### 8.2 Plan

```text
plans
-----
id
name
api_call_limit
ai_token_limit
created_at
```

The Pro plan will have higher limits.

### 8.3 Subscription

```text
subscriptions
-------------
id
tenant_id
plan_id
stripe_customer_id
stripe_subscription_id
status
created_at
updated_at
```

### 8.4 Usage Event

```text
usage_events
------------
id
tenant_id
usage_type
quantity
idempotency_key
metadata
created_at
```

For AI usage, additional token information may be stored in structured metadata or dedicated fields depending on the final implementation.

Important constraint:

```text
tenant_id + idempotency_key
```

must uniquely identify a billable request.

---

## 9. Data Relationships

```text
Tenant
  │
  ├──────────────► Subscription
  │                     │
  │                     ▼
  │                    Plan
  │
  └──────────────► Usage Events
```

A tenant may have many usage events.

A tenant has one current subscription.

A subscription references one plan.

Usage events never belong to another tenant.

Tenant isolation is required for all usage and subscription queries.

---

## 10. Plans and Quotas

### Free

```text
API calls:
1,000 / month

AI tokens:
100,000 / month
```

### Pro

The Pro plan has higher limits.

The exact values will be defined in application configuration rather than hard-coded throughout the business logic.

Quota flow:

```text
current usage
      +
requested usage
      |
      ▼
compare with plan limit
      |
   ┌──┴──┐
   │     │
under   over
   │     │
   ▼     ▼
allow   reject
```

The quota must be checked before creating the billable usage event.

---

## 11. Idempotency Strategy

A client sends:

```http
Idempotency-Key: abc-123
```

with a billable request.

The service checks whether this key has already been processed for the tenant.

### First request

```text
Request
   |
   ▼
Check idempotency key
   |
   ▼
Key does not exist
   |
   ▼
Check quota
   |
   ▼
Record usage event
   |
   ▼
Return result
```

### Retry

```text
Request
   |
   ▼
Check idempotency key
   |
   ▼
Key already exists
   |
   ▼
Return original result
```

The retry must not create another usage event.

The database will enforce uniqueness so application-level checks are not the only protection against duplicates.

---

## 12. Billable Endpoint

The initial billable endpoint will be:

```http
POST /generate
```

It simulates an AI generation request.

Example request:

```json
{
  "input_tokens": 1000,
  "cached_input_tokens": 200,
  "output_tokens": 500,
  "reasoning_tokens": 100
}
```

The endpoint will:
1. Identify the tenant.
2. Read the idempotency key.
3. Check whether the request was already processed.
4. Calculate requested usage.
5. Check the tenant's quota.
6. Record the usage event.
7. Calculate the associated cost.
8. Return the result.

No real LLM API call is required.

---

## 13. Usage API

The service will expose:

```http
GET /usage
```

Conceptual response:

```json
{
  "used": {
    "api_calls": 10,
    "ai_tokens": 2500
  },
  "limit": {
    "api_calls": 1000,
    "ai_tokens": 100000
  },
  "cost": {
    "amount": 123
  }
}
```

The exact response structure may be adjusted during implementation while preserving the required information.

The endpoint calculates usage by rolling up usage events belonging to the tenant.

---

## 14. Quota Error Handling

When a request exceeds the tenant's allowed usage, the service must reject it.

For usage quota exhaustion:

```http
429 Too Many Requests
```

The response should clearly explain the reason.

For subscription/payment-related restrictions:

```http
402 Payment Required
```

The final implementation will document exactly when `429` and `402` are used.

---

## 15. Cost Calculation

Cost calculation is separated from usage recording.

```text
Input tokens
      +
Cached input tokens
      +
Output tokens
      +
Reasoning tokens
      |
      ▼
Cost Calculator
      |
      ▼
Total cost
```

Rules:
- Cached input tokens are priced differently from normal input tokens.
- Reasoning tokens count as output tokens.
- Token categories must not be incorrectly double-counted.
- Pricing constants are stored in configuration.
- Pricing calculations are covered by deterministic tests.

---

## 16. Money Representation

Money will never be stored as floating-point values.

The system will use integer units such as:

```text
cents
```

Example:

```text
$12.50
```

is stored as:

```text
1250
```

This prevents floating-point precision problems in persisted monetary values.

---

## 17. Stripe Integration

Stripe will be used only in test mode.

Core flow:

```text
Customer
   |
   ▼
Backend
   |
   ▼
Stripe Checkout
   |
   ▼
Test Subscription
   |
   ▼
Stripe Webhook
   |
   ▼
Webhook Handler
   |
   ▼
Verify Signature
   |
   ▼
Deduplicate Event
   |
   ▼
Update Subscription
   |
   ▼
Update Tenant Plan
```

---

## 18. Stripe Checkout

The backend will provide:

```http
POST /billing/checkout
```

The customer selects the Pro plan.

Stripe handles the test checkout.

After successful checkout, Stripe sends a webhook to the backend.

The local subscription state is updated only after receiving and verifying the appropriate Stripe event.

---

## 19. Stripe Webhooks

The system will handle:

```text
checkout.session.completed
customer.subscription.updated
customer.subscription.deleted
```

### Signature verification

The Stripe webhook signature must be verified before processing the event.

Invalid signatures result in:

```http
400 Bad Request
```

No subscription state should change.

### Event deduplication

Stripe events can be delivered more than once.

The service must record processed Stripe event IDs.

If the same event is received again, it is ignored without applying the state change twice.

---

## 20. Stripe Secrets

Stripe credentials must never be committed to GitHub.

They will be loaded from environment variables:

```text
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

The real values will exist only in `.env`.

The repository will contain `.env.example` with safe placeholder values.

`.env` will be included in `.gitignore`.

---

## 21. API Surface

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/generate` | Execute a billable simulated AI request |
| GET | `/usage` | Return tenant usage, limits, and cost |
| POST | `/billing/checkout` | Create Stripe Checkout session |
| POST | `/webhooks/stripe` | Receive Stripe subscription events |

Additional endpoints may be added only if required by the implementation.

---

## 22. Request Flow — Billable Usage

```text
POST /generate
      |
      ▼
Validate request
      |
      ▼
Identify tenant
      |
      ▼
Read Idempotency-Key
      |
      ▼
Already processed?
   ┌──┴──┐
  YES    NO
   │      │
   ▼      ▼
Return   Check quota
original    |
result      ▼
         Allowed?
        ┌──┴──┐
       NO     YES
        │       │
        ▼       ▼
      429/402  Record usage
                  |
                  ▼
             Calculate cost
                  |
                  ▼
              Return result
```

---

## 23. Request Flow — Stripe Webhook

```text
Stripe
  |
  ▼
POST /webhooks/stripe
  |
  ▼
Verify signature
  |
 ┌┴────────────┐
 │             │
Invalid       Valid
 │             │
 ▼             ▼
400        Check event ID
               |
          ┌────┴────┐
          │         │
       Duplicate   New
          │         │
          ▼         ▼
        Ignore    Process
                    |
                    ▼
             Update subscription
                    |
                    ▼
                Update plan
```

---

## 24. Database Constraints

### Usage event idempotency

A unique constraint should prevent duplicate usage events for the same tenant and idempotency key.

```text
UNIQUE (
    tenant_id,
    idempotency_key
)
```

### Tenant isolation

Every usage event must contain a valid `tenant_id` foreign key.

### Subscription relationships

Subscriptions must reference valid:

```text
tenant_id
plan_id
```

---

## 25. Testing Strategy

Tests will focus on correctness rather than only happy paths.

### Idempotency

```text
same request
+
same idempotency key
=
one usage event
```

### Quota boundary

Test:
```text
just below limit
exactly at limit
just above limit
```

### Cost calculation

Test:
```text
normal input tokens
cached input tokens
output tokens
reasoning tokens
```

### Stripe

Test:
```text
valid webhook
invalid signature
duplicate webhook
```

The tests should be deterministic.

---

## 26. Phase 1 Acceptance Gate

Phase 1 is complete when this design document clearly defines:

- Database schema
- Tenants
- Plans
- Subscriptions
- Usage events
- Plan quotas
- Metering API contract
- Idempotency strategy
- Layered architecture
- Stripe integration boundary
- Explicit non-goals

The design should be reviewed before implementation begins.

---

## 27. Implementation Principles

The implementation will prioritize:

1. Correctness over feature count.
2. Idempotency for retried operations.
3. Explicit quota boundaries.
4. Integer-based money representation.
5. Tenant data isolation.
6. Verified Stripe webhooks.
7. Duplicate webhook protection.
8. Deterministic tests.
9. Clear separation between HTTP, business logic, and persistence.
10. Small, understandable scope.

---

## 28. Explicit Non-Goal for Core Version

The core version will **not** implement real LLM calls.

AI token usage will be simulated through request data.

The purpose of the project is to demonstrate:

```text
metering
+
quota enforcement
+
cost calculation
+
idempotency
+
Stripe subscription synchronization
```

rather than building an AI application itself.

---

## 29. Phase 1 Decision

### Selected Capstone
**Usage Metering & Billing Engine**

### Language
Python

### Planned Backend Framework
FastAPI

### Database
PostgreSQL through Docker

### Payment Provider
Stripe Test Mode

### Webhook Development
Stripe CLI

### Repository
`flyrank-capstone-metering-billing`

### Core Scope

```text
2 plans
2 usage types
1 billable endpoint
usage metering
quota enforcement
cost calculation
Stripe Checkout
Stripe webhooks
idempotency
automated tests
```

---

## 30. Phase 1 Status

```text
[x] Problem defined
[x] Goals defined
[x] Non-goals defined
[x] Data model designed
[x] Plans and quotas defined
[x] API surface defined
[x] Idempotency strategy defined
[x] Architecture designed
[x] Stripe integration flow defined
[x] Testing strategy defined
[ ] Implementation
```

**Phase 1 gate: Design complete — ready to begin Phase 2.**

---

## 31. Implementation Status (Phases 2–5)

### Phase 2 — Core billing logic (`[x]` complete)

```text
[x] Idempotent usage recording (unique constraint + IntegrityError handling)
[x] Duplicate request protection (concurrent-safe, tested with real threads)
[x] Correct quota enforcement (just below / exactly at / just above limit)
[x] Correct HTTP status codes (429 quota, 402 payment, 422 validation, 404 tenant)
[x] Input validation (usage_type, quantity, token categories, idempotency key)
[x] Tenant isolation (X-Tenant-ID header; every query scoped by tenant)
[x] Usage endpoint (GET /usage with monthly rollup + cost)
[x] Billable endpoint (POST /generate; api_calls and ai_tokens modes)
[x] Tests (metering, quota boundaries, isolation, validation)
```

Implementation notes and deviations from the Phase 1 design:

- Usage types are stored lowercase as `api_calls` and `ai_tokens` (the design
  used `API_CALL` / `AI_TOKENS`); constants live in `app/constants.py`.
- The billable request body carries either `quantity` (api_calls) or a token
  breakdown (ai_tokens), matching the Phase 1 example request.
- `record_usage` performs the INSERT first and relies on the database unique
  constraint `UNIQUE(tenant_id, idempotency_key)`; a lost race rolls back and
  returns the winner's row. No SELECT-then-INSERT.

### Phase 3 — Stripe integration (`[x]` complete)

```text
[x] Checkout session creation        (POST /billing/checkout)
[x] Subscription creation            (Stripe Checkout, test mode)
[x] Stripe webhook endpoint          (POST /webhooks/stripe)
[x] Signature verification           (stripe.Webhook.construct_event)
[x] Webhook deduplication            (stripe_webhook_events.event_id UNIQUE)
[x] Tenant plan synchronization      (only via verified events)
[x] Handled events                   checkout.session.completed,
                                     customer.subscription.updated,
                                     customer.subscription.deleted
```

Security notes:

- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRO_PRICE_ID` are read
  from the environment; `.env` is git-ignored; `.env.example` has placeholders.
- Invalid signatures return `400` and change no state.
- Stripe-specific code is isolated in `app/services/stripe_service.py`
  (API client + signature verification) and `app/services/webhook_sync.py`
  (event application), keeping core business logic Stripe-free.

### Phase 4 — Cost calculation (`[x]` complete)

```text
[x] Integer money units              micro-dollars (1e-6 USD), never float
[x] input / cached_input / output / reasoning token pricing
[x] Cached input cheaper than input
[x] Reasoning tokens billed as output
[x] Centralized pricing constants    app/services/cost.py
[x] Pinned pricing tests             tests/test_cost.py
[x] Usage rollup with cost           GET /usage -> cost_micros / cost_cents
```

Pricing table (micro-dollars per token == USD per 1M tokens):

| category | µ$/token | USD/1M |
|---|---:|---:|
| input | 3 | $3.00 |
| cached input | 1 | $1.00 |
| output | 15 | $15.00 |
| reasoning | 15 | $15.00 |

### Phase 5 — Background job, demo & docs (`[x]` complete)

```text
[x] Background job: monthly usage aggregation (app/jobs/rollup.py)
    - retry-safe upsert, duplicate-safe via UNIQUE(tenant, type, period)
    - runs periodically in-process + via `python -m app.jobs.rollup`
[x] README.md, EVIDENCE.md, BUILDLOG.md, capstone.yaml, .env.example
[x] Architecture diagram (ASCII, see README)
[x] Full test suite + acceptance probes
```

### Data model additions beyond Phase 1

```text
subscriptions      + stripe_customer_id, stripe_subscription_id, updated_at
usage_events       + payload (JSON token breakdown + stored cost)
stripe_webhook_events   new table (processed event dedup)
usage_snapshots         new table (background rollup output)
```

### Documented HTTP status semantics

| Code | Meaning |
|---|---|
| 200 | Success (including idempotent replays) |
| 400 | Invalid Stripe signature / malformed webhook |
| 404 | Unknown tenant |
| 422 | Validation error (usage type, quantity, tokens, tenant header) |
| 429 | Usage quota exceeded |
| 402 | No active subscription / payment required |
| 503 | Stripe Checkout unavailable (no key configured) |
