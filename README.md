# Usage Metering & Billing Engine

A small, production-minded backend service that answers three questions for a
multi-tenant SaaS product:

1. **How much has a customer used?**
2. **How much does that usage cost?**
3. **Has the customer reached their plan limits?**

It combines idempotent usage metering, quota enforcement, integer-exact AI
token cost calculation, and Stripe test-mode subscription synchronization —
with correctness as the top priority.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Database](#database)
- [Seed](#seed)
- [Run](#run)
- [Tests](#tests)
- [API](#api)
- [Idempotency](#idempotency)
- [Quota Behavior](#quota-behavior)
- [Pricing & Cost Calculation](#pricing--cost-calculation)
- [Stripe Integration](#stripe-integration)
- [Background Job](#background-job)
- [Limitations](#limitations)
- [Security Notes](#security-notes)

---

## Features

- **Multi-tenant usage tracking** with strict tenant isolation.
- **Idempotent metering** — the same billable request with the same
  `Idempotency-Key` is recorded exactly once, even under concurrent retries.
- **Monthly quotas** with explicit boundary behavior (just below / exactly at /
  just above the limit).
- **Correct HTTP status codes**: `429 Too Many Requests` for usage quota
  exhaustion, `402 Payment Required` for missing/canceled subscriptions.
- **AI token cost calculation** using integer micro-dollar units (no floating
  point money). Supports input, cached input, output and reasoning tokens.
- **Stripe test-mode Checkout + webhooks** with real signature verification and
  webhook idempotency (a delivered Stripe event is applied at most once).
- **Tenant plan synchronization** — the local subscription mirrors verified
  Stripe events.
- **Background job** — periodic usage rollup/aggregation, retry-safe.
- **Automated tests** covering metering, quotas, costs, Stripe webhooks,
  tenant isolation and the background job.

---

## Architecture

```
                          ┌─────────────────┐
                          │     Client      │
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │   HTTP / API    │
                          │     Layer       │
                          │  (FastAPI)      │
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │ Service Layer   │
                          │  Metering       │
                          │  Quota          │
                          │  Cost           │
                          │  Subscription   │
                          └────────┬────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
             ┌──────────┐   ┌──────────┐   ┌──────────┐
             │ Idempotent│  │  Quota   │   │   Cost   │
             │ record    │  │  check   │   │   calc   │
             └──────────┘   └──────────┘   └──────────┘
                    │              │              │
                    └──────────────┼──────────────┘
                                   ▼
                          ┌─────────────────┐
                          │   SQLite (SQLAlchemy)   │
                          │  tenants / plans /      │
                          │  subscriptions /        │
                          │  usage_events /         │
                          │  stripe_webhook_events /│
                          │  usage_snapshots        │
                          └─────────────────┘

        ┌──────────────────────┐
        │       Stripe         │
        │     TEST MODE        │
        └─────────┬────────────┘
                  │ signed webhook + Checkout
                  ▼
        ┌──────────────────────┐
        │ Webhook Handler       │
        │  1. verify signature  │
        │  2. deduplicate event │
        │  3. sync subscription │
        └──────────────────────┘
```

Key layering rule: the **HTTP layer** validates input and translates business
errors into status codes; the **service layer** owns business rules; the
**data layer** owns persistence; **Stripe is isolated** in
`app/services/stripe_service.py` and `app/services/webhook_sync.py`.

---

## Tech Stack

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x
- SQLite (local development)
- pydantic-settings
- Stripe Python SDK (test mode only)
- pytest + httpx (TestClient)

---

## Setup

```bash
# 1. Create a virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# ... fill in Stripe test-mode values (see below) ...

# 4. Create the database and seed demo data
python -m app.seed

# 5. Run the service
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | no | SQLAlchemy URL (default `sqlite:///./metering.db`) |
| `STRIPE_SECRET_KEY` | for Checkout | Stripe **test** secret key (`sk_test_...`) |
| `STRIPE_WEBHOOK_SECRET` | for webhooks | `whsec_...` from `stripe listen` |
| `STRIPE_PRO_PRICE_ID` | for Checkout | Price id of the Pro plan (starts with `price_`) |
| `STRIPE_SUCCESS_URL` | no | Redirect URL after successful checkout |
| `STRIPE_CANCEL_URL` | no | Redirect URL after canceled checkout |
| `ROLLUP_INTERVAL_SECONDS` | no | Background rollup interval (default `60`) |

Secrets are never hardcoded and never logged. `.env` is git-ignored; only
`.env.example` (with placeholders) is committed.

---

## Database

The service uses a single SQLite file (`metering.db`) for local development.

Tables:

| Table | Purpose |
|---|---|
| `tenants` | Customers |
| `plans` | Free / Pro with `api_call_limit` and `ai_token_limit` |
| `subscriptions` | Tenant's current plan + Stripe ids + status |
| `usage_events` | One row per billable request; `UNIQUE(tenant_id, idempotency_key)` |
| `stripe_webhook_events` | Already-processed Stripe event ids (dedup) |
| `usage_snapshots` | Monthly aggregation output of the background job |

> Migration note: the schema is created with `Base.metadata.create_all()`.
> `metering.db` is a disposable development artifact; delete it and re-run
> `python -m app.seed` to rebuild. It is git-ignored and never committed.

---

## Seed

```bash
python -m app.seed
```

Creates:

- Plans: `Free` (1000 API calls / 100,000 AI tokens per month) and `Pro`
  (10,000 API calls / 1,000,000 AI tokens per month).
- A `Demo Tenant` (id `1`) with an active Free subscription.

Output:

```
Seed completed successfully.
Tenant ID: 1
Plan: Free
API call limit: 1000
AI token limit: 100000
```

---

## Run

```bash
uvicorn app.main:app --reload
# or, as declared in capstone.yaml
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API docs: `http://localhost:8000/docs`

---

## Tests

```bash
pytest -q
```

61 tests covering: idempotency (including a real multi-thread race), quota
boundaries, tenant isolation, input validation, 429/402 behavior, pinned
pricing, Stripe signature verification, webhook dedup, subscription sync and
the background job.

---

## API

All billable/usage endpoints select a tenant via the `X-Tenant-ID` header
(defaults to `1`). This is a capstone stand-in for real authentication.

### Health

```http
GET /
```

### Billable endpoint — `POST /generate`

Simulates a billable AI generation request. Records usage idempotently and
returns the resulting cost.

Two usage modes:

**API calls** (`api_calls`) — requires `quantity`:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-1" \
  -H "X-Tenant-ID: 1" \
  -d '{"usage_type":"api_calls","quantity":5}'
```

**AI tokens** (`ai_tokens`) — requires at least one token category > 0:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-2" \
  -H "X-Tenant-ID: 1" \
  -d '{"usage_type":"ai_tokens","input_tokens":1000,"cached_input_tokens":200,"output_tokens":500,"reasoning_tokens":100}'
```

Response:

```json
{
  "message": "Generation request accepted",
  "tenant_id": 1,
  "usage_type": "ai_tokens",
  "quantity": 1800,
  "usage_event_id": 1,
  "cost_micros": 12200,
  "cost_cents": 1,
  "idempotent_replay": false
}
```

The `quantity` is the total token count; `cost_micros` is the exact cost in
integer micro-dollars (1e-6 USD).

### Usage rollup — `GET /usage`

```bash
curl http://localhost:8000/usage -H "X-Tenant-ID: 1"
```

```json
{
  "tenant_id": 1,
  "plan": "Free",
  "subscription_status": "active",
  "api_calls_used": 6,
  "api_calls_limit": 1000,
  "api_calls_remaining": 994,
  "ai_tokens_used": 1800,
  "ai_tokens_limit": 100000,
  "ai_tokens_remaining": 98200,
  "cost_micros": 12200,
  "cost_cents": 1
}
```

### Stripe Checkout — `POST /billing/checkout`

```bash
curl -X POST http://localhost:8000/billing/checkout \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 1" \
  -d '{"plan":"Pro"}'
```

Returns `{"checkout_url": ..., "session_id": ...}` for a Stripe test-mode
subscription Checkout session.

### Stripe Webhook — `POST /webhooks/stripe`

Receives verified Stripe events (`checkout.session.completed`,
`customer.subscription.updated`, `customer.subscription.deleted`). See
[Stripe Integration](#stripe-integration).

---

## Idempotency

Every billable request must include an `Idempotency-Key` header.

- Sending the **same key** twice for the same tenant records **exactly one**
  usage event. The second response is an idempotent replay that returns the
  original result — nothing is double-counted.
- **Different keys** produce different usage events.
- The **same key on a different tenant** is allowed (keys are scoped per
  tenant).

This is not implemented with a fragile `SELECT`-then-`INSERT`. The database
enforces a `UNIQUE(tenant_id, idempotency_key)` constraint, and
`MeteringService.record_usage` performs the `INSERT` first. If two concurrent
requests race, one commit wins and the loser catches the resulting
`IntegrityError`, rolls back, and returns the winner's event. Duplicate usage
is therefore impossible at the database level, not merely at the application
level. The same design is used for Stripe webhook deduplication.

---

## Quota Behavior

The rule is: `current_usage + requested_quantity <= limit` is allowed,
anything above is rejected.

| Situation | Result |
|---|---|
| Just below the limit | `200` — request allowed |
| Exactly at the limit | `200` — request allowed (boundary is inclusive) |
| Just above the limit | `429 Too Many Requests` with a clear `detail` |

Quota is checked **before** recording usage, so an over-quota request creates
no usage event.

`429` is used for **usage quota exhaustion**; `402 Payment Required` is used
when the tenant has **no active subscription** (or it is canceled/past-due).

---

## Pricing & Cost Calculation

Money is always an integer number of **micro-dollars** (1 micro-dollar =
1e-6 USD). Floating point is never used for money.

Prices (micro-dollars per token, equivalent to USD per 1M tokens):

| Token category | µ$/token | USD / 1M tokens | Notes |
|---|---|---|---|
| `input_tokens` | 3 | $3.00 | normal input |
| `cached_input_tokens` | 1 | $1.00 | cheaper than normal input |
| `output_tokens` | 15 | $15.00 | generated output |
| `reasoning_tokens` | 15 | $15.00 | billed at the output rate |

Rules:

- Cached input tokens are cheaper than normal input tokens.
- Reasoning tokens count as output tokens.
- Categories are summed once each — never double-counted (input and cached
  input are separate).
- Constants are centralized in `app/services/cost.py` and pinned by tests.

Example: `input=1000, cached=200, output=500, reasoning=100` →
`1000·3 + 200·1 + 500·15 + 100·15 = 12,200` micro-dollars = $0.0122 = 1 cent.

The total token quantity charged against the AI token quota is the plain sum
of all four categories.

---

## Stripe Integration

Test mode only. Stripe is the source of truth for payment state; the local
database mirrors Stripe only through **verified** webhook events.

### Checkout flow

1. `POST /billing/checkout` creates a Stripe Checkout subscription session.
2. The customer completes it in Stripe's test-mode hosted page.
3. Stripe sends `checkout.session.completed` to `/webhooks/stripe`.
4. The webhook handler verifies the signature, deduplicates the event, and
   upgrades the tenant to the Pro plan.

### Signature verification

Every webhook request must carry a valid `Stripe-Signature` header computed
with `STRIPE_WEBHOOK_SECRET`. Invalid or missing signatures are rejected with
`HTTP 400` and the database is left untouched.

### Webhook deduplication

Processed Stripe event ids are stored in `stripe_webhook_events` (unique
`event_id`). A delivery that was already processed is ignored and reported as
`{"status": "ignored"}` — never applied twice. Dedup is enforced by the
unique constraint, so concurrent duplicate deliveries are safe too.

### Local setup with Stripe CLI

```bash
# 1. Forward Stripe webhooks to the local server
stripe listen --forward-to localhost:8000/webhooks/stripe

# 2. Note the whsec_... secret it prints and put it in .env
#    STRIPE_WEBHOOK_SECRET=whsec_...

# 3. Trigger a real test-mode checkout
stripe checkout sessions create --success-url http://localhost:8000/billing/success \
  --cancel-url http://localhost:8000/billing/cancel \
  --line-items price=price_XXX:1 \
  --subscription-data-metadata tenant_id=1,plan=Pro
```

Manually trigger a webhook event to watch it flow through:

```bash
stripe trigger checkout.session.completed
stripe trigger customer.subscription.deleted
```

> If Stripe CLI / real credentials are not available in the environment, the
> signed-webhook path is fully exercised by the automated test suite, which
> constructs real signed payloads and verifies them with the real Stripe
> signature-verification code.

---

## Background Job

`app/jobs/rollup.py` aggregates each tenant's usage into per-(tenant,
usage_type, month) `usage_snapshots`.

It is:

- **Retry-safe / idempotent** — it recomputes and overwrites the same snapshot
  values (upsert), never appends;
- **Duplicate-safe** — the `UNIQUE(tenant_id, usage_type, period)` constraint
  makes duplicate snapshot rows impossible even if two runs overlap;
- **Non-corrupting** — a failed run leaves the previous snapshot intact.

Run it once from the CLI:

```bash
python -m app.jobs.rollup
```

The FastAPI app also starts a lightweight daemon thread that runs it every
`ROLLUP_INTERVAL_SECONDS` (default 60 s).

---

## Limitations

- Local development uses SQLite; production would use PostgreSQL.
- Tenant selection is via the `X-Tenant-ID` header (no real authentication).
- AI usage is simulated from request fields — no real LLM is called.
- No real payments, production invoicing, proration, or overage billing.
- Checkout in this environment requires real Stripe test credentials; without
  them `POST /billing/checkout` returns `503`.

---

## Security Notes

- Stripe credentials come **only** from environment variables. They are never
  hardcoded and never logged.
- `.env` is git-ignored; `.env.example` contains placeholders only.
- Webhooks are signature-verified before any state change; forged events are
  rejected with `400` and change nothing.
- Errors never leak secret material or internal details.
- Tenant isolation is enforced at every query: a tenant can only ever see or
  modify its own usage and subscription.
