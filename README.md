# Zippyy — logistics aggregation + NDR agent

A production-shaped MVP of a shipping aggregator: a merchant creates an order, Zippyy compares three differently-shaped
mock carriers, locks a quote, books the shipment, ingests carrier webhooks into a normalized tracking history, and an
**NDR (failed delivery) agent** talks to the buyer in their language, extracts intent, applies deterministic seller and
carrier rules, asks for approval when it must, instructs the carrier — and only tells the buyer the carrier *accepted*
after the carrier actually did.

```
Merchant → Order → Rate aggregation → Carrier selection → Shipment → Carrier events → Tracking
        → NDR detection → Buyer conversation → Intent → Rules engine → Carrier action → Reattempt / Delivery / RTO
```

> **Key principle:** Zippyy never delivers parcels, so it never promises delivery. It says "submitted to the carrier", and
> "the carrier has accepted…" only after the carrier returned `ACCEPTED`. See [docs/business-rules.md](docs/business-rules.md).

## Run it

```bash
docker compose up --build        # postgres, redis, mock carriers, backend, frontend
```

| What | URL |
|---|---|
| Web app | <http://localhost:3000> |
| API + Swagger UI | <http://localhost:8080/api/docs> |
| Mock carriers | <http://localhost:9000> |

No Docker? `scripts/dev-local.sh start` runs the stack against local Postgres + Redis (see the script header).

### 5-minute demo (UI)
1. **Create order** → *Fill demo data* → Create. (`MERCHANT-10001`, Rahul Sharma, 560001 → 110001, 1.5 kg, COD ₹2,500)
2. **Get shipping rates** → compare (Reliable Surface ₹159.30 · FastShip Air ₹182.90 · QuickExpress ₹197.06 · Reliable Air ₹202.96) → **Select** FastShip → **Create shipment**.
3. **Mock carrier control** → *Trigger pickup* → *in transit* → *OFD* → *Trigger NDR* (Customer unavailable). Each button makes the mock carrier send a real signed webhook.
4. **Open the NDR case** → *Contact buyer* → pick the sample reply "EN · tomorrow evening" (or type your own, e.g. `kal subah 10 baje ke baad aana, gate pe guard ko bolna`) → *Send as buyer*.
   Watch the timeline: intent extracted → rules checked → action submitted → **carrier accepted** → buyer informed.
5. **Mock carrier control** → *Trigger OFD* → *Trigger delivered* → the case closes; tracking shows the full history.
6. Try the edge cases: *Address (new pincode)* or *Cancel order* (needs approval: switch **Acting as** to Seller → Approvals), *Vague (low confidence)*, *Deliver each webhook 5 times*, *failure injection*, or a regression after delivery (HTTP 409).

Scripted: `./scripts/smoke.sh` (needs a running stack). Roles: the header dropdown **Acting as** sends `X-Zippy-Role`.

## Architecture
Modular monolith in Go (Fiber) + PostgreSQL (source of truth) + Redis (rate cache) + React/Vite UI, with the mock carriers as a
separate service. Diagrams (system, order/rate, tracking, NDR, state machine) are in [docs/architecture.md](docs/architecture.md).

```
HTTP (httpapi) → application services (service, ndr) → domain/rules → repositories (store) → PostgreSQL / Redis
                        └→ carriers.Adapter → FastShip | QuickExpress | ReliableCourier → mock carrier APIs
```

**The rest of the app never sees a carrier format.** `carriers.Adapter` (`GetRates`, `CreateShipment`, `NormalizeWebhook`, `SubmitAction`)
is implemented once per carrier; callers use `registry.Get(code)`. Adding a fourth courier = one new adapter file + one line in `app.Build`
(+ a `carrier_rules` row and a webhook path).

### Tech stack
Go 1.26 · Fiber · pgx · go-redis · PostgreSQL 16 · Redis 7 · React 19 · TypeScript · Vite · Tailwind 4 · TanStack Query · React Hook Form · Zod · React Router · Recharts · Docker Compose · nginx.

### Folder structure
```
apps/api/            Go API (cmd/server, internal/{domain,carriers,rates,rules,agent,comms,store,service,ndr,httpapi,app,platform,config}, testkit)
apps/mock-carriers/  mock FastShip / QuickExpress / ReliableCourier + webhook emitter + control + fault injection
apps/web/            React operations console
packages/shared-types/ TypeScript API types
migrations/          SQL migrations (embedded in the API binary)
docs/                architecture.md, api.md, business-rules.md, assumptions.md, openapi.yaml
tests/               integration + end-to-end tests (real PostgreSQL, Redis, mock carriers, real webhooks)
scripts/             smoke.sh, dev-local.sh
```

