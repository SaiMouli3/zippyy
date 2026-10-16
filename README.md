# Zippyy — multilingual delivery & NDR autonomy

Zippyy runs delivery recovery for Indian D2C brands. Before an attempt, it asks customers whether they will be available.
After a failed attempt (NDR), it contacts them on WhatsApp and by voice, in their language. It turns their answer into
a carrier request, but only if the merchant's deterministic policy allows it. Operators work the exceptions in a web
console that follows the zippyy.ai design system.

```
 Carriers ──webhooks──► Webhook inbox ──► Tracking ──► NDR case ──► Agent task ─┐
 Meta WhatsApp ─────────►   (dedupe,       (state       (read      (durable,     │
 Sarvam voice ──────────►   quarantine)     machine)     model)     timers)      │
                                                                                 ▼
          ┌──────── Workflows: NDR recovery · Pre-delivery confirmation ───────────┐
          │ typed tools only ─► contact guard ─► providers (WhatsApp, Sarvam voice) │
          │ intent extraction (rules / Sarvam LLM, schema-validated)               │
          │ policy engine R01–R14 (deterministic) ─► carrier action ─► reconcile   │
          │ escalation inbox for anything that needs a person                      │
          └────────────────────────────────────────────────────────────────────────┘
 Postgres (RLS per merchant) · job queue (SKIP LOCKED) · transactional outbox ─► SSE ─► Next.js console
```

## What is in this repository

| Path | What it is |
|---|---|
| `backend/app/platform/` | The platform: tenancy, auth, policy, agents, providers, event processing, v1 API |
| `backend/app/platform/workflows/` | `ndr_recovery_agent` and `delivery_readiness_agent` on a durable workflow engine |
| `backend/app/platform/api/` | v1 REST API (68 routes) and the server-sent event stream |
| `backend/migrations/` | Alembic: `0001` MVP baseline, `0002` platform schema, `0003` row-level security and app role |
| `backend/app/carriers`, `app/mock_carriers` | Carrier adapters (tracking + NDR actions) and three mock carriers with distinct APIs |
| `frontend/app/(platform)/` | Operator console: 14 sections, from Overview to Settings |
| `frontend/app/site/` | Marketing page built from `docs/zippyy-design-system.md` |
| `docs/` | Design system extracted from zippyy.ai, and the original MVP sandbox notes |

## Run it

### Docker (single host)

```bash
cp .env.example .env                       # defaults work locally; set secrets for anything shared
docker compose up --build                  # postgres, redis, migrate (one-shot), backend, worker, frontend
docker compose --profile demo run --rm seed   # optional: fictional demo workspaces, prints a password once
```

Open http://localhost:3000. Scale workers with `docker compose up --scale worker=3`; jobs are claimed with
`FOR UPDATE SKIP LOCKED` leases, so workers never double-process.

### Without Docker

```bash
# backend (Python 3.12, Postgres 16, Redis 7)
cd backend && pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://zippy:zippy@localhost:5432/zippy REDIS_URL=redis://localhost:6379/0
alembic upgrade head
DEMO_PASSWORD='choose-a-local-password' python -m app.platform.seed --demo   # optional
uvicorn app.main:app --port 8000 &
python -m app.platform.worker &

# frontend (Node 20)
cd frontend && npm ci
BACKEND_URL=http://localhost:8000 npm run build && BACKEND_URL=http://localhost:8000 node .next/standalone/server.js
# or for development: BACKEND_URL=http://localhost:8000 npm run dev
```

The browser only talks to the Next.js origin: `/api/v1/*` is proxied to `BACKEND_URL`, so session cookies stay
first-party and no CORS is needed.

## Security model

- **Tenancy.** Every tenant table has `FORCE ROW LEVEL SECURITY` keyed on `app.merchant_id`, which is set per
  transaction from the authenticated session (never from a request body or query). The app connects as the
  non-owner `zippy_app` role, and audit and event tables are append-only for that role. A case from another
  workspace returns 404.
- **Authentication.** Browser sessions use an httpOnly `zpy_session` cookie; only its SHA-256 is stored, with an
  absolute TTL, an idle timeout and revocation. CSRF uses a signed double-submit token in `X-CSRF-Token`. Passwords
  use scrypt, with lockout after repeated failures and per-IP and per-email rate limits. API keys
  (`zpy_live_…`, sent as `Authorization: Bearer`) are hashed, scoped, expiring and revocable.
- **Roles.** `owner`, `ops_lead`, `ops`, `finance` and `viewer` map to explicit permissions. The UI hides what a role
  cannot do, and the API enforces it regardless.
- **PII.** Phone, email and address are encrypted at rest (AES-256-GCM). Phone lookups use an HMAC. Values are masked
  everywhere by default; revealing them requires the `pii.unmask` permission and a reason, and is audited.
  Transcript views are audited too. Retention windows hide old message bodies and transcripts.
- **HTTP.** Request IDs, a 1 MB body limit, CSP and security headers on both apps, and error messages that never echo
  input. Logs are JSON with PII redaction.
- **Production guard.** `APP_ENV=production` refuses to start with development secrets or insecure cookies.

## How decisions are made

1. **Signals.** Carrier, WhatsApp and Sarvam webhooks land in `webhook_inbox`, de-duplicated by provider event ID
   and signature-checked. Anything unparseable, unknown or an illegal status transition goes to `webhook_quarantine`
   rather than being applied.
