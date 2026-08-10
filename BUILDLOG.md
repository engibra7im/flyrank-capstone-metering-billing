# BUILDLOG.md

An honest record of how this capstone was built, where AI assisted, and what
was corrected along the way.

This project was implemented by an AI coding agent (opencode) continuing from
a partially implemented repository. This log documents AI involvement
honestly: what AI suggested, where suggestions were wrong, and what was
changed and why.

---

## Phase 2 — core metering & billing logic

### What already existed (from the human developer)

- Phase 1 design document (`design.md`).
- Database models: `Tenant`, `Plan`, `Subscription`, `UsageEvent` with
  `UNIQUE(tenant_id, idempotency_key)`.
- Seed script, initial `MeteringService` (`get_usage`, `record_usage`),
  `check_quota`, and a `/generate` + `/generate/usage` route hardcoding
  tenant id 1.
- A small test file that passed, but the repo had at one point reported
  `collected 0 items`.

### AI contributions

- Wrote `app/config.py` (pydantic-settings) to centralize env-driven config
  (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, database URL, rollup
  interval).
- Replaced the fragile `SELECT -> INSERT` in `record_usage` with an
  INSERT-first pattern that catches `IntegrityError` and returns the winner's
  row. The database unique constraint is the real guarantee, not the app check.
- Added `app/constants.py` to stop scattering magic strings.
- Added `X-Tenant-ID` selection (capstone stand-in for auth) via a FastAPI
  dependency.
- Implemented validation in `app/schemas.py` with pydantic field/model
  validators (usage type, quantity, token categories).
- Implemented `GET /usage` rollup and a `POST /generate` that supports both
  `api_calls` (quantity) and `ai_tokens` (token breakdown) modes.

### Mistakes AI made and corrections

1. **Reserved column name `metadata`.** AI named a JSON column `metadata`,
   which is a reserved attribute name in SQLAlchemy's Declarative API. The app
   failed to import with `InvalidRequestError`. Renamed the column to
   `payload` and updated all references.
2. **Redundant second unique constraint.** AI initially added
   `UNIQUE(tenant_id, usage_type, idempotency_key)` in addition to
   `UNIQUE(tenant_id, idempotency_key)`. The second constraint conflicted
   with the design (a key must uniquely identify a billable request per
   tenant). Removed it, keeping only the documented constraint.

---

## Phase 3 — Stripe integration

### AI contributions

- Added the `stripe` package (SDK 15.4.0).
- Isolated Stripe in `app/services/stripe_service.py` (Checkout session
  creation, `construct_event` signature verification) and
  `app/services/webhook_sync.py` (dedup + applying events), keeping core
  business logic Stripe-free.
- Added `stripe_webhook_events` table with a unique `event_id` for webhook
  dedup. Dedup uses the same insert-first/IntegrityError pattern as usage
  metering.
- Implemented `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted` handling in `app/services/subscription.py`.
- Added `stripe_customer_id`, `stripe_subscription_id`, `updated_at` to
  `Subscription`.

### Mistakes AI made and corrections

1. **Stripe SDK v15 object model.** AI initially wrote event handling with
   dict methods like `event.get("data")`. Stripe v15 objects do **not** subclass
   `dict`; they expose fields via `obj["field"]` / attribute access and raise
   `AttributeError` for `.get`. Rewrote webhook access through a `_get`
   helper and `_as_dict` conversion.
2. **Fake test events missing the top-level `object` field.** The first
   webhook tests failed because `stripe.Webhook.construct_event` reads
   `event.object` to detect v2 events. Added `"object": "event"` to the test
   helper's generated payloads.
3. **Pro price id not propagated.** The plan-downgrade/update tests expected
   the Pro price id to map a subscription to Pro, but the webhook route never
   passed `settings.stripe_pro_price_id` into the sync service, so every
   subscription mapped to Free. Fixed the wiring and pinned the price id in
   the test fixtures.
4. **Unhandled Stripe API errors.** A live call with an invalid test key
   produced an HTTP 500. Added `stripe.error.StripeError` handling in the
   checkout route so misconfiguration returns a clean `503` without leaking
   details.

---

## Phase 4 — cost calculation

### AI contributions

- Implemented `app/services/cost.py` with integer **micro-dollar** units
  (1e-6 USD). Prices are integers per token: input 3, cached input 1, output
  15, reasoning 15 (reasoning billed as output).
- Centralized pricing constants with pinned tests.
- Added `micros_to_cents` display helper.
- Wired cost into the generate response and the `/usage` rollup; costs are
  recomputed exactly from stored token breakdowns on idempotent replays.

### Note

The initial idea of storing money only in cents conflicted with per-token AI
pricing (single tokens cost fractions of a cent). The design allows "integer
cents or another exact integer micro-unit", so micro-dollars were chosen as
the exact integer unit, with cents exposed only as a display convenience.

---

## Phase 5 — background job, tests, docs

### AI contributions

- `app/jobs/rollup.py`: monthly usage aggregation into `usage_snapshots`,
  idempotent (upsert) and duplicate-safe via a unique constraint. Runs
  in-process via a FastAPI lifespan daemon thread and via `python -m
  app.jobs.rollup`.
- Wrote the full pytest suite (61 tests) including a real multi-thread race
  test for idempotency and signature-verification tests that build genuine
  HMAC-signed webhook payloads.
- Wrote README, design updates, EVIDENCE (from live transcripts), BUILDLOG,
  capstone.yaml, .env.example, architecture diagram, and .gitignore.

### Mistakes AI made and corrections

- The concurrency test originally used an in-memory shared connection, which
  does not actually exercise multi-connection SQLite locking. Rewrote it to
  use a temp-file database with two threads and a barrier, which reproduces
  the real race. (Fixed after reasoning about what the test actually proved.)

---

## Verification honesty

- Full test suite: `61 passed`.
- All five acceptance probes executed live against a running server:
  - PROBE 1 idempotent duplicate (one event),
  - PROBE 2 exact-quota boundary + 429,
  - PROBE 3 Free->Pro via signed webhook + new limits,
  - PROBE 4 forged webhook 400 / replay ignored,
  - PROBE 5 pinned pricing + rollup consistency.
- The live Stripe **Checkout page** was not exercised end-to-end because no
  real test credentials/Stripe CLI are available in this environment; that
  specific step is documented in EVIDENCE.md as externally verifiable.
