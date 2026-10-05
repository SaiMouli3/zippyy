# Zippy – logistics aggregation MVP (first vertical slice)

WhatsApp / voice agent → Zippy backend → 3 mock carriers → normalized quotes → select → book → webhooks → tracking.

## 1. Architecture

```
 WhatsApp (mock endpoint)      Voice (MockVoiceProvider)        Admin dashboard (Next.js)
   POST /api/agent/message       POST /api/voice/mock-call         REST calls
            │                             │                             │
            └────────── AgentService ─────┘                             │
                        AgentProvider (rule-based today, LLM later)     │
                               │ only through ZippyTools                │
                               ▼                                        ▼
 ┌─ API layer ───────────── app/api/*  (FastAPI routes, schemas, error mapping) ───────────┐
 ├─ Application services ── app/services/{orders,rates,shipments,tracking}.py              │
 ├─ Domain ───────────────── app/domain/*  (enums, status-transition rules, neutral types) ┤
 ├─ Carrier adapter interface  app/carriers/base.py  CarrierAdapter                        │
 ├─ Carrier implementations ── fastship.py · quickexpress.py · reliable.py                 │
 └─ External carrier APIs ──── app/mock_carriers/*  (mounted in-process; separate modules) ┘
        ▲ Postgres (orders, quotes, shipments, events)      ▲ Redis (rate cache, conversation state)
```

Rules enforced by structure:
* Services and agents only see `NormalizedRate / NormalizedShipment / NormalizedEvent` (`app/domain/carrier_types.py`).
  Carrier-specific JSON exists only inside `app/carriers/<carrier>.py`.
* `app/agent/*` never imports an adapter or an HTTP client (there is a test for that). It calls `ZippyTools`, which calls services.
* Adapters reach carriers through `CARRIER_BASE_URL` over real HTTP, so the mock carriers are already "remote" and can be moved out.

