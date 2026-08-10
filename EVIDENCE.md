# EVIDENCE.md

Proof for every Definition-of-Done requirement. Every item below was executed
in this repository and the actual output is reproduced.

Environment: Linux, Python 3.14.6, SQLite. Stripe SDK 15.4.0 (test mode).

---

## 1. Test suite runs

Command:

```
python -m pytest -v
```

Result:

```
============================== 61 passed in 1.04s ==============================
```

Test inventory (all PASSED):

- `test_api.py` — health, successful billable request, duplicate idempotency
  key, different keys, same key on different tenants, invalid quantity (0, -1),
  non-integer quantity, invalid usage type, missing idempotency key, zero
  tokens, quota just below / exactly at / above limit, 429 responses, AI token
  quota, tenant isolation, 404 unknown tenant, 422 invalid tenant header,
  usage rollup shape, exact cost in generate response, 402 no subscription.
- `test_billing.py` — Checkout session creation (mocked), invalid plan 422,
  missing key 503, Stripe API error -> 503 (no secret leaked), 404 tenant.
- `test_cost.py` — pinned pricing constants, cached-input cheaper, reasoning =
  output, no double counting, exact integer math, zero tokens, totals,
  micro->cent conversion, metadata cost, single-token param cases.
- `test_jobs.py` — rollup aggregation per period, rollup idempotent when run
  twice.
- `test_metering.py` — record usage, duplicate key, **multi-thread race
  produces exactly one event**, same key across tenants, isolation, quota
  boundary unit tests.
- `test_webhook.py` — missing signature 400, forged signature 400 + state
  unchanged, invalid payload 400, checkout completed upgrades to Pro, duplicate
  event ignored, subscription updated syncs status, subscription deleted
  cancels tenant, plan downgrade, unhandled event type recorded.

---

## 2. Seed works

Command:

```
python -m app.seed
```

Output:

```
Seed completed successfully.
Tenant ID: 1
Plan: Free
API call limit: 1000
AI token limit: 100000
```

---

## 3. Application startup works

Command:

```
uvicorn app.main:app --port 8000
```

Output (log excerpt):

```
INFO:     Started server process
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     127.0.0.1:xxxxx - "GET / HTTP/1.1" 200 OK
```

`GET /` returns:

```json
{"service":"Usage Metering & Billing Engine","status":"ok"}
```

Registered routes (from OpenAPI):

```
['/', '/billing/checkout', '/generate', '/usage', '/webhooks/stripe']
```

---

## 4. Acceptance PROBE 1 — idempotent duplicate request

Send the same billable request twice with the same idempotency key.

Request (twice):

```bash
curl -X POST http://localhost:8000/generate \
  -H "Idempotency-Key: probe-1-key" -H "Content-Type: application/json" -H "X-Tenant-ID: 1" \
  -d '{"usage_type":"api_calls","quantity":3}'
```

First response:

```json
{"message":"Generation request accepted","tenant_id":1,"usage_type":"api_calls",
 "quantity":3,"usage_event_id":1,"cost_micros":0,"cost_cents":0,"idempotent_replay":false}
```

Second response:

```json
{"message":"Generation request accepted","tenant_id":1,"usage_type":"api_calls",
 "quantity":3,"usage_event_id":1,"cost_micros":0,"cost_cents":0,"idempotent_replay":true}
```

`GET /usage`:

```json
{"tenant_id":1,"plan":"Free","subscription_status":"active","api_calls_used":3,
 "api_calls_limit":1000,"api_calls_remaining":997,"ai_tokens_used":0,
 "ai_tokens_limit":100000,"ai_tokens_remaining":100000,"cost_micros":0,"cost_cents":0}
```

**Result:** exactly one usage event (`usage_event_id: 1` on both), usage
counted once (`api_calls_used: 3`), second request is an idempotent replay.

Automated equivalents:

```
tests/test_api.py::test_duplicate_idempotency_key_counts_once PASSED
tests/test_metering.py::test_concurrent_same_key_creates_exactly_one_event PASSED
```

---

## 5. Acceptance PROBE 2 — drive a tenant to its exact quota

Free plan limit = 1000 API calls. Tenant already used 3; fill 997.

```
curl ... -d '{"usage_type":"api_calls","quantity":997}'        -> 200
```

