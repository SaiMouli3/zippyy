"""Voice simulator: runs the multilingual conversation engine against the customer's scripted side of the call
and posts the result as a signed callback."""
import json
from datetime import timedelta

from app.platform import clock, jobs, policies
from app.platform.simulation import profiles
from app.platform.voice_engine import CallScript, ConversationEngine

PAISE_PER_MINUTE = 300  # ₹3/min, Sarvam's published starting price; used only for simulated cost figures


def after_place(db, merchant, customer, call) -> None:
    jobs.enqueue(db, "sim_voice_run", {"call_id": call.id}, merchant_id=merchant.id,
                 run_at=clock.now() + timedelta(seconds=25))


def handle_run(db, job) -> None:
    from app.platform.customers import first_name
    from app.platform.ingest import ingest_webhook
    from app.platform.models import Customer, Merchant, Order, Shipment, VoiceCall
    from app.platform.providers.voice import SimulatedVoice
    from app.platform.contact_guard import local_now

    call = db.get(VoiceCall, job.payload["call_id"])
    if call is None or call.status not in ("initiated", "ringing"):
        return
    merchant = db.get(Merchant, call.merchant_id)
    customer = db.get(Customer, call.customer_id)
    shipment = db.get(Shipment, call.shipment_id)
    order = db.get(Order, shipment.order_id)
    key = "predelivery_calls" if call.purpose == "pre_delivery" else "voice_calls"
    script = profiles.consume(db, customer.id, key) or {"answer": "no_answer"}
    answer = script.get("answer", "answered")
    base = {"provider_call_id": call.provider_call_id, "occurred_at": clock.now().isoformat()}
    if answer in ("no_answer", "busy", "failed"):
        payload = {**base, "status": answer, "event_id": f"{call.provider_call_id}:{answer}",
                   "failure_reason": "network error" if answer == "failed" else None}
    else:
        _, cfg = policies.agent_config(db, merchant.id)
        engine = ConversationEngine(list(cfg.voice_languages), cfg.language_switch_confidence, cfg.max_clarifications)
        outcome = engine.run(CallScript(script.get("turns", [])), call.start_language or "en", call.purpose
                             if call.purpose != "callback" else "ndr_recovery", local_now(merchant).date(),
                             {"name": first_name(customer), "brand": merchant.brand_name,
                              "order": order.code or order.merchant_order_id})
        payload = {**base, "status": "completed", "event_id": f"{call.provider_call_id}:completed",
                   "duration_seconds": outcome.duration_seconds, "start_language": outcome.start_language,
                   "final_language": outcome.final_language, "final_variables": outcome.final_variables(),
                   "cost_paise": max(1, (outcome.duration_seconds + 59) // 60) * PAISE_PER_MINUTE,
                   "turns": [t.__dict__ for t in outcome.turns]}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ingest_webhook(db, "voice:simulator", SimulatedVoice.sign(raw), raw, {})
