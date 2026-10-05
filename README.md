# Zippy – logistics + NDR agent (MVP)

A small modular monolith that demos: order → carrier rates → select → shipment → carrier webhooks → NDR →
simulated WhatsApp → intent → rules → carrier reattempt → buyer confirmation.

```
React (Vite/TS/Tailwind) ──► FastAPI ──► services (orders · rates · shipments/tracking · ndr)
                                         ├─ carriers/   adapters (FastShip, QuickExpress, ReliableCourier)
                                         ├─ mock_carriers/  3 mock carrier APIs + webhook sender (same process, real HTTP)
                                         ├─ ai/intent.py    IntentExtractor interface + MockIntentExtractor
                                         └─ rules.py        deterministic policy (AI never authorises)
                                      PostgreSQL (state)   Redis (rate cache only)
```

## Run

```
docker compose up --build
```
- UI: http://localhost:3000  · API: http://localhost:8000 (docs at `/docs`)
- Seeded: demo merchant, order `ZPY-ORD-10001` (Rahul Sharma) with a FastShip shipment `FST123456789`.

Without Docker: start Postgres + Redis, then `cd backend && pip install -r requirements.txt && DATABASE_URL=... uvicorn app.main:app`
and `cd frontend && npm i && npm run dev` (proxies `/api` and `/mock/` to :8000).

## Tests

```
cd backend && python -m pytest        # needs Postgres + Redis; or: docker compose exec api python -m pytest
```
(`TEST_DATABASE_URL` / `TEST_REDIS_URL` override the defaults; the suite recreates a `zippy_test` database.)
26 tests: normalization, intent, rules, cache, selection, shipment, webhook idempotency, NDR, reattempt, full E2E.

## Demo (3–5 min)
1. **Create Order** (prefilled) → rates page shows 3 carriers (cached on revisit; *Refresh rates* bypasses cache).
2. **Select Carrier** on FastShip → **Create Shipment**.
3. **Mock Carrier Control** → Pickup → In Transit → Out For Delivery → Trigger NDR (each is a real webhook in that carrier's format).
4. **NDR Cases** → open the case → **Contact Buyer** → type `Yes tomorrow evening after 6` → Send.
5. Intent `RESCHEDULE_DELIVERY` + rules `ALLOWED` → **Request Reattempt** → buyer sees "submitted", then "The carrier has accepted…"; case `RESOLVED`.
6. Mock Carrier Control → Delivered → Shipment Tracking shows `DELIVERED`.

Try `cancel this order` / `my address is wrong` / `come on friday` to see the rules engine require approval and block the carrier call.
Simulate an outage: `curl -XPOST localhost:8000/mock/_control/failures -H 'content-type: application/json' -d '{"carrier":"quickexpress","fail":true}'`.

## API
| Method | Path |
|---|---|
| POST | `/api/orders` · GET `/api/orders` · GET `/api/orders/:id` |
| POST/GET | `/api/orders/:id/rates[?refresh=true]` |
| POST | `/api/orders/:id/select-carrier` · `/api/orders/:id/shipment` |
| GET | `/api/orders/:id/tracking` · `/api/shipments` · `/api/dashboard` |
| POST | `/api/webhooks/:carrier` (`fastship` \| `quickexpress` \| `reliable`) |
| GET | `/api/ndr` · `/api/ndr/:id` |
| POST | `/api/ndr/:id/contact` · `/message` · `/reattempt` |
| POST | `/api/mock/:carrier/:trackingNumber/event` (mock carrier control) |
| POST | `/mock/_control/failures` (outage simulation) · `/mock/<carrier>/…` (carrier APIs) |

## Tables
`merchants, orders, shipping_quotes, shipments, shipment_events, ndr_cases, conversation_messages, carrier_actions, audit_logs`
(webhook idempotency = `UNIQUE(carrier, tracking_number, status, event_id)` on `shipment_events`).

## Design notes
- Carrier-specific shapes never leave `app/carriers/*`; everything else sees `NormalizedRate` / `WebhookEvent`.
- Safety rule (`services/ndr.py`): buyer is told "submitted" before the carrier call and "accepted" only after the carrier returns `ACCEPTED`; a rejection never produces an acceptance message.
- `/api/ndr/:id/reattempt` re-runs the rules engine itself; it does not trust the stored decision.
- Partial carrier failure still returns the other carriers; partial results are not cached.

## Known limitations
- No auth, webhook signature verification, or multi-tenancy (single demo merchant).
- Mock intent extractor is keyword-based, English-only; dates resolve relative to server date; no seller-approval workflow (`REQUIRES_APPROVAL` just blocks).
- Out-of-order/late webhooks are applied as received (no status state-machine guard); unknown NDR reasons map to `CUSTOMER_UNAVAILABLE`.
- Prices/ETAs are synthetic. Money is stored as NUMERIC but handled as float in Python.
- Migrations are a single SQL file applied at startup; no WhatsApp/voice, no real carriers.

## Next
Webhook signatures + auth; real LLM `IntentExtractor` with schema-validated output; seller approval queue; carrier status state machine;
WhatsApp provider behind a messaging interface; async job queue for carrier calls/retries; more NDR scenarios (multi-attempt policy, RTO).
