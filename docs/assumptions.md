# Assumptions, strategies and MVP limits

This MVP deliberately trades production hardening for a small, fully working end-to-end slice. This document records
the choices made so reviewers can see what is intentional.

## Intentional MVP limitations
- **Single process, modular monolith.** Orders, rates, shipments, tracking and NDR are modules in one FastAPI app; no queues or microservices.
- **No authentication / authorisation / RBAC / multi-tenant isolation.** `merchantId` is a plain request field used for idempotency and cache scoping, not a security boundary.
- **No webhook authentication** (no HMAC/IP allow-list). Anyone who can reach `/api/webhooks/*` can post events.
- **Mock AI.** `MockIntentExtractor` is keyword based and English only; the `IntentExtractor` interface is the seam for a real LLM. Rules (not the AI) decide what may happen.
- **No seller approval workflow.** `REQUIRES_APPROVAL` decisions simply block the automatic action.
- **Money is `NUMERIC(10,2)` in Postgres but `float` in Python** (fine for display and equality on 2 dp; use `Decimal`/integer paise in production).
- **Synthetic pricing/ETAs.** Prices are derived from chargeable weight (greater of actual and volumetric, each carrier with its own divisor) and a zone factor from pincodes.
- **Migrations** are plain ordered `.sql` files applied at startup under an advisory lock (no Alembic).
- **No pagination** on list endpoints (capped at 100 rows).
- **Unknown NDR reasons** from a carrier are mapped to `CUSTOMER_UNAVAILABLE`.

## Cache strategy
- **Key:** `zippy:rates:{merchantId}:{pickupPincode}:{deliveryPincode}:{weightGrams}:{lengthCm}:{widthCm}:{heightCm}:{paymentType}:{codAmount}`
  e.g. `zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500`. Every pricing input is in the key, so changing any one yields a new key (unit-tested per field). `codAmount` is rendered as an integer when whole (`2500`) else 2 dp (`99.50`).
- The key deliberately does **not** contain the order id: two orders with identical pricing inputs share one quote lookup. Each order still gets its own `shipping_quotes` rows copied from the cached result, so selection is always validated against that order's own stored quote.
- **Complete result** (every carrier answered): TTL `RATE_CACHE_TTL` = 300 s.
- **Partial result** (>= 1 carrier failed): **cached, with a shorter TTL** `PARTIAL_RATE_CACHE_TTL` = 60 s, together with the failure details. Rationale: a degraded carrier should not be hammered by every page refresh (and user clicks stay fast), but a recovered carrier should reappear within a minute. A cache hit on a partial result is still reported as `partial: true` with the original failures. `refresh=true` bypasses the cache and replaces the entry (upgrading the TTL if everything now succeeds).
- **All carriers failed:** nothing is cached; the API returns 502 with per-carrier failure details.
- **Expiry** is Redis TTL (`SET ... EX`). `refresh=true` (GET or POST) ignores the cache and overwrites it.

## Timeout strategy
- Every carrier HTTP request (rates, create shipment, reattempt) uses `CARRIER_TIMEOUT_MS` (default 3000), read at call time.
- Rate calls run concurrently in a thread pool with an additional hard deadline (`timeout + 1 s`) so a carrier that trickles bytes still cannot hold the request; the pool is shut down without waiting.
- A timed-out/erroring carrier is reported in `errors[]` as `{carrier, code, message, durationMs}` with `code` in `TIMEOUT | HTTP_ERROR | UNREACHABLE | BAD_RESPONSE`; the other carriers' quotes are returned (`partial: true`).
- A timeout during shipment creation returns 502 and creates nothing; a timeout during an NDR reattempt marks the action failed and the buyer is **never** told the carrier accepted.
- No automatic retries in the MVP (a retry would double the worst-case latency of a user-facing call).

## Redis fallback strategy
- Redis is a pure accelerator. Any `RedisError` (down, timeout, connection refused) on GET or SET is caught and logged (`CACHE_UNAVAILABLE`, warning); the request proceeds to direct carrier calls and returns normally with `cacheStatus: "UNAVAILABLE"`.
- Redis sockets use 1 s connect/read timeouts so an outage adds at most ~1 s per request rather than hanging.
- Because quotes are persisted in Postgres, carrier selection and shipment creation do not depend on Redis at all.

