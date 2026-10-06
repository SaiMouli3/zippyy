# Business rules

## Who owns what
Zippyy does **not** deliver parcels. The carrier owns the delivery executive, physical movement, delivery attempts, reattempt scheduling, the NDR reason and RTO.
Zippyy owns shipment data, the merchant and buyer relationship, tracking, NDR handling, seller rules, instructions sent to carriers and the audit trail.
Therefore the agent never promises a delivery. Buyer-facing language is split in two:

* after *submitting*: "We've submitted your request … to the carrier. We'll confirm as soon as the carrier accepts it."
* only after the carrier answered **ACCEPTED**: "The carrier has accepted the reattempt request for …"

This is enforced in state (`ACTION_SUBMITTED` → `CARRIER_ACCEPTED` → `REATTEMPT_SCHEDULED`), in code (the `accepted.*` templates are only rendered after acceptance), and in tests.

## Shipment status transitions
Lifecycle: `SHIPMENT_CREATED → PICKED_UP → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED`, plus `DELIVERY_FAILED` and `RTO`.

* Forward moves, including skips (lost intermediate webhooks), are applied.
* The same non-terminal state again with a new event is recorded in history without a state change.
* `DELIVERY_FAILED → OUT_FOR_DELIVERY | IN_TRANSIT | DELIVERED | RTO` (reattempt / hub return / direct delivery / return).
* `DELIVERED` and `RTO` are terminal.
* Everything else is a regression. **Chosen strategy: reject + quarantine** – HTTP 409 `INVALID_STATUS_TRANSITION`, the raw event is stored with `disposition=REJECTED_TRANSITION` for investigation, it never changes status or appears in customer-visible history.

## Webhook handling
HMAC-SHA256 over the raw body (`X-Carrier-Signature`), per-carrier secrets, fail-closed when required. Unknown tracking number → 404 and recorded in `webhook_inbox` (outcome `UNKNOWN_TRACKING`). Malformed → 400. Duplicate → 200.

## NDR reason taxonomy
`CUST_UNAVAILABLE, CUST_REFUSED, ADDRESS_ISSUE, PHONE_UNREACHABLE, COD_NOT_READY, FUTURE_DELIVERY, ACCESS_RESTRICTED, OUT_OF_AREA, SUSPECT_FALSE_ATTEMPT`.
Carrier codes are mapped in each adapter (FastShip `CONSIGNEE_UNAVAILABLE`, QuickExpress `NDR-01`, ReliableCourier `R-11`, …). Unknown/generic codes (`OTHER`) fall back to AI remark interpretation, recorded as `reason_source=LLM_REMARK`.

| Reason | Playbook |
|---|---|
| CUST_UNAVAILABLE | ask when to retry → reattempt |
| CUST_REFUSED | ask why; clear cancel → early RTO per seller policy |
| ADDRESS_ISSUE | collect landmark/address; same pincode+city agent-approved; new pincode seller; new city seller+ops |
| PHONE_UNREACHABLE | WhatsApp → IVR → SMS; if all fail alert seller for alternate number |
| COD_NOT_READY | ask readiness; offer prepaid if seller & carrier allow; or schedule reattempt |
| FUTURE_DELIVERY | check carrier hold window; offer nearest valid date |
| ACCESS_RESTRICTED | ask buyer to inform security; reattempt with instruction |
| OUT_OF_AREA | escalate to carrier/ops immediately |
| SUSPECT_FALSE_ATTEMPT | record buyer statement, request reattempt, draft ops dispute (never blames the carrier to the buyer) |

## Rules engine (`internal/rules`)
Input: structured intent, reason, attempt number, order facts, **live** seller rules, **live** carrier rules, clock (IST), confidence threshold, pending question. Output: outcome, plan, approvals, and every check (`rule`, `passed`, `detail`) which is written to the timeline and audit log.

| Decision | Outcome |
|---|---|
| reattempt same address / reschedule inside hold window / phone update / same-pincode correction | `AGENT_ALLOWED` |
| new pincode | `SELLER_APPROVAL` |
| new city | `SELLER_OPS_APPROVAL` (both roles must approve) |
| COD → prepaid | seller rule + carrier capability, else clarify |
| early RTO | seller policy `AUTO` / `APPROVAL` / `DISALLOWED` |
| false-attempt dispute | reattempt now (agent) + non-blocking `DISPUTE_DRAFT` for ops |
| seller max attempts reached | `EXTRA_ATTEMPT` seller approval |
| carrier max attempts reached / unsupported action / cannot change address | `ESCALATE` |
| requested date before cutoff-adjusted earliest date or beyond hold window | `OFFER_ALTERNATIVE` (nearest valid date, needs buyer YES) |
| COD above seller limit on attempt ≥ 2 | seller approval |
| confidence < threshold (0.75) or unknown | `NEEDS_CONFIRMATION` / `CLARIFY` – never acts |

Carrier constraints stored per carrier: max attempts, instruction cutoff (IST), hold window, supported actions, time-slot support, payment-mode/address/phone change.
Unsupported time-slot preferences are sent only as an *advisory* remark and the buyer is not promised a slot.

## No response
`BUYER_TIMEOUT` escalates channels (WhatsApp → IVR → SMS). When all are used: non-final attempt → default reattempt; **final attempt** (min of seller max/auto-RTO and carrier max) → seller alert + `FINAL_ATTEMPT_DECISION` approval. `SELLER_TIMEOUT` → seller `default_on_silence` (`RTO` → carrier RTO, `ESCALATE` → ops). A background sweeper fires these triggers using the seller's timeouts; the UI can fire them instantly.

## Language
`case.language` + `case.language_source` (`reply` > `stored` > `seller` > `pincode`). A buyer reply in another supported language switches the case, updates the buyer profile, is audited and all later messages use the new language. Original text is always preserved; the internal English interpretation is stored separately. Carriers only ever receive a structured **English** remark built from structured fields.

## AI vs deterministic
AI (`agent.LLMProvider`): conversation text, intent extraction, messy carrier-remark interpretation. Deterministic (no AI): status transitions, case state, permissions, seller/carrier rules, cutoff & hold-window checks, attempt counting, RTO decisions, idempotency, duplicate detection, quote validation.

## Roles & authorization (MVP)
`X-Zippy-Role: SELLER|OPS` identifies the actor (no login in the MVP). Approvals are decidable only by roles in `required_roles`; seller rules need SELLER, carrier rules need OPS; manual carrier actions need SELLER or OPS and still pass through the rules engine.
