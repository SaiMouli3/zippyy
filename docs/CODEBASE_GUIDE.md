# Zippy MVP – Complete Codebase Guide

This document explains **every file, every flow and every piece of logic** in the project, in plain language.
Read it top to bottom once; afterwards use the table of contents as a reference.
For a screen-by-screen view ("I click this button → which file, which API, what appears") see [`UI_FLOW_GUIDE.md`](UI_FLOW_GUIDE.md).

1. [What the system does (the big picture)](#1-what-the-system-does)
2. [Glossary](#2-glossary)
3. [Repository map](#3-repository-map)
4. [The end-to-end flows, step by step](#4-the-end-to-end-flows)
5. [Backend, file by file](#5-backend-file-by-file)
6. [Database, table by table](#6-database)
7. [Frontend, file by file](#7-frontend-file-by-file)
8. [Tests, file by file](#8-tests)
9. [Infrastructure: Docker, nginx, env vars](#9-infrastructure)
10. [Cross-cutting rules (idempotency, locking, timeouts, cache, logging, errors)](#10-cross-cutting-logic)
11. [State machines](#11-state-machines)
12. [Cookbook: how to change things](#12-cookbook)
13. [Honest list of gaps and gotchas](#13-gaps-and-gotchas)

---

## 1. What the system does

Zippy is a small logistics platform with two halves.

**Half A – shipping integration.** A merchant creates an *order*. Zippy asks **three carriers** (FastShip, QuickExpress,
ReliableCourier) what they would charge. Each carrier speaks a **different API language**, so Zippy translates ("normalizes")
every answer into one common shape. The merchant picks a carrier, Zippy books the shipment with that carrier and gets a
*tracking number*. From then on the carrier sends **webhooks** ("your parcel was picked up", "out for delivery", …) and Zippy
updates the shipment and keeps a full history.

**Half B – the NDR agent.** *NDR* = *Non-Delivery Report*: the courier tried to deliver and failed. Zippy opens an **NDR case**,
"messages" the buyer (a simulated WhatsApp chat), **understands** what the buyer wants ("come tomorrow evening"), lets a
**rules engine** decide if that request may be handled automatically, asks the **carrier** to reattempt, and only tells the
buyer "the carrier accepted" **after** the carrier really accepted.

### Architecture

![Zippy end-to-end architecture](architecture.svg)

*(Also available as [`architecture.png`](architecture.png).)*

Text version of the same picture:

```
 Browser
   │  http://localhost:3000
   ▼
 nginx  (serves the built React app; forwards /api, /mock/, /docs, /openapi.json, /static/ to the API)
   │
   ▼
 FastAPI app  (backend/app/main.py)  ──────────────  one process, "modular monolith"
   │
   ├─ routes (main.py)                 thin: validate input → call a service → shape the output
   ├─ services/                        the business logic
   │     orders · rates · shipments (+webhooks, tracking) · ndr · dashboard
   ├─ carriers/                        ADAPTERS: translate between Zippy's shape and each carrier's shape
   ├─ mock_carriers/                   FAKE carriers (3 different APIs) living in the same process,
   │                                   but always called over real HTTP, like real carriers
   ├─ ai/intent.py                     "AI" that extracts intent from buyer text (mock, keyword-based)
   ├─ rules.py                         deterministic policy: decides what is allowed
   ├─ transitions.py                   which shipment status changes are legal
   └─ db.py / logs.py / config.py      plumbing
   │
   ├──► PostgreSQL   the source of truth (orders, quotes, shipments, events, NDR cases, audit, quarantine)
   └──► Redis        only a rate cache; the app works without it
```

### Why the mock carriers are called over HTTP even though they are in the same process
So the adapters behave exactly like they would with real carriers: real network calls, real timeouts, real error codes.
Changing `FASTSHIP_BASE_URL` to a real URL later requires no change in the services.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Order** | What the merchant wants shipped (customer, pincodes, weight, size, COD or prepaid). ID like `ZPY-ORD-10002`. |
| **Pincode** | 6-digit Indian postal code. |
| **COD** | Cash on delivery – the buyer pays the courier when the parcel arrives. |
| **Quote / rate** | A carrier's price + delivery time for an order. |
| **Normalization** | Converting each carrier's own response format to Zippy's one common format. |
| **Adapter** | The class that does that conversion for one carrier. |
| **Tracking number / AWB** | The carrier's ID for a parcel (e.g. `FST123456789`). |
| **Webhook** | The carrier calling *us* to report a status change. |
| **Idempotency** | Doing the same request twice has the same effect as once (no duplicates). |
| **Quarantine** | A holding table for webhook events we refuse to apply (unknown parcel, illegal status change, garbage). |
| **NDR** | Non-delivery report: a failed delivery attempt. |
| **Intent** | What the buyer wants, as a label (`RESCHEDULE_DELIVERY`, `CANCEL_ORDER`, …). |
| **Rules engine** | Plain `if/else` code that decides if an intent may be acted on automatically. The AI never decides this. |
| **Audit log** | An append-only list of important events (`ORDER_CREATED`, `RATES_FETCHED`, …). |
| **Request ID** | A unique ID per HTTP request, written into every log line so one request can be traced. |

---

## 3. Repository map

```
zippyy/
├── docker-compose.yml          starts postgres, redis, api, web
├── .env.example                every environment variable with its default
├── .gitignore
├── README.md                   how to run / API summary / demo
├── docs/
│   ├── CODEBASE_GUIDE.md       this file
│   ├── assumptions.md          decisions, strategies, MVP limits, what changes in production
│   └── acceptance-checklist.md each assignment requirement → the test that proves it
├── backend/
│   ├── Dockerfile · requirements.txt · pytest.ini · .dockerignore
│   ├── app/
│   │   ├── main.py             FastAPI app, all routes, OpenAPI metadata
│   │   ├── config.py           reads environment variables
│   │   ├── db.py               Postgres pool, migrations runner, audit helper
│   │   ├── logs.py             structured JSON logging + request-ID middleware
│   │   ├── util.py             camelCase conversion, ApiError
│   │   ├── schemas.py          request/response models (drive Swagger docs)
│   │   ├── transitions.py      shipment status state machine
│   │   ├── rules.py            NDR rules engine
│   │   ├── seed.py             demo data
│   │   ├── ai/intent.py        IntentExtractor interface + MockIntentExtractor
│   │   ├── carriers/           base.py · registry.py · fastship.py · quickexpress.py · reliable.py
│   │   ├── mock_carriers/router.py   the three fake carriers + webhook sender + fault injection
│   │   ├── services/           orders.py · rates.py · shipments.py · ndr.py · dashboard.py
│   │   ├── migrations/         001_init.sql · 002_assignment_compliance.sql
│   │   └── static/swagger-ui/  vendored Swagger UI files (so /docs works offline)
│   └── tests/                  conftest.py · test_units.py · test_api.py
└── frontend/
    ├── Dockerfile · nginx.conf · vite.config.ts · package.json · tsconfig*.json · index.html
    └── src/  main.tsx · App.tsx · api.ts · ui.tsx · index.css · pages/ (7 pages)
```

---

## 4. The end-to-end flows

Each flow lists **what the user does → which function runs → what is written to the database**.

### Flow A – Create an order (idempotent)

1. UI `CreateOrder.tsx` posts the form to `POST /api/orders` (camelCase JSON).
2. `main.py: create_order` → FastAPI validates the body against `schemas.OrderIn` (10-digit phone, 6-digit pincodes, grams > 0, dimensions > 0, COD/PREPAID…). Bad input → HTTP 422.
3. `services/orders.py: create_order`:
   1. Fill `merchantId` with `DEFAULT_MERCHANT_ID` if missing.
   2. COD must have `codAmount > 0`; PREPAID forces `codAmount = 0`.
   3. Insert the merchant row if it is new (`ON CONFLICT DO NOTHING`).
   4. **If `merchantOrderId` was given and an order with the same `(merchantId, merchantOrderId)` already exists** → `_replay`:
      compare the important fields. Same → return the existing order (`duplicate = true`, HTTP 200). Different → HTTP 409 listing the differing fields.
   5. Otherwise `INSERT` a new row. The ID is built in SQL: `'ZPY-ORD-' || nextval('order_seq')` (sequence starts at 10001).
      The insert has `ON CONFLICT … DO NOTHING`; if it returns nothing, a concurrent identical request won the race, so we re-read and treat ours as the duplicate.
   6. Write an `ORDER_CREATED` audit row and log line.
4. `main.py` returns HTTP **201** for a new order, **200** for a duplicate; the body contains `duplicate: true/false`.
5. UI: new order → go to the rates page; duplicate → show a yellow notice with a link to the existing order.

### Flow B – Get rates (fan-out, normalize, cache)

`POST` (or `GET`) `/api/orders/{id}/rates[?refresh=true]` → `services/rates.py: get_rates(order_id, refresh)`.

```
load order ──► build cache key ──► refresh=false? ──yes──► Redis GET ──hit──► copy cached quotes into this order's
                                                              │                shipping_quotes ──► return (cached:true)
                                                              └─miss / Redis down─┐
                                  refresh=true ───────────────────────────────────┤
                                                                                  ▼
                    call all 3 carriers IN PARALLEL (threads) — each bounded by CARRIER_TIMEOUT_MS
                                                                                  ▼
                    successes → NormalizedRate list;  failures → errors[] {carrier, code, message, durationMs}
                                                                                  ▼
                    no successes at all? → HTTP 502 (with the errors), nothing cached
                                                                                  ▼
                    save quotes to Postgres (shipping_quotes)  +  audit RATES_FETCHED
                                                                                  ▼
                    Redis SET with TTL: 300 s if complete, 60 s if partial
                                                                                  ▼
                    return {rates, errors, partial, cached:false, cacheStatus, cacheKey}
```

Details of each step:

* **Cache key** (`cache_key`): `zippy:rates:{merchantId}:{pickup}:{delivery}:{weightGrams}:{L}:{W}:{H}:{COD|PREPAID}:{codAmount}`,
  e.g. `zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500`. Anything that can change the price is in the key, so changing
  any one input produces a different key. The **order ID is not in the key**: two orders with identical inputs share a quote.
  Because of that, on a cache hit we still copy the cached quotes into *this* order's `shipping_quotes` rows (so selecting a
  carrier later works for this order).
* **Parallel calls** (`_fetch_all`): a `ThreadPoolExecutor` with 3 workers; each runs one adapter's `get_rates`. We `wait()` for at most
  `timeout + 1 s`. Whatever has not finished by then is reported as `TIMEOUT` and **we do not wait for it** (`shutdown(wait=False)`).
  `contextvars.copy_context()` is used so the worker threads keep the `requestId` in their log lines.
* **Adapter call** (`CarrierAdapter.call`, see §5): sets the timeout, sends `X-Request-ID`, classifies failures as
  `TIMEOUT | HTTP_ERROR | UNREACHABLE | BAD_RESPONSE`.
* **Storing quotes** (`_store_quotes`): locks the order row (`FOR UPDATE`) so two simultaneous refreshes cannot collide, then
  deletes and re-inserts the order's quotes. **If a shipment already exists the quotes are left untouched** – what was bought must not change.
* **Cache write:** complete result → `RATE_CACHE_TTL` (300 s); partial result → `PARTIAL_RATE_CACHE_TTL` (60 s) and the failure list is cached with it.
* **Redis down:** every Redis call is wrapped; a `RedisError` is logged as `CACHE_UNAVAILABLE` (warning) and the request carries on to the
  carriers. The response says `cacheStatus: "UNAVAILABLE"`.
* **`cacheStatus` values:** `HIT`, `MISS`, `REFRESH` (you asked for `refresh=true`), `UNAVAILABLE` (Redis broken).

### Flow C – Select a carrier

`POST /api/orders/{id}/select-carrier` with `{carrier, service[, price]}` → `rates.select_carrier`:

1. Unknown carrier code → 400.
2. Lock the order row. If a shipment already exists → 409.
3. Look up the **stored quote** for `(order, carrier, service)`. Not found → 400 ("fetch rates first").
4. **Quoted amount cannot be modified:** the price always comes from the stored quote. If the client *also* sent a `price` and it differs → 409.
   (Extra unknown fields like `quotedPrice` are ignored by the request model.)
5. Update the order: `selected_carrier`, `selected_service`, `quoted_price` (copied from the quote), `status = CARRIER_SELECTED`. Audit + log.

### Flow D – Create the shipment

`POST /api/orders/{id}/shipment` → `shipments.create_shipment`:

1. Lock the order row. No selected carrier → 409. Shipment already exists → 409.
2. Call the selected adapter's `create_shipment` (a real HTTP call to the carrier). Any `CarrierError` → HTTP 502 with the carrier's error code, **nothing is saved**.
3. Insert the `shipments` row (tracking number, carrier's own shipment ID, status `SHIPMENT_CREATED`).
4. Insert the first `shipment_events` row: status `SHIPMENT_CREATED`, event id `created`, raw `{"source":"zippy"}`.
5. Set order status `SHIPPED`; audit + log.

(The order row stays locked while the carrier call is in flight, which guarantees **one booking per order** even if the user double-clicks.)

### Flow E – Carrier webhook arrives

In the demo, the *Mock Carrier Control* page calls `POST /api/mock/{slug}/{tracking}/event`. The mock carrier (`mock_carriers/router.py: send_event`)
builds a payload **in that carrier's own format** and POSTs it back to `POST /api/webhooks/{slug}`. (A real carrier would call that URL itself.)

`shipments.handle_webhook(slug, payload)` returns `(body, http_status)`:

```
payload ─► adapter.parse_webhook ─ fails ─► store in webhook_quarantine (UNPARSEABLE_PAYLOAD) ─► HTTP 400
              │ ok → normalized event {carrier, trackingNumber, status, eventId, reason}
              ▼
   find shipment by (carrier, trackingNumber)  [row locked]
              │ none ─► quarantine (UNKNOWN_TRACKING_NUMBER) ─► HTTP 202   (no shipment is created)
              ▼
   same (carrier, tracking, status, eventId) already stored? ─yes─► HTTP 200 {"status":"duplicate"}
              ▼ no
   transitions.is_valid(current → new)? ─no─► quarantine (INVALID_TRANSITION, with from/to/allowed) ─► HTTP 202; shipment unchanged
              ▼ yes
   INSERT shipment_events (raw payload + normalized JSON)   ← unique constraint protects against a racing duplicate
   UPDATE shipments.status
   DELIVERED? → orders.status = DELIVERED
   NDR?       → create ndr_cases row (reason, attempt number = previous cases + 1), audit NDR_CREATED
              ▼
   HTTP 200 {"status":"processed", "shipmentStatus":…, "ndrCaseId":…}
```

Why 202 for quarantined events? A 2xx tells the carrier "received, stop retrying". We kept the event (in quarantine) for a human to investigate, so
retrying would only create noise. Unparseable payloads get 400 because the sender really did send something malformed.

### Flow F – NDR conversation

1. An NDR webhook creates a case with status `OPEN` (Flow E).
2. **Contact Buyer** → `POST /api/ndr/{id}/contact` → `ndr.contact_buyer`: inserts an `AGENT` message such as
   *"Hi Rahul, your parcel could not be delivered today because we couldn't reach you at the delivery address. Would you like us to attempt delivery again?"*
   (the reason text comes from `REASON_TEXT`). Calling it again does nothing new (it checks if an agent message already exists).
3. **Buyer types a message** → `POST /api/ndr/{id}/message` → `ndr.buyer_message`:
   1. Reject empty text (422) or a case that is already `ACTION_SUBMITTED / CARRIER_ACCEPTED / RESOLVED` (409).
   2. Store the `BUYER` message; audit `BUYER_MESSAGE_RECEIVED`.
   3. `extractor.extract(text)` → an `Intent` (label, date, time, confidence…); audit `INTENT_EXTRACTED`.
   4. `rules.evaluate(intent, order)` → a `Decision` (`ALLOWED`, `REQUIRES_APPROVAL`, `NEEDS_CLARIFICATION`, `NO_ACTION`).
   5. Save `last_intent` and `last_decision` on the case. Case status becomes `NEEDS_APPROVAL` if approval is required, otherwise `OPEN`.
   6. Store an `AGENT` reply chosen by the decision. **Note: even for `ALLOWED` the reply only says "I'll check this with the carrier" – it does not promise anything.**

### Flow G – Reattempt (the safety-critical part)

`POST /api/ndr/{id}/reattempt` → `ndr.reattempt`, in **three separate database transactions**:

* **Transaction 1 – validate and record "submitted".**
  Lock the case. The status must be one of `OPEN / NEEDS_APPROVAL / ACTION_FAILED`, and a buyer request must exist.
  **Re-run the rules engine on the stored intent** (the stored decision is deliberately *not* trusted); if the outcome is not `ALLOWED`
  → 409 with the decision. Otherwise insert a `carrier_actions` row (`ACTION_SUBMITTED`), set the case to `ACTION_SUBMITTED`, and add the
  buyer message **"Your reattempt request has been submitted to the carrier."** Commit.
* **Step 2 – call the carrier**, *outside* any transaction (so no locks are held during a slow network call). Any exception is treated as "not accepted".
* **Transaction 3 – record the outcome.**
  * Accepted → action `CARRIER_ACCEPTED`, case `CARRIER_ACCEPTED`, buyer message **"The carrier has accepted the reattempt request."**, audit + log, then the case becomes `RESOLVED`.
  * Not accepted / error → action `REJECTED`, case `ACTION_FAILED`, buyer message *"The carrier could not confirm the reattempt yet. Our team will follow up with you."*. The acceptance sentence is never written. A failed case can be retried.

The "submitted" text can only be created before the carrier call and the "accepted" text only inside the branch where the carrier said `ACCEPTED`.

After a reattempt is accepted the **shipment** stays `NDR` until the carrier sends the next webhook (`OUT_FOR_DELIVERY`, then `DELIVERED`).

---

## 5. Backend, file by file

### `backend/requirements.txt`, `pytest.ini`, `Dockerfile`, `.dockerignore`
* `requirements.txt` – FastAPI, uvicorn, psycopg 3 (+ pool), redis client, httpx, pytest.
* `pytest.ini` – tells pytest tests live in `tests/`.
* `Dockerfile` – `python:3.12-slim`, install requirements, copy `app/`, `tests/`, `pytest.ini`; run `uvicorn app.main:app` on port 8000.
* `.dockerignore` – excludes caches.

### `app/config.py`
Reads environment variables once at import and exposes them as module attributes (`config.CARRIER_TIMEOUT_MS`, `config.RATE_CACHE_TTL`, …).
Important detail: other code reads `config.X` **at call time** (not copying the value at import), which is why tests can change a setting with `monkeypatch`.
Contains: DB/Redis URLs, the three carrier base URLs (default `CARRIER_BASE_URL + /mock/<carrier>`), `WEBHOOK_BASE_URL`, the timeout (ms), both cache TTLs,
`DEFAULT_MERCHANT_ID`, `SEED_DEMO`, `MAX_AUTO_RESCHEDULE_DAYS`, `LOG_LEVEL`.

### `app/db.py`
* `_NumericAsFloat` – registers a loader so Postgres `NUMERIC` values arrive in Python as `float` (so JSON shows `182.9`, not `"182.90"`).
* `init_pool()` – opens a connection pool (1–12 connections) with `dict_row` (rows are dicts). **Retries for up to 30 s** so the API survives Postgres starting a few seconds later (Docker).
* `conn()` – `with db.conn() as c:` gives a connection that is **one transaction**: commit on normal exit, rollback if an exception escapes. This is why raising `ApiError` inside the block undoes the writes.
* `migrate()` – takes an advisory lock (so two API instances don't migrate at once), creates `schema_migrations`, and runs every `migrations/*.sql` file not yet recorded, in filename order.
* `audit(c, event, entity_type, entity_id, details)` – inserts one `audit_logs` row *in the caller's transaction* (so an audit row exists only if the action committed).

### `app/logs.py`
* `request_id_var` – a `ContextVar` holding the current request's ID.
* `JsonFormatter` – turns a log record into one JSON line: `ts, level, requestId, event, …fields`; `None` values are dropped.
* `setup_logging()` – attaches the JSON handler to the `zippy` logger (once).
* `log(event, level="info", **fields)` – the helper used everywhere: `log("CARRIER_CALL", carrier="FASTSHIP", orderId="…")`.
* `RequestIdMiddleware` – a *pure ASGI* middleware (chosen over `BaseHTTPMiddleware` because that one breaks context variables). For each HTTP request: take `X-Request-ID`
  from the request or generate `req-<12 hex>`, store it in the context var, add it to the response headers, and emit an `HTTP_REQUEST` log line with method, path, status and duration for `/api*` and `/mock*` paths.

### `app/util.py`
* `camelize` / `out(data)` – recursively converts dict keys from `snake_case` to `camelCase` and makes values JSON-safe (datetimes → ISO strings). Services return snake_case dicts straight from the DB; routes wrap them with `out()`.
* `ApiError(status, message, **extra)` – the exception services raise for expected failures. `main.py` turns it into `{"error": message, ...extra}` with that HTTP status.

### `app/schemas.py`
Pydantic models. Two kinds:
* **Request models** (`OrderIn`, `SelectIn`, `MessageIn`) – inherit `CamelIn` so camelCase JSON maps to snake_case attributes; include validation (regexes, `gt=0`) and OpenAPI examples. `OrderIn.merchant_order_id` is the idempotency key.
* **Response models** (`OrderOut`, `RatesOut`, `CarrierFailure`, `ShipmentOut`, `TrackingOut`, `WebhookOut`, `QuarantineOut`, `NdrSummaryOut`, `NdrDetailOut`, `ErrorOut`) – used as `response_model=` so Swagger shows the exact shapes and examples. Several allow extra fields (`extra="allow"`) because the real payload contains more keys than the documented core.

### `app/main.py`
Creates the `FastAPI` app and defines **all routes**. Routes are deliberately thin: validate → call a service → `out(...)`.
* `lifespan` – on startup: set up logging → `db.init_pool()` → `db.migrate()` → `seed()` (if `SEED_DEMO`) → log `APP_STARTED`.
* `docs_url=None` + custom `/docs` route + `/static` mount – serves the **vendored Swagger UI** so docs work without internet.
* `RequestIdMiddleware` is added; `mock_router` is included.
* `@app.exception_handler(ApiError)` – formats errors.
* Helper `E(status, description, example)` builds documented error responses for OpenAPI.
* Routes: health, dashboard, orders (create/list/get), rates (POST+GET), select-carrier, shipment, tracking (`includeRaw`), shipments list, webhook, webhook-quarantine, NDR (list, detail, contact, message, reattempt).
  The create-order route returns a `JSONResponse` so it can choose 201 vs 200. The webhook route returns whatever `(body, status)` the service produced.

### `app/transitions.py`
A dictionary `ALLOWED = {current_status: {allowed next statuses}}` and `is_valid(current, new)`.

| From | May go to |
|---|---|
| SHIPMENT_CREATED | PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY |
| PICKED_UP | IN_TRANSIT, OUT_FOR_DELIVERY |
| IN_TRANSIT | OUT_FOR_DELIVERY, NDR |
| OUT_FOR_DELIVERY | DELIVERED, NDR |
| NDR | OUT_FOR_DELIVERY (reattempt), DELIVERED |
| DELIVERED | nothing (final) |

Forward skips are fine (carriers sometimes lose events). Going backwards, repeating a status under a *new* event id, or any move out of `DELIVERED` is illegal.

### `app/rules.py` – the rules engine
`evaluate(intent, order, today=None) → Decision(outcome, reasons, action, requested_date, requested_window)`.
Order of checks:
1. Confidence < 0.6 or intent `UNKNOWN` → `NEEDS_CLARIFICATION`.
2. `CANCEL_ORDER`, `REFUSE_ORDER` → `REQUIRES_APPROVAL` (it would mean returning the parcel).
3. `SWITCH_TO_PREPAID` → `REQUIRES_APPROVAL`.
4. `ADDRESS_CORRECTION` → `REQUIRES_APPROVAL`.
5. `RESCHEDULE_DELIVERY` / `COD_READY`:
   * If the intent contains a pincode different from the order's → `REQUIRES_APPROVAL`.
   * Work out the target date with `resolve_date`: `today`, `tomorrow`, `day after tomorrow`, `in N days`, or a weekday name (next occurrence, 1–7 days ahead). Unknown text → `NEEDS_CLARIFICATION`. **No date given → tomorrow.**
   * If the target is in the past or more than `MAX_AUTO_RESCHEDULE_DAYS` (2) away → `REQUIRES_APPROVAL`.
   * Otherwise → `ALLOWED`, `action="REATTEMPT"`, with the ISO date and the time window (`"After 6 PM"`, or the plain word like `"evening"`).
6. Anything else → `NO_ACTION`.

The key design rule: **the AI only labels; this file alone grants permission.**

### `app/ai/intent.py`
* `Intent` (pydantic): `intent, date, time, time_window, pincode, confidence, entities`.
* `IntentExtractor` – abstract base with one method `extract(text) → Intent`. **This is the seam where a real LLM would plug in.**
* `MockIntentExtractor` – lowercases the text and checks keywords **in priority order**:
  `cancel` → CANCEL_ORDER · "don't want / refuse / not interested / return it" → REFUSE_ORDER · "address / pincode / deliver to" → ADDRESS_CORRECTION ·
  a lone 6-digit number → ADDRESS_CORRECTION · "prepaid / pay online / upi" → SWITCH_TO_PREPAID · "payment ready / cash ready / will pay" → COD_READY ·
  any date or time word, or "come / reattempt / try again" → RESCHEDULE_DELIVERY (0.95) · a bare "yes/ok/sure" → RESCHEDULE_DELIVERY (0.7) · otherwise UNKNOWN (0.2).
  Dangerous intents are checked first so "cancel, don't come tomorrow" is not mistaken for a reschedule.
  Helpers `_date` (finds tomorrow/today/day-after/weekday/"in N days") and `_time` (morning/afternoon/evening/night plus "after 6" → "After 6 PM"; no am/pm defaults to PM unless "morning").
* `extractor = MockIntentExtractor()` – the single instance the app imports.

### `app/carriers/base.py` – the adapter contract
* `CarrierError(code, message, duration_ms)` – the one exception adapters raise for any carrier problem.
* `NormalizedRate` – **the only rate shape outside the adapters**: `carrier, carrierName, service, serviceName, price, etaMinDays, etaMaxDays`.
* Dataclasses `ShipmentResult`, `WebhookEvent`, `ReattemptResult` – the normalized results of the other operations.
* `CarrierAdapter` (abstract) with four methods every carrier must implement: `get_rates`, `create_shipment`, `parse_webhook`, `request_reattempt`.
* `CarrierAdapter.call(operation, method, path, order_id, **kw)` – **the single place that talks HTTP to carriers**:
  builds the URL from `config.CARRIER_URLS[slug]`, applies `CARRIER_TIMEOUT_MS`, forwards `X-Request-ID`, calls `raise_for_status`, parses JSON, logs `CARRIER_CALL`
  with duration on success, and on failure logs `CARRIER_CALL_FAILED` and raises `CarrierError` with code `TIMEOUT` (httpx timeout), `HTTP_ERROR` (4xx/5xx), `UNREACHABLE` (connection errors) or `BAD_RESPONSE` (invalid JSON).

### `app/carriers/fastship.py`, `quickexpress.py`, `reliable.py`
Each defines `code`, `slug`, `name` and its own vocabulary tables, and implements the four methods. This is where the three **different contracts** live:

| | FastShip | QuickExpress | ReliableCourier |
|---|---|---|---|
| Rates request | `POST /rates` camelCase: `origin, destination, weightGrams, dimensions{lengthCm,widthCm,heightCm}, cod, codAmount` | `POST /rates` snake_case: `from_pin, to_pin, weight_grams, dimensions_cm{l,w,h}, payment_mode, cod_value` | `GET /rates?pickup&drop&wt(kg)&l&b&h` |
| Rates response | `{service, price, etaDays}` | `{product, payable, deliveryEstimate}` | `{options:[{code, amount, days}]}` |
| ETA mapping | min = max = `etaDays` | max = estimate, min = estimate − 1 (≥ 1) | max = days, min = days − 1 (≥ 1) |
| Create | `POST /shipments` → `{shipmentId, awb}` | `POST /bookings` → `{booking:{id, tracking}}` | `POST /consignments` → `{consignmentNo, trackingRef}` |
| Webhook in | `{trackingNumber, status:"PKD/INT/OFD/DLV/NDR", eventId, reasonCode}` | `{awb, id, event:{code:"PICKUP_DONE/…/DELIVERY_FAILED", reason}}` | `{reference, seq, state:"Picked Up/…/Undelivered", undeliveredCode}` |
| Reattempt | `POST /ndr-action` → `{status:"ACCEPTED"}` | `POST /ndr/{awb}/reattempt` → `{result:"OK"}` | `POST /consignments/{ref}/redeliver` → `{accepted:true}` |

`normalize_rates` is a **static, pure** function in each adapter (easy to unit-test without any HTTP). `parse_webhook` maps the carrier's status/reason codes to Zippy's internal ones
(`PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, NDR` and the five NDR reasons). A missing key raises `KeyError`, which the webhook handler converts into an `UNPARSEABLE_PAYLOAD` quarantine entry.
`request_reattempt` converts each carrier's yes/no into `ReattemptResult("ACCEPTED" | "REJECTED", message, raw)`.

### `app/carriers/registry.py`
`ADAPTERS` (list of the three instances), `BY_CODE` (`"FASTSHIP"` → adapter, used when we already know our own code) and `BY_SLUG` (`"fastship"` → adapter, used by the webhook URL).
Adding a carrier = write an adapter + add it here.

### `app/mock_carriers/router.py` – the fake carriers
* **Fault injection:** `STATE[slug] = {"fail": bool, "delayMs": int}`. `_gate(slug)` is awaited at the top of every carrier endpoint: sleeps `delayMs` first, then returns 503 if `fail`.
  `POST /mock/_control/failures {"carrier", "fail"?, "delayMs"?}` changes it; `GET` shows it. A delay larger than `CARRIER_TIMEOUT_MS` produces a real timeout.
* **Pricing:** `_chargeable_kg(grams, l, w, h, divisor)` = the larger of real weight and volumetric weight (`l·w·h / divisor`; divisors 5000 / 4000 / 6000 differ per carrier).
  `_zone_factor(origin, dest)` adds 5% per leading-digit gap beyond 4 and gives a 10% discount when both pincodes start with the same digit.
  FastShip `(119.9 + 42·kg)`, QuickExpress `(134.06 + 42·kg)`, ReliableCourier `(99.30 + 40·kg)` times the zone factor – which gives the demo prices ₹182.90 / ₹197.06 / ₹159.30 for 1.5 kg, 560001 → 110001.
* **Endpoints** per carrier: rates, create, reattempt (`attempt >= 3` is rejected to demo failure). IDs are random digits (`FS-######`, `FST#########`, `QX-`/`QXP`, `RC-`/`RLC`).
* **Webhook sender:** `build_webhook(slug, tracking, status, reason, event_id)` converts Zippy's status into the carrier's own code/shape using the `FS_*`, `QX_*`, `RC_*` tables.
  `POST /api/mock/{slug}/{tracking}/event {status, reason?, eventId?}` generates a random `event_id` unless you pass one (passing the same one twice simulates a duplicate), POSTs the payload to `WEBHOOK_BASE_URL/api/webhooks/{slug}`, and returns what it sent plus Zippy's reply.

### `app/services/orders.py`
`get_order` (404 if missing, optional `FOR UPDATE` lock – used everywhere else), `_existing`, `_replay`, `create_order` (Flow A), `list_orders` (joined with shipment status), `order_detail` (order + its shipment).
`_SIGNATURE` lists the fields compared when deciding whether a repeated `merchantOrderId` is the *same* order.

### `app/services/rates.py`
`cache_key`, `_fmt_amount` (2500.0 → `2500`, 99.5 → `99.50`), `_cache_get` (returns status + value), `_cache_set`, `_fetch_all`, `_store_quotes`, `get_rates` (Flow B), `select_carrier` (Flow C).
The Redis client is created with 1-second connect/read timeouts so an outage costs about a second rather than hanging.

### `app/services/shipments.py`
`create_shipment` (Flow D), `tracking` (current status + ordered history; `include_raw` adds `raw` and `normalized`), `list_shipments`, `_quarantine` (insert helper that also logs), `handle_webhook` (Flow E), `list_quarantine`.
`VALID_REASONS` guards against unknown NDR reasons (falls back to `CUSTOMER_UNAVAILABLE`).

### `app/services/ndr.py`
`REASON_TEXT` (human wording per reason), `_msg` (insert chat message), `_case_row` (case joined with order + shipment, optional lock), `list_cases`, `case_detail` (case + messages + carrier actions + audit entries for that case),
`contact_buyer`, `_agent_reply` (chooses the reply by decision outcome), `buyer_message`, `reattempt` (Flows F and G).
`case_detail_after` is a trivial wrapper left over from refactoring; it just calls `case_detail`.

### `app/services/dashboard.py`
`summary()` – five counters (orders, shipments, in transit = PICKED_UP/IN_TRANSIT/OUT_FOR_DELIVERY, delivered, NDR cases) plus the 5 most recently updated shipments and 5 latest NDR cases.

### `app/seed.py`
Runs at startup if `SEED_DEMO=true`. Always ensures merchant `MER-DEMO` exists; **only if there are no orders at all** it creates order `ZPY-ORD-10001` (merchantOrderId `DEMO-1001`, Rahul Sharma, COD ₹2500, 1500 g, 20×15×10),
the three matching quotes, and a FastShip shipment `FS-700001` / `FST123456789` with its `SHIPMENT_CREATED` event. That makes the Mock Carrier Control page usable immediately.

### `app/migrations/001_init.sql` and `002_assignment_compliance.sql`
See §6. `001` creates the original schema; `002` adds merchant order IDs, grams + dimensions (and drops `weight_kg`), the `normalized` column, and the `webhook_quarantine` table.

### `app/static/swagger-ui/`
The files Swagger UI needs (`swagger-ui-bundle.js`, `swagger-ui.css`, favicon, licence). Vendored so `/docs` has no CDN dependency.

---

## 6. Database

All timestamps are `TIMESTAMPTZ`. Money is `NUMERIC(10,2)`.

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `merchants` | Who is shipping. | `id` PK, `name`. Auto-created when an unknown `merchantId` appears. |
| `orders` | One row per order. | `id` (`ZPY-ORD-n`), `merchant_id` FK, `merchant_order_id`, customer fields, `pickup_pincode`, `delivery_pincode`, `weight_grams`, `length_cm/width_cm/height_cm`, `payment_mode` (COD/PREPAID check), `cod_amount`, `status`, `selected_carrier`, `selected_service`, `quoted_price`. **Unique index on `(merchant_id, merchant_order_id)` where not null** = order idempotency. |
| `shipping_quotes` | The quotes an order may choose from. | `order_id`, `carrier`, `service`, `service_name`, `price`, `eta_min_days`, `eta_max_days`; `UNIQUE(order_id, carrier, service)`. |
| `shipments` | The booked parcel. | `order_id` **UNIQUE** (one shipment per order), `carrier`, `service`, `carrier_shipment_id`, `tracking_number` **UNIQUE**, `status`, `updated_at`. |
| `shipment_events` | Full tracking history. | `shipment_id`, `carrier`, `tracking_number`, `status`, `event_id`, `reason`, `raw` (carrier payload), `normalized` (Zippy's reading), `occurred_at`. **`UNIQUE(carrier, tracking_number, status, event_id)`** = webhook idempotency. |
| `webhook_quarantine` | Events we refused to apply. | `carrier`, `tracking_number` (nullable), `reason` (`UNKNOWN_TRACKING_NUMBER` / `INVALID_TRANSITION` / `UNPARSEABLE_PAYLOAD`), `detail`, `raw`, `normalized`, `request_id`, `received_at`. |
| `ndr_cases` | One per failed delivery attempt. | `id` default `'NDR-' || nextval('ndr_seq')` (starts 1001), `shipment_id`, `order_id`, `reason`, `attempt_number`, `status`, `last_intent` (JSON), `last_decision` (JSON), `resolved_at`. |
| `conversation_messages` | The simulated WhatsApp chat. | `ndr_case_id`, `sender` (`BUYER`/`AGENT`), `message`, `timestamp`. |
| `carrier_actions` | Requests we made to the carrier for a case. | `ndr_case_id`, `action_type` (`REATTEMPT`), `status` (`ACTION_SUBMITTED` → `CARRIER_ACCEPTED` / `REJECTED`), `request`, `response` (JSON). |
| `audit_logs` | Append-only business event log. | `event`, `entity_type`, `entity_id`, `details` (JSON). |
| `schema_migrations` | Which migration files have run. | `name`. Created by `db.migrate()`. |

Sequences: `order_seq` (10001…) and `ndr_seq` (1001…). Indexes exist on the foreign-key lookups used by the app.

**Why two JSON columns on `ndr_cases` (`last_intent`, `last_decision`)?** The UI shows "what the AI understood" and "what the rules said" without extra tables; the audit log and chat keep the history.

---

## 7. Frontend, file by file

Stack: React + TypeScript + Vite + Tailwind CSS (v4) + `react-router-dom`. No state library; each page fetches what it needs.

| File | What it does |
|---|---|
| `index.html` | The single HTML shell; title "Zippy"; mounts `#root`. |
| `src/main.tsx` | Starts React inside a `BrowserRouter`. |
| `src/index.css` | Imports Tailwind; sets the page background/text colour. |
| `src/App.tsx` | Layout: dark left sidebar (nav links) + main area; declares the 8 routes. |
| `src/api.ts` | `api(path, method, body)` – a small `fetch` wrapper that sends JSON, parses the reply, and **throws `ApiError`** with the server's `error` message (or joins FastAPI validation errors). Also the TypeScript types `Rate`, `Message`, `NdrDetail`. |
| `src/ui.tsx` | Shared building blocks: `Badge` (coloured status pill), `Card`, `PageTitle`, `Btn`, `ErrorBox`, table cells `Th`/`Td`, formatting helpers (`inr`, `nice` = `OUT_FOR_DELIVERY` → "Out For Delivery", `ago`), carrier name/slug maps, and **`useFetch(path, pollMs)`** – loads data, optionally re-polls every N ms, returns `{data, error, reload, setData}`. |
| `vite.config.ts` | Dev server on 5173; proxies `/api`, `/mock/`, `/docs`, `/openapi.json`, `/static/` to the API on :8000. (`/mock/` has a trailing slash so it does not swallow the `/mock-control` page route.) |
| `nginx.conf` | Production equivalent of the proxy: serves the built files; forwards the same paths to `api:8000`; unknown paths fall back to `index.html` (so React Router deep links work). |
| `Dockerfile` | Stage 1: `node` builds the app (`npm ci && npm run build`). Stage 2: `nginx` serves `dist/` with `nginx.conf`. |
| `package.json`, `tsconfig*.json`, `.oxlintrc.json`, `.gitignore`, `.dockerignore`, `public/*.svg` | Standard Vite template/tooling files (dependencies, TypeScript settings, linter config, ignore lists, template icons). Nothing project-specific. |

### Pages (`src/pages/`)

* **`Dashboard.tsx`** – polls `/api/dashboard` every 4 s. Five count cards + "Recent shipments" and "Recent NDR cases" tables with links.
* **`CreateOrder.tsx`** – the form (prefilled with the demo order; Merchant order ID is auto-generated like `SHOP-1234`). Submits to `/api/orders`. If the response has `duplicate: true`, shows the yellow *duplicate protection* notice with a link; otherwise navigates to `/orders/{id}/rates`.
* **`Rates.tsx`** – on load calls `POST /api/orders/{id}/rates`. Shows one card per rate (carrier, service, ₹price, ETA, "Cheapest" tag), a **sort selector** (price / delivery time / carrier name – done in the browser), the **cache label** (hit / miss / refreshed / Redis unavailable) with the full cache key underneath,
  a yellow banner **per failed carrier** (code, duration, message), a *Refresh rates* button (`?refresh=true`), *Select Carrier* per card and *Create Shipment*. After creating the shipment it goes to the tracking page.
* **`Tracking.tsx`** – with no order in the URL it lists all shipments to pick from. With an order it polls `/api/orders/{id}/tracking?includeRaw=true` every 3 s and shows a progress checklist, the full status history (each event expandable to *raw / normalized*), and a link to Mock Carrier Control.
* **`MockControl.tsx`** – pick a shipment; buttons *Pickup / In Transit / Out For Delivery / Trigger NDR / Delivered* each call `/api/mock/{slug}/{tracking}/event` (NDR also sends the chosen reason). A *Resend last webhook* button replays the same event id to show duplicate handling.
  Shows a log of the last webhooks (HTTP code, result, payload in the carrier's own format) and the **quarantine table** (polled from `/api/webhook-quarantine`).
* **`NdrList.tsx`** – table of all cases (Case ID, Order, Customer, Carrier, Reason, Attempt, Status), polled every 3 s.
* **`NdrDetail.tsx`** – three columns: case/customer/shipment info; the WhatsApp-style chat (with *Contact Buyer* first, then a text box acting as the buyer); and the "AI intent → rules → action" panel (extracted intent, date/time, confidence, rules outcome + reasons, *Request Reattempt* button – enabled only when the decision is `ALLOWED` and the status is `OPEN`/`ACTION_FAILED`),
  plus carrier actions and the audit trail.

---

## 8. Tests

Run with `cd backend && python -m pytest`. **59 tests.**

### `tests/conftest.py` – the test harness
* Sets environment variables **before** importing the app: test database `zippy_test`, Redis db 15, and all carrier/webhook URLs pointing at port 8765.
* `server` fixture – drops/recreates `zippy_test`, flushes Redis, starts a **real uvicorn server in a background thread** (so adapters → mock carriers → webhooks go over genuine HTTP).
* `api` – an `httpx` client to that server. `_clean_redis` (autouse) flushes Redis before every test so cached results don't leak between tests.
* `logs` – captures the app's structured log records for assertions. `new_order_body()` / `order` / `shipped` / `ndr_case` fixtures build orders, shipments and NDR cases quickly; `send_event()` fires a mock-carrier webhook.

### `tests/test_units.py` – pure logic, no server
Rate normalization for all three carriers · intent extraction examples and entities · rules (allowed / approval / unknown) · **cache key contains every input and changes with each** · transition table.

### `tests/test_api.py` – behaviour through the real API
Order creation/validation/idempotency (replay, conflict, per-merchant, 6 concurrent requests) · rates (normalized, miss→hit with zero carrier calls, shared cache between identical orders, refresh, expiry, per-field cache-key change, prices react to weight/volume) ·
partial failure (TTL, cached partial, recovery) · carrier **timeout** (returns in < 2.5 s though the carrier sleeps 5 s) · all carriers failing (502) · **Redis outage** (still 200, selection still works) · selection and immutable quote ·
shipments for each carrier · webhook vocabularies · raw+normalized stored · duplicate webhook (also 6 concurrent) · unknown tracking · unparseable payload · status regression · NDR creation · full reattempt flow and message ordering · rules blocking · carrier rejection / timeout never claiming acceptance ·
structured logs carry `requestId/orderId/carrier/shipmentId` · OpenAPI/Swagger · dashboard · seed data · the full E2E demo.

---

## 9. Infrastructure

### `docker-compose.yml`
* `postgres` (16-alpine, user/db/password `zippy`, volume `pgdata`, healthcheck `pg_isready`).
* `redis` (7-alpine, healthcheck `redis-cli ping`).
* `api` – built from `./backend`; environment sets `DATABASE_URL`, `REDIS_URL`, the carrier URLs (pointing to itself on 127.0.0.1:8000 – the mock carriers), timeouts/TTLs; port 8000; waits for healthy postgres and redis.
* `web` – built from `./frontend`; port 3000→80; depends on `api`.

### `.env.example`
Documents every variable and its default (copy to `.env` for non-Docker runs).

### Environment variables (all optional thanks to defaults)
`DATABASE_URL, REDIS_URL, CARRIER_BASE_URL, FASTSHIP_BASE_URL, QUICKEXPRESS_BASE_URL, RELIABLE_BASE_URL, WEBHOOK_BASE_URL, CARRIER_TIMEOUT_MS (3000), RATE_CACHE_TTL (300), PARTIAL_RATE_CACHE_TTL (60), DEFAULT_MERCHANT_ID, SEED_DEMO, MAX_AUTO_RESCHEDULE_DAYS (2), LOG_LEVEL`.

### Startup sequence in Docker
postgres + redis become healthy → `api` starts → pool connects (retrying) → migrations 001, 002 run → seed → `APP_STARTED` log → `web` serves the UI.

---

## 10. Cross-cutting logic

**Transactions and locking.** `with db.conn()` is one transaction. Money-relevant operations lock the order row (`SELECT … FOR UPDATE`): select-carrier, create-shipment, store-quotes. NDR operations lock the case row. Webhooks lock the shipment row.
This serialises concurrent requests for the same object, which is how double-clicks and racing duplicates are handled safely.

**Idempotency – four places.** Orders: unique index on merchant + merchant order ID. Webhooks: unique constraint on carrier + tracking + status + event id. Shipments: one per order (unique + lock). Reattempts: a case can only be submitted from `OPEN / NEEDS_APPROVAL / ACTION_FAILED`, and after acceptance it is `RESOLVED` (a second click → 409).

**Timeouts.** Every carrier call goes through `CarrierAdapter.call` with `CARRIER_TIMEOUT_MS`. The rate fan-out adds a hard deadline. No retries (documented choice).

**Cache.** Redis is only an accelerator, never required. Keys include all pricing inputs; TTL 300 s (complete) / 60 s (partial). Postgres always has the quotes needed for selection.

**Error handling.** Expected problems → `ApiError(status, message, …)` → `{"error": "...", ...}`. Validation problems → FastAPI's 422. Carrier problems → `CarrierError` caught and either reported per carrier (rates), turned into 502 (shipment), or recorded as a failed action (reattempt).

**camelCase boundary.** The database and Python use snake_case; JSON in and out uses camelCase. Conversion happens at the edges: request models via aliases, responses via `out()`.

**Logging.** One JSON line per event with `requestId`; business events (`ORDER_CREATED`, `RATE_REQUEST`, `CARRIER_CALL`, `WEBHOOK_QUARANTINED`, `SHIPMENT_STATUS_UPDATED`, `NDR_CREATED`, `CARRIER_ACTION_*`, …) plus an `HTTP_REQUEST` line per request. Filter by `requestId` to follow one request across the API, the carrier calls and the webhook it triggers.

**The buyer-honesty rule.** Message text is chosen by code position: "submitted" before the carrier call, "accepted" only in the accepted branch. There is no code path that writes "accepted" otherwise.

**AI vs rules.** The extractor produces a label; `rules.evaluate` is the only thing that can say `ALLOWED`. `reattempt` re-evaluates the rules itself rather than trusting stored output.

---

## 11. State machines

**Shipment status** (`shipments.status`, enforced by `transitions.py`)
```
SHIPMENT_CREATED → PICKED_UP → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED (end)
        │(skips allowed)           │                │  ▲
        └──────────────────────────┴────► NDR ◄─────┘  │
                                            └───────────┘ (reattempt: NDR → OUT_FOR_DELIVERY, or NDR → DELIVERED)
```
NDR is reachable from IN_TRANSIT and OUT_FOR_DELIVERY only.

**Order status** (`orders.status`): `CREATED → CARRIER_SELECTED → SHIPPED → DELIVERED`.

**NDR case status** (`ndr_cases.status`)
```
OPEN ──buyer message, rules say approval needed──► NEEDS_APPROVAL (a new allowed message returns it to OPEN)
OPEN / NEEDS_APPROVAL / ACTION_FAILED ──/reattempt (rules must say ALLOWED)──► ACTION_SUBMITTED
ACTION_SUBMITTED ──carrier ACCEPTED──► CARRIER_ACCEPTED ──immediately──► RESOLVED
ACTION_SUBMITTED ──carrier refuses / error / timeout──► ACTION_FAILED (can be retried)
```

**Carrier action** (`carrier_actions.status`): `ACTION_SUBMITTED → CARRIER_ACCEPTED` or `REJECTED`.

---

## 12. Cookbook

**Add a fourth carrier** – (1) add mock endpoints in `mock_carriers/router.py` (or point a URL at a real one) and a `STATE` entry; (2) create `carriers/<name>.py` implementing the four adapter methods with its own vocab; (3) add it to `registry.ADAPTERS`; (4) add a base URL in `config.py`/`CARRIER_URLS`; (5) add a webhook builder branch in the mock; (6) add the carrier to `CARRIER_NAMES/CARRIER_SLUG` in `ui.tsx`. Nothing in services or pages changes.

**Add a new intent** – add the label to `INTENTS` and a keyword branch in `MockIntentExtractor.extract`; add the policy branch in `rules.evaluate`; optionally a reply in `_agent_reply`.

**Change the auto-approve window** – set `MAX_AUTO_RESCHEDULE_DAYS`.

**Add an NDR reason** – add it to `NDR_REASONS`/`VALID_REASONS`, the three adapters' `REASON` tables, the mock `FS_REASON/QX_REASON/RC_REASON` tables, `REASON_TEXT` in `ndr.py`, and the dropdown in `MockControl.tsx`.

**Allow another status transition** – edit `transitions.ALLOWED` (and the table in `docs/assumptions.md`).

**Add a migration** – create `migrations/003_<name>.sql`; it runs automatically on next start.

**Swap the mock AI for a real LLM** – implement `IntentExtractor.extract` to call the model and **validate** its output into `Intent`; assign it to `extractor`. Keep `rules.py` untouched.

**Watch it work** – `docker compose logs -f api | grep requestId`, or open `/docs` and try the endpoints.

---

## 13. Gaps and gotchas

Being straightforward about what a careful reader should know:

1. **Crash window in `reattempt`.** It uses three transactions. If the process dies after step 1 and before step 3, the case stays `ACTION_SUBMITTED` forever (the buyer was told "submitted", never "accepted" – honest, but stuck). Production fix: a recovery job or an outbox.
2. **Money as float** in Python (stored as NUMERIC). Fine for 2-decimal equality here; use Decimal/paise in production.
3. **Shipment creation holds a DB row lock during the carrier call** (≤ `CARRIER_TIMEOUT_MS`). Acceptable at MVP scale; production would use a queue.
4. **No retries** of carrier calls, and **no stampede protection** on cache misses (several simultaneous misses all call the carriers).
5. **No authentication**, no webhook signatures; `merchantId` is not a security boundary.
6. **Late/out-of-order webhooks** are handled by the transition table (they get quarantined), but there is no timestamp/sequence ordering and no reconciliation polling.
7. **Mock carrier state is in memory** (fault injection settings reset on restart) and mock carriers don't remember shipments; the reattempt endpoint accepts any tracking number.
8. **Mock AI** is keyword matching, English only. "Yes" alone is treated as a reschedule request with confidence 0.7 and defaults to *tomorrow*.
9. **Dates are server-local** (`date.today()`), with no time-zone handling.
10. **Seed** only runs when the orders table is empty; on a database that already has orders the demo order is not recreated.
11. **Docker Hub / proxy note:** in restricted networks building the images may need registry/proxy access; this is environmental, not part of the code.