Key behaviours
* **Rates**: all carriers called concurrently (`asyncio.gather`), each with its own timeout; a failing/slow carrier lands in `failedCarriers`, the rest are returned, sorted by total. Quotes are stored per fetch (`batch_id`).
* **Cache**: key `zippy:rates:{merchant}:{pickup}:{delivery}:{grams}:{l}:{w}:{h}:{payment}:{cod}`, TTL 5 min. `POST …/rates?refresh=true` bypasses it. Partial results (a carrier failed) are *not* cached. Cache outages degrade to live calls.
* **Select**: quote must belong to the order, be in the latest batch, be unexpired (15 min), and `quotedAmount` must equal the stored total. The amount on the shipment is copied from the stored quote (never from the client).
* **Book**: idempotent (a second call returns the same tracking number). Booking is not auto-retried (a timeout may still have booked at the carrier).
* **Webhooks**: each carrier has its own payload format → `normalize_webhook`. Idempotency key = `{carrier}:{event id}` (hash fallback), unique in DB. Duplicates return 200 `duplicate`; backwards moves (e.g. `DELIVERED → IN_TRANSIT`) return 200 `ignored` and change nothing (200 so the carrier doesn't retry forever).

## 2. Folder structure

```
backend/
  app/
    main.py config.py db.py models.py schemas.py cache.py http.py
    api/            orders.py shipments.py webhooks.py agent.py
    services/       orders.py rates.py shipments.py tracking.py
    domain/         enums.py errors.py tracking.py carrier_types.py
    carriers/       base.py registry.py fastship.py quickexpress.py reliable.py
    mock_carriers/  common.py control.py fastship.py quickexpress.py reliablecourier.py
    agent/          tools.py provider.py rule_based.py voice.py
  tests/            52 tests (SQLite + fakeredis, carriers called in-process)
frontend/           Next.js + TS + Tailwind: /orders, /orders/[id], …/rates, …/tracking, /mock
docker-compose.yml  .env.example
```

## 3. Setup

```bash
cp .env.example .env
docker compose up --build
# frontend http://localhost:3000   backend http://localhost:8000/docs
```

Without Docker (needs local Postgres + Redis, or point `DATABASE_URL` at SQLite):
```bash
cd backend && pip install -r requirements-dev.txt
DATABASE_URL=sqlite:///./dev.db REDIS_URL=redis://localhost:6379/0 uvicorn app.main:app --reload
python -m pytest            # tests need no Postgres/Redis
cd ../frontend && npm install && npm run dev
```
Tables are created on startup (`create_all`); there are no migrations yet.

## 4. Sample curl

```bash
H='Content-Type: application/json'; API=http://localhost:8000

# order
ORDER=$(curl -s -X POST $API/api/orders -H "$H" -d '{
  "customerName":"Asha Rao","customerPhone":"9876543210","pickupPincode":"560001","deliveryPincode":"500001",
  "weightGrams":2000,"lengthCm":20,"widthCm":15,"heightCm":10,"paymentType":"COD","codAmount":2000}' | jq -r .id)

# rates (3 carriers, normalized, cheapest first); repeat it -> "cached": true
curl -s -X POST $API/api/orders/$ORDER/rates | jq
curl -s -X POST "$API/api/orders/$ORDER/rates?refresh=true" | jq .cached

# select + book
curl -s -X POST $API/api/orders/$ORDER/select-carrier -H "$H" \
  -d '{"carrierCode":"FASTSHIP","serviceCode":"FAST-AIR","quotedAmount":195.2}' | jq
TRACK=$(curl -s -X POST $API/api/orders/$ORDER/shipment | tee /dev/stderr | jq -r .trackingNumber)

# advance the carrier (it fires the webhook to Zippy), then track
curl -s -X POST $API/mock/fastship/shipments/$TRACK/next-status | jq
curl -s -X POST "$API/mock/fastship/shipments/$TRACK/next-status?duplicate=true" | jq .deliveries   # applied + duplicate
curl -s $API/api/orders/$ORDER/tracking | jq

# raw mock carriers + failure simulation
curl -s -X POST "$API/mock/fastship/api/v1/rate?failure=true" -H "$H" -d '{"weight_kg":2}' -o /dev/null -w "%{http_code}\n"   # 500
curl -s -X POST "$API/mock/fastship/api/v1/rate?delay=3000"  -H "$H" -d '{"weight_kg":2}'                                   # slow
curl -s "$API/mock/reliablecourier/shipping-options?from=560001&to=500001&weight=2&cod=true&amount=2000" | jq
curl -s -X PUT "$API/mock/quickexpress/config?delay=3000"      # make QuickExpress slow for ALL calls (reset: no params)
curl -s -X PUT "$API/mock/fastship/config?failure=true"        # make FastShip fail for all calls

# agent (WhatsApp stand-in)
say(){ curl -s -X POST $API/api/agent/message -H "$H" -d "{\"conversationId\":\"conv-001\",\"message\":\"$1\"}" | jq -r .reply; }
say "I want to send a parcel."; say 560001; say 500001; say "2 kg"; say "COD, ₹2000"; say "Book FastShip"; say "Where is my shipment?"

# voice (scripted call through MockVoiceProvider, same tools)
curl -s -X POST $API/api/voice/mock-call -H "$H" -d '{"utterances":["send a 2kg prepaid parcel from 560001 to 500001","book fastship","where is my shipment"]}' | jq
```
Webhook endpoints (`/api/webhooks/{fastship,quickexpress,reliable}`) can also be hit by hand; see `mock_carriers/*.py::build_webhook` for each payload shape.
Extra mock switches: `next-status?event=delivery_failed|rto` (from any live state), `GET /mock/shipments`, `GET /mock/config`.

## 5. Demo flow (5 minutes)

1. `/orders` → create an order (or message the agent: "I want to send a 2kg parcel from 560001 to 500001").
2. Agent / **Shipping options** page shows 4 options from 3 carriers with different native formats, normalized & sorted. Click *Get rates* again → "served from Redis cache".
3. `/mock` → tick **FastShip: fail** (or *slow*) → *Refresh (skip cache)* on the options page: the other carriers still answer, FastShip appears under "unavailable". Untick it.
4. Book FastShip (button, or tell the agent "Book FastShip") → tracking number appears.
5. `/mock` → **Trigger Next Status** repeatedly; `/orders/{id}/tracking` (auto-refreshes) shows each webhook landing: PICKED_UP → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED.
6. Ask the agent "Where is my shipment?" at any point.
7. Idempotency: `next-status?duplicate=true` → second delivery is `duplicate`; POST an old status payload to the webhook → `ignored`.

## 6. Where real providers plug in

**WhatsApp** (Twilio / Meta Cloud API / Gupshup): add a route such as `POST /api/channels/whatsapp` that (1) verifies the provider signature, (2) maps the inbound payload to `conversation_id = sender phone`, `message = text` (and `customer_phone`), (3) calls `AgentService(db).handle(...)` – exactly what `api/agent.py::agent_message` does – and (4) sends `reply` back with the provider's send API. Nothing inside the agent or services changes. Optional speech (Sarvam etc.) transcribes voice notes into `message` before step 3.

**LLM**: implement `AgentProvider.respond(conversation, message, tools)` (`app/agent/provider.py`) using your LLM's function calling with `TOOL_SCHEMAS` from `app/agent/tools.py`, dispatch each tool call via `tools.call(name, **args)`, register it in `get_agent_provider()` and set `AGENT_PROVIDER`. `Conversation.history` already holds the transcript.

**Voice** (Twilio Voice, Exotel, Plivo, LiveKit…): implement `VoiceProvider` (`handle_incoming_call`, `speak`, `collect_input`, `end_call`) in `app/agent/voice.py` – STT inside `collect_input`, TTS inside `speak` – and run `VoiceAgent(provider, AgentService(db)).run_call(call_id, caller)` from the telephony webhook/stream handler. `MockVoiceProvider` and `POST /api/voice/mock-call` show the shape; the same `ZippyTools` back both channels.

## 7. Replacing a mock carrier with a real one

Business logic does not change; only the adapter and config do.

1. **Credentials/URL**: give the adapter its real base URL + auth (today every adapter uses `CARRIER_BASE_URL`; use a per-carrier setting and put auth headers in `CarrierAdapter._send` or an override).
2. **Request mapping**: edit `build_rate_request` / `build_shipment_request` in `app/carriers/<carrier>.py` to the real API's paths and fields.
3. **Response mapping**: edit `normalize_rate_response`, `normalize_shipment_response`, and `normalize_webhook` (incl. the carrier's status vocabulary → `ShipmentStatus`, its event-id field for idempotency, and signature verification in `api/webhooks.py`).
4. **Webhook**: register `https://<public-host>/api/webhooks/<slug>` with the carrier (`ZIPPY_PUBLIC_URL`).
5. **Remove the mock**: delete the corresponding router from `main.py` (and `app/mock_carriers/<carrier>.py`). Keep the adapter tests, pointing them at recorded real responses.

Adding a *fourth* carrier: create `app/carriers/<name>.py` (subclass `CarrierAdapter`) and add one line to `registry.py`, plus a webhook route in `api/webhooks.py`. Rates, caching, selection, booking and tracking pick it up automatically.

To move the mock carriers into their own service: they already import nothing from Zippy except `app.config/app.http`; copy `app/mock_carriers/` into a new FastAPI app, set `CARRIER_BASE_URL` to it and `ZIPPY_PUBLIC_URL` to Zippy.

## 8. Known MVP limits
* Mock carrier shipment state is in memory (lost on backend restart); Zippy's data is in Postgres.
* No auth/merchant isolation, no webhook signature checks, no DB migrations, no retries for rates beyond the single timed attempt.
* Sync SQLAlchemy inside async handlers (fine for the MVP; move to async engine or thread offload for load).
* The rule-based agent understands only the demo phrases (pincodes, weight, prepaid/COD, "book <carrier>", tracking questions).
* `docker-compose.yml` was written but not run in the authoring sandbox (no Docker daemon); the backend, Redis and frontend were exercised directly instead.