## Configuration (`.env.example`)
`DATABASE_URL`, `REDIS_URL`, `FASTSHIP_BASE_URL`, `QUICKEXPRESS_BASE_URL`, `RELIABLECOURIER_BASE_URL`, `ZIPPY_PUBLIC_URL`,
`CACHE_TTL_SECONDS` (5 min), `CACHE_PARTIAL_TTL_SECONDS` (30 s), `CARRIER_TIMEOUT_MS`, `WEBHOOK_SIGNATURE_REQUIRED` + per-carrier
`*_WEBHOOK_SECRET`, `LLM_PROVIDER`, `INTENT_CONFIDENCE_MIN`, `NDR_CONTACT_TIMEOUT`, `NDR_AUTO_CONTACT`, `SEED_DEMO`, `LOG_LEVEL`.
No real secrets are committed; compose defaults are obvious dev placeholders.

## Database & Redis
PostgreSQL schema = `migrations/*.sql`, applied automatically at API start (advisory-locked, tracked in `schema_migrations`).
Tables: orders, shipping_quotes, shipments, shipment_events, webhook_inbox, idempotency_records, seller_rules, carrier_rules, buyer_profiles,
ndr_cases, ndr_events, communication_attempts, conversation_messages, carrier_actions, approvals, audit_logs.
Redis only caches normalized rates; if it is down the API falls back to direct carrier calls.

## API
Full OpenAPI at `/api/docs`; summary in [docs/api.md](docs/api.md). Required endpoints (`/api/orders…`, `/api/webhooks/…`, `/api/ndr/cases…`, `/api/approvals…`, `/api/mock-carriers/…`) are all implemented, plus rules, audit, dashboard, metrics.

## How the important requirements are met
* **Rate caching** – key `zippy:rates:{merchant}:{pickup}:{delivery}:{grams}:{l}:{w}:{h}:{payment}:{cod}`; TTL configurable; `refresh=true`; partial results use a 30 s TTL, total failure is not cached; Redis failure → fallback; single-flight collapses 10 identical misses into 1 carrier fan-out (tested).
* **Quote integrity** – selection compares against the server-stored latest quote set (exists, unexpired, amount equal to the paisa, quote reference); the persisted amount is the stored one.
* **Idempotency** – unique event key per carrier/tracking/event; 5 identical webhooks → 1 event; shipment/order/carrier-action idempotency documented in architecture.md.
* **Status regressions** – explicit transition table; regressions are rejected (409) and quarantined.
* **Webhook security** – HMAC-SHA256 verification abstraction (`WebhookVerifier`), per-carrier secrets, raw payload stored.
* **NDR pipeline** – webhook → case (reason normalized per carrier) → buyer contact (WhatsApp → IVR → SMS, case language) → intent → **rules engine** → approval if needed → carrier action (idempotent, retried) → carrier acceptance → buyer confirmation → delivered/RTO closes the case. Everything is on the case timeline and in the audit log.
* **Language** – `case.language` + `language_source` (reply > stored > seller > pincode); switching mid-conversation; Romanized/native Hindi, Telugu, Tamil, Kannada; original text preserved; carriers get a structured English remark.
* **AI boundary** – `agent.LLMProvider` (mock shipped) only does conversation, intent extraction and messy-remark interpretation. `rules`/`domain` cannot import it. Low confidence → ask the buyer, never act.
* **Authorization** – approvals/manual actions/rule edits are role-gated server-side; the frontend never decides what is allowed.
* **Observability** – JSON logs with request/correlation/order/shipment/case/carrier ids; `/api/metrics`.

## Testing
```bash
go test ./... -count=1                 # unit tests; integration tests auto-skip without PostgreSQL
make test-integration                  # starts Postgres via Docker, runs tests/ (needs Docker)
TEST_DATABASE_URL=postgres://… go test ./tests/ -v      # or point at your own database
cd apps/web && npm test                # frontend unit tests (vitest) ; npm run build = typecheck + bundle
```
* Unit: domain (transitions, validation, sorting, cache key), carrier request mapping/normalization/malformed/timeout/500, rate aggregator + miniredis (miss/hit/expiry/refresh/partial TTL/Redis down/single-flight), rules engine (every outcome), mock LLM (languages, dates, times, intents), mock carriers.
* Integration/E2E (`tests/`, real HTTP everywhere including carrier→Zippy webhooks): orders, rates, cache, selection tampering/expiry, shipment per carrier, webhooks (duplicates, regressions, unknown tracking, signatures), and **all NDR use cases UC1–UC9**, approvals RBAC, carrier rejection/outage, the full demo scenario (`TestUC1…`).

## Known limitations
See [docs/assumptions.md](docs/assumptions.md): mock keyword NLU, header-based roles, per-instance single-flight and case locks, simulated payment confirmation, in-memory mock-carrier state, float money.

## Production improvements
Real identity (OIDC) and per-merchant tenancy; outbox + queue for webhooks/NDR actions; Redis distributed lock; `pg_advisory_xact_lock` per case; real LLM + WhatsApp/IVR/SMS providers behind the existing interfaces; payment gateway verification; OpenTelemetry + Prometheus; webhook timestamp replay window; per-merchant negotiated rates in the cache key; carrier circuit breakers; partitioned `shipment_events`; pagination; CI with the Docker-based integration suite.