2. **Workflows.** A failed attempt opens or updates an NDR case and wakes its `agent_task`. The workflow then acts
   only through the typed tool registry (`tools.py`, version `2026-10.1`). Reading tools:
   - `get_shipment_status`
   - `get_order_details`
   - `get_delivery_attempt_history`
   - `get_customer_preferences`
   - `get_allowed_delivery_options`
   - `get_message_status`, `get_voice_call_status`
   - `get_conversation_history`
   - `get_carrier_action_status`
   - `get_ndr_sla_status`

   Writing tools:
   - `save_delivery_preference`
   - `send_whatsapp_template`, `send_whatsapp_reply`
   - `schedule_voice_call`
   - `request_reattempt`, `request_reschedule`, `request_address_change`
   - `schedule_followup`, `cancel_obsolete_followup`
   - `create_escalation`
   - `record_customer_opt_out`

   Every call is recorded as an agent run step with sanitized input and output. Private model reasoning is never
   stored.
3. **Contact guard.** Every message or call is checked against:
   - opt-outs and consent evidence
   - quiet hours and the voice window, in the workspace timezone
   - per-customer and per-workspace caps (replies and confirmations are exempt)
   - concurrent calls and the daily voice budget
4. **Understanding replies.** A multilingual rule extractor (Hindi, Telugu, Tamil, Kannada, English, romanized and
   code-mixed) is used by default, with prompt-injection guards. Optionally, Sarvam chat completions with JSON-schema
   output can be used instead, falling back to the rules on any failure. Language is detected per turn, with
   hysteresis before switching.
5. **Policy engine.** Rules `R01`–`R14` are deterministic and versioned (`rules-2026.10.1`). The language model
   proposes; the engine returns `ALLOWED`, `REQUIRES_APPROVAL` or `DENIED`, with the rules that fired. Carrier tools
   refuse to run without an allowed or operator-approved decision. RTO, cancellation, address and phone changes
   always need a person.
6. **Carrier actions.** Each action carries an idempotency key. If a timeout leaves the outcome unknown, the platform
   reconciles by asking the carrier for its status before it ever resubmits. A case shows *Carrier requested* until
   the carrier confirms, and *Reattempt confirmed* only after it does.
7. **Operators.** Escalations carry the full context. Operators can approve or reject a pending action, correct a
   preference, send the escalation to a supervisor, restart contact or resolve it. Each of these needs a reason, and
   each is audited.
8. **Live UI.** Every state change writes an outbox event. `/api/v1/events/stream` serves them as SSE with
   `Last-Event-ID` resume, a heartbeat every 15 s and a `resync` event if a client falls too far behind. The console
   shows **Live** only while heartbeats arrive; otherwise it says *Reconnecting* or *Offline* and polls every 30 s.

## Providers

| Integration | Live | Simulated (demo workspaces always use these) |
|---|---|---|
| WhatsApp | Meta Cloud API; inbound verified with `X-Hub-Signature-256`; webhook `GET/POST /api/v1/providers/whatsapp/meta` | Signed simulator replies through the same ingestion path |
| Voice | Sarvam hosted voice agent, instant outbound; callback `POST /api/v1/providers/voice/sarvam?call=…&token=…` (per-call HMAC token, because Sarvam documents no webhook signature) | In-house conversation engine with scripted fictional customers |
| Language & intent | Sarvam `/text-lid`, speech-to-text (`saaras`), text-to-speech (`bulbul:v3`), chat (`sarvam-105b`) | Heuristic script and lexicon detector, rule extractor |
| Carriers | Adapters per carrier; webhooks `POST /api/webhooks/{fastship,quickexpress,reliable}` with `X-Carrier-Signature` | Mock carriers with behaviour controls (accept, reject, timeout-then-accept, pending, server error) |

Demo data is fictional: `.test` email domains, generated `+91 90000 xxxxx` numbers, `DEMO` in every AWB, and "(Demo)" in every workspace name.
A demo workspace cannot be switched to a live provider.

## Tests

```bash
cd backend && pytest -q                                   # unit + API + workflow tests on SQLite
TEST_POSTGRES_URL=postgresql+psycopg://… pytest -q tests/platform/test_postgres.py   # RLS & SKIP LOCKED on real Postgres
cd frontend && npx tsc --noEmit && npm run build
E2E_PASSWORD=<demo password> node frontend/e2e/smoke.cjs    # browser smoke test against a seeded local stack
```

Automated tests never contact real customers. Providers are simulators or mocked HTTP transports.

## Environment

Every variable is listed and explained in [`.env.example`](.env.example). The minimum for production:

- `SECRET_KEY`, `PII_ENCRYPTION_KEY`, `PII_HASH_KEY`, `VOICE_WEBHOOK_SECRET`
- `SESSION_COOKIE_SECURE=true`, `CARRIER_WEBHOOK_SIGNATURE_REQUIRED=true` with per-carrier secrets
- `LEGACY_SANDBOX_ENABLED=false`, `ALLOW_DEMO_SEED=false`
- the Meta and Sarvam credentials, with `ZIPPY_PUBLIC_URL` set to the public HTTPS origin of the API

## Known limits

- **Live providers are untested.** The Meta and Sarvam integrations follow their published APIs but have not been run
  against live accounts from this repository. Message templates must be approved in Meta Business Manager under the
  same names, and the Sarvam app must be configured to accept the variables Zippyy sends.
- **Carriers are mocks.** The three carriers are mocks. Real carrier adapters need each carrier's NDR API contract.
- **Intent accuracy is not measured.** The analytics shows clarification rates instead; accuracy needs
  human-labelled conversations.
- **Vercel previews fail.** They fail until the Vercel project uses Framework Preset **Next.js** with Root Directory
  **`frontend`**. The frontend also needs a reachable backend (`BACKEND_URL` at build time).