`GET /usage` at the boundary:

```json
{"api_calls_used":1000,"api_calls_limit":1000,"api_calls_remaining":0,...}
```

Next request (would make 1001):

```
curl ... -d '{"usage_type":"api_calls","quantity":1}'
```

Response (HTTP 429):

```json
{"detail":{"message":"api_calls quota exceeded","usage_type":"api_calls",
 "used":1000,"requested":1,"limit":1000}}
```

Automated equivalents:

```
tests/test_api.py::test_quota_just_below_limit        PASSED
tests/test_api.py::test_quota_exactly_at_limit        PASSED
tests/test_api.py::test_quota_above_limit_returns_429 PASSED
tests/test_metering.py::test_quota_allows_request_at_exact_limit        PASSED
tests/test_metering.py::test_quota_rejects_request_over_limit           PASSED
tests/test_metering.py::test_quota_rejects_request_that_crosses_limit   PASSED
```

---

## 6. Acceptance PROBE 3 — Stripe Checkout: Free -> Pro via verified webhook

No live Stripe credentials are available in this environment, so the full
Checkout page is externally verifiable. Locally we exercise the exact
production code path: a **real** HMAC-signed webhook payload is delivered to
`/webhooks/stripe` and verified by `stripe.Webhook.construct_event`.

Signed `checkout.session.completed` for tenant 1, plan Pro:

```
POST /webhooks/stripe
Stripe-Signature: t=<ts>,v1=<hmac-sha256 over (ts + "." + payload) with whsec_probe_test>
```

Webhook response:

```json
{"status":"processed","event_id":"evt_probe3_checkout","event_type":"checkout.session.completed"}
```

`GET /usage` after:

```json
{"tenant_id":1,"plan":"Pro","subscription_status":"active","api_calls_used":0,
 "api_calls_limit":10000,"api_calls_remaining":10000,"ai_tokens_used":0,
 "ai_tokens_limit":1000000,"ai_tokens_remaining":1000000,"cost_micros":0,"cost_cents":0}
```

**Result:** tenant changed Free -> Pro; `/usage` shows the new limits
(10,000 API calls, 1,000,000 AI tokens).

Automated equivalent:

```
tests/test_webhook.py::test_checkout_completed_upgrades_tenant_to_pro PASSED
```

---

## 7. Acceptance PROBE 4 — forged webhook + replay

Forged webhook (bad signature, attempts `customer.subscription.deleted`):

```
POST /webhooks/stripe
Stripe-Signature: t=9999999999,v1=deadbeef
```

Response:

```json
{"detail":"Invalid Stripe signature"}
```

HTTP **400**. `GET /usage` immediately after still shows the tenant active on
Pro — **database state unchanged**.

Then replay a valid signed `customer.subscription.deleted` event **twice**:

First delivery:

```json
{"status":"processed","event_id":"evt_probe4_delete","event_type":"customer.subscription.deleted"}
```

Second delivery (same event id):

```json
{"status":"ignored","reason":"duplicate event","event_id":"evt_probe4_delete"}
```

**Result:** forged event rejected with 400 and no state change; valid event
processed once, replay ignored.

Automated equivalents:

```
tests/test_webhook.py::test_forged_webhook_rejected_and_state_unchanged PASSED
tests/test_webhook.py::test_duplicate_webhook_event_ignored            PASSED
tests/test_webhook.py::test_webhook_missing_signature_rejected         PASSED
```

---

## 8. Acceptance PROBE 5 — pricing tests and rollup consistency

Pinned pricing test output:

```
tests/test_cost.py::test_pricing_constants_are_pinned PASSED
tests/test_cost.py::test_cached_input_is_cheaper_than_input PASSED
tests/test_cost.py::test_million_tokens_are_priced_per_documented_rate PASSED
tests/test_cost.py::test_reasoning_tokens_billed_as_output PASSED
tests/test_cost.py::test_exact_integer_math PASSED
```

Live request (`input=1000, cached=200, output=500, reasoning=100`):

```
POST /generate {"usage_type":"ai_tokens", ...}
```

Response:

```json
{"message":"Generation request accepted","tenant_id":1,"usage_type":"ai_tokens",
 "quantity":1800,"usage_event_id":1,"cost_micros":12200,"cost_cents":1,
 "idempotent_replay":false}
```