## Webhook strategy
- One endpoint per carrier (`/api/webhooks/{fastship|quickexpress|reliable}`); each carrier's adapter parses its own payload into a normalised event `{carrier, trackingNumber, status, eventId, reason}`.
- **Raw + normalised are both stored** in `shipment_events` (`raw`, `normalized` JSONB) for every accepted event; quarantined events store both too in `webhook_quarantine`.
- **Unknown tracking number:** no shipment is created; the event goes to `webhook_quarantine` (`UNKNOWN_TRACKING_NUMBER`) and the response is HTTP 202 `{"status":"quarantined", ...}` (2xx so the carrier stops retrying; the quarantine log, `GET /api/webhook-quarantine`, is the investigation queue).
- **Unparseable payload:** stored in quarantine (`UNPARSEABLE_PAYLOAD`), HTTP 400.
- **Invalid transition:** stored in quarantine (`INVALID_TRANSITION`) with `from/to/allowed`, shipment untouched, HTTP 202.

## Idempotency strategy
- **Orders:** unique index on `(merchant_id, merchant_order_id)` (where the latter is not null). A repeat request returns the existing order with HTTP 200 and `duplicate: true`; the same key with *different* details returns 409 listing the differing fields. Concurrent identical requests are safe (the unique index decides; the loser re-reads the winner).
- **Webhooks:** unique constraint on `shipment_events(carrier, tracking_number, status, event_id)`. A replay returns HTTP 200 `{"status":"duplicate"}` and creates nothing (checked first for clarity and again via `ON CONFLICT DO NOTHING` for races).
- **Shipments:** one per order (`UNIQUE(order_id)` plus a row lock held while the carrier is called).
- **Quoted price:** always read from the server-side `shipping_quotes`; a client-supplied price that differs is rejected (409), unknown price-like fields are ignored, and quotes are frozen once a shipment exists.

## Status transition strategy
Allowed transitions (anything else is quarantined, never applied):

| From | To |
|---|---|
| SHIPMENT_CREATED | PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY |
| PICKED_UP | IN_TRANSIT, OUT_FOR_DELIVERY |
| IN_TRANSIT | OUT_FOR_DELIVERY, NDR |
| OUT_FOR_DELIVERY | DELIVERED, NDR |
| NDR | OUT_FOR_DELIVERY (reattempt), DELIVERED |
| DELIVERED | — (terminal) |

Forward skips are tolerated (carriers drop events); regressions (`DELIVERED -> IN_TRANSIT`), repeats under a new event id, and a second NDR without an intervening out-for-delivery are rejected. Late events that arrive after a later status therefore get quarantined rather than rewriting history. (RTO/cancelled/lost states are out of scope.)

## Why mock carriers are implemented locally
The assignment tests carrier integration and normalisation, not access to real accounts. Local mocks give deterministic prices, fault injection (`POST /mock/_control/failures` with `fail` / `delayMs`), controllable webhooks (Mock Carrier Control page) and a fully offline, reproducible demo and test suite. They run inside the API process for simplicity but are only reachable over HTTP at configurable URLs (`FASTSHIP_BASE_URL`, ...) and each has a deliberately different contract (JSON camelCase POST / snake_case nested POST / GET with query params and a list response; different webhook vocabularies), so adapters do real translation work. Pointing the URLs at real carriers would require only new adapter field mappings and auth.

## Structured logging
JSON lines on stdout. Every line has `ts`, `level`, `requestId` (from `X-Request-ID` or generated; echoed in the response and forwarded to carrier calls), `event` and, where known, `orderId`, `shipmentId`, `carrier`. Examples: `RATE_REQUEST`, `CACHE_HIT|CACHE_MISS|CACHE_UNAVAILABLE`, `CARRIER_CALL`, `CARRIER_CALL_FAILED`, `ORDER_CREATED`, `ORDER_DUPLICATE`, `SHIPMENT_CREATED`, `WEBHOOK_RECEIVED`, `WEBHOOK_DUPLICATE`, `WEBHOOK_QUARANTINED`, `SHIPMENT_STATUS_UPDATED`, `NDR_CREATED`, `CARRIER_ACTION_*`.

## What would change in production
- AuthN/Z, tenant isolation, per-merchant carrier credentials; HMAC-signed webhooks with replay windows.
- Real carrier adapters with retries/backoff + circuit breakers, async job queue for booking and NDR actions, outbox for reliable side effects.
- Redis single-flight / request coalescing on cache misses (avoid stampedes), cache invalidation on carrier-rate-card changes, Redis HA.
- Decimal/paise money handling, quote expiry/versioning, idempotency keys on every mutating endpoint.
- Alembic migrations, pagination, metrics/tracing (OpenTelemetry), log shipping, alerting on the quarantine queue.
- Webhook ordering via carrier event timestamps/sequence numbers; reconciliation polling for missed events; RTO/lost/cancelled states.
- A real LLM `IntentExtractor` with schema-validated output, a seller approval queue, and a real WhatsApp provider.
