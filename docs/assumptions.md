# Assumptions, trade-offs and unfinished items

## Source documents
* The coding-assignment document was read in full. The second document ("NDR Agent — Business Flow & Functional Overview") was **not** attached to this session; its requirements were taken from the detailed product brief supplied in the task (taxonomy, state names, use cases UC1–UC9, rule outcomes, AI boundaries). Where the brief was silent the simplest reasonable choice was made and is listed here.

## Product assumptions
1. **Time zone** – cutoffs, communication hours and "tomorrow" use IST (fixed +05:30, no tzdata dependency).
2. **Instruction cutoff** – an instruction received after the carrier's daily cutoff cannot affect the next day's attempt, so the earliest actionable date moves one day. Seeds: FastShip 23:59 (so the demo works at any hour), QuickExpress 22:00, ReliableCourier 20:00.
3. **COD limit** – interpreted as: COD above the seller limit needs seller approval for attempt ≥ 2.
4. **Attempt counting** – `attempt_number` = number of NDR events for the shipment. "Final attempt" = attempt ≥ min(seller max, seller auto-RTO attempt, carrier max).
5. **Default on buyer silence** – non-final: plain reattempt; final: seller decision, then seller default (`RTO`/`ESCALATE`).
6. **Prepaid conversion** – payment is *simulated*: a mock payment link is generated and "PAID" typed by the buyer stands in for a gateway callback. A real gateway verification must replace this before production.
7. **Carrier NDR payloads** – the assignment defines status codes but not NDR reason fields. Each mock carrier adds a reason block in its own style (FastShip `ndr_reason`, QuickExpress `ndrDetails.code`, ReliableCourier `failure.reasonCode`).
8. **Carrier action APIs** – the brief names endpoints loosely; each mock carrier exposes its own action contract (documented in the adapters and mock). Action decisions are synchronous (`ACCEPTED`/`REJECTED`).
9. **Reliable returns two services** (RC-SURFACE, RC-AIR) exactly as the contract sample, so the option list has four rows; the assignment's example table shows three.
10. **Cancellation** – a clear "cancel" is acted on (approval per seller policy); a vague refusal first asks the reason.
11. **Order language** – optional `language` on order creation represents the "seller order language".
12. **Seeded demo data** – `MERCHANT-09001..09003` are seeded (OFD / delivered / in transit); `MERCHANT-10001` is intentionally left free for the evaluator.
13. **Unlocalized messages** – three rarely used buyer messages (`clarify.prepaid_unavailable`, `clarify.rto_unavailable`, `ack.thanks`) fall back to English; everything on the main flow is localized in en/hi/te/ta/kn.

## Trade-offs
* **Mock LLM** is deterministic keyword/regex NLU (English + Romanized/native Hindi, Telugu, Tamil, Kannada). It is convincing on the demo phrases, not a general NLU. The `LLMProvider` interface is where a real model plugs in; the deterministic core is unaffected.
* **Auth** – role header, no login/JWT. Fine for a demo; production needs real identity.
* **Single-flight is per instance**; cross-instance stampedes would need a Redis lock.
* **Per-case mutex is in-process**; multiple API replicas should use `pg_advisory_xact_lock` per case.
* **Carrier call inside the shipment transaction** holds the order row lock for the carrier timeout; an orphaned booking is possible if the DB commit fails after the carrier accepted (needs an outbox/reconciliation job).
* **Webhook ordering** relies on the state machine, not event timestamps; history is ordered by receipt time.
* **Money** is `float64` rounded to 2 dp with paisa-exact comparison; a decimal type would be preferable at scale.
* **In-memory mock-carrier state**; restarting the mock loses its bookings (Zippy passes enough context for control triggers to keep working).

## Not done / future
Webhook replay protection by timestamp window, real queues/outbox, OpenTelemetry, merchant login, per-merchant negotiated rates, Postman collection, load tests, real WhatsApp/IVR/SMS providers, pagination on list endpoints, e2e browser tests in CI.