`GET /usage`:

```json
{"plan":"Pro","ai_tokens_used":1800,"ai_tokens_limit":1000000,
 "ai_tokens_remaining":998200,"cost_micros":12200,"cost_cents":1}
```

Hand calculation: `1000*3 + 200*1 + 500*15 + 100*15 = 12200` micro-dollars
($0.0122). Matches both the generate response and the usage rollup.

---

## 9. Concurrency proof (idempotency under real threads)

`tests/test_metering.py::test_concurrent_same_key_creates_exactly_one_event`

Two threads race `record_usage` with the same key against a real SQLite file.
Assertions:

- exactly one `usage_events` row for the key,
- summed quantity == 1,
- both callers returned the same event id.

Result: PASSED. The guarantee comes from the DB unique constraint
`UNIQUE(tenant_id, idempotency_key)`; the loser of the race hits
`IntegrityError`, rolls back, and returns the winner's event.

---

## 10. Background job (rollup) evidence

CLI run on a DB containing `api_calls=11` and `ai_tokens=800` for tenant 1:

```
$ python -m app.jobs.rollup
Rollup completed. 2 snapshot rows written.
```

Snapshot rows:

```
(1, 'api_calls', '2026-08', 11)
(1, 'ai_tokens', '2026-08', 800)
```

Re-run is idempotent (no duplicate rows):

```
$ python -m app.jobs.rollup
Rollup completed. 2 snapshot rows written.
```

The in-process scheduler also runs it (server log):

```
INFO:     Usage rollup job completed: 1 snapshot rows
```

Automated equivalent:

```
tests/test_jobs.py::test_rollup_aggregates_usage PASSED
tests/test_jobs.py::test_rollup_is_idempotent_when_run_twice PASSED
```

---

## 11. Stripe verification status

| Item | Local status | Live status |
|---|---|---|
| Signature verification (real HMAC) | Verified via tests + probes | Same code path as live |
| Webhook dedup | Verified via tests + probes | Same code path as live |
| Checkout session creation | Code implemented; mocked in tests | Requires real test key; **not exercised live** here |
| Full Stripe Checkout page flow | — | Requires Stripe CLI + test key; externally verifiable |

To verify the live flow: set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`STRIPE_PRO_PRICE_ID` in `.env`, run `stripe listen --forward-to localhost:8000/webhooks/stripe`,
then complete a test Checkout and confirm `GET /usage` shows the Pro limits.

---

## 12. Money representation

- All costs are stored/computed as integer **micro-dollars** (1e-6 USD).
- No floating point is used for money anywhere.
- Pinned tests: `test_exact_integer_math`, `test_micros_to_cents_conversion`,
  `test_cost_from_event_metadata` — all PASSED.

---

## 13. Validation & error handling evidence

| Input | Response | Test |
|---|---|---|
| quantity = 0 / -1 | 422 | `test_invalid_quantity_rejected` |
| quantity = "three" | 422 | `test_non_integer_quantity_rejected` |
| usage_type = "galaxies" | 422 | `test_invalid_usage_type_rejected` |
| missing Idempotency-Key | 422 | `test_missing_idempotency_key_rejected` |
| ai_tokens with all-zero tokens | 422 | `test_ai_tokens_requires_positive_tokens` |
| X-Tenant-ID = "abc" | 422 | `test_invalid_tenant_header_returns_422` |
| unknown tenant | 404 | `test_unknown_tenant_returns_404` |
| quota exceeded | 429 | `test_quota_above_limit_returns_429` |
| no active subscription | 402 | `test_no_active_subscription_returns_402` |
| forged/missing webhook signature | 400 | `test_forged_webhook_rejected_and_state_unchanged` |
| Stripe API error on checkout | 503 | `test_checkout_handles_stripe_api_error` |

All PASSED.

---

## 14. Repository hygiene

- `.env` present locally but empty; covered by `.gitignore`.
- `.gitignore` excludes `.env`, `*.db`, `__pycache__`, `.pytest_cache`, venvs.
- No real Stripe credentials appear anywhere in the repository.
- `capstone.yaml`, `README.md`, `design.md`, `BUILDLOG.md`, `.env.example`
  all present.
