"""WhatsApp simulator: status callbacks and scripted customer replies, in Meta Cloud API webhook format."""
from datetime import timedelta

from app.platform import clock, jobs
from app.platform.simulation import profiles

# Default behaviour when a customer has no profile: delivered and read, no reply.
DEFAULT_DELIVERY = "read"


def after_send(db, merchant, customer, msg) -> None:
    prof = profiles.for_customer(db, customer.id)
    delivery = prof.get("whatsapp_delivery", DEFAULT_DELIVERY)  # read | delivered | sent | failed
    t = clock.now()
    steps = {"failed": ["sent", "failed"], "sent": ["sent"], "delivered": ["sent", "delivered"],
             "read": ["sent", "delivered", "read"]}[delivery]
    for i, status in enumerate(steps):
        jobs.enqueue(db, "sim_whatsapp_status", {"provider_message_id": msg.provider_message_id, "status": status,
                                                 "to": customer.phone_last4},
                     merchant_id=merchant.id, run_at=t + timedelta(seconds=20 + 40 * i))
    if delivery == "failed" or msg.direction != "outbound":
        return
    if msg.template_code in ("reattempt_confirmed", "reattempt_not_possible", "followup_no_reply") and not prof.get("reply_to_followup"):
        return
    if msg.template_id is None:  # our own session replies do not trigger another scripted reply
        return
    key = "predelivery_replies" if msg.template_code == "predelivery_availability" else "whatsapp_replies"
    reply = profiles.consume(db, customer.id, key)
    if reply is None:
        return
    after = int(reply.get("after_minutes", 12)) if isinstance(reply, dict) else 12
    text = reply.get("text") if isinstance(reply, dict) else str(reply)
    jobs.enqueue(db, "sim_whatsapp_inbound", {"customer_id": customer.id, "text": text,
                                              "follow_ups": reply.get("then", []) if isinstance(reply, dict) else []},
                 merchant_id=merchant.id, run_at=t + timedelta(minutes=after))


def _deliver(db, payload: dict) -> None:
    from app.platform.ingest import ingest_webhook
    from app.platform.providers.whatsapp import SimulatedWhatsApp
    raw, headers = SimulatedWhatsApp().sign(payload)
    ingest_webhook(db, "whatsapp:simulator", headers, raw, {})


def handle_status(db, job) -> None:
    p = job.payload
    ts = int(clock.now().timestamp())
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "sim-waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "statuses": [{
            "id": p["provider_message_id"], "status": p["status"], "timestamp": str(ts), "recipient_id": "91xxxxxx" + p.get("to", ""),
            **({"errors": [{"code": 131026, "title": "Message undeliverable"}]} if p["status"] == "failed" else {}),
        }]}}]}]}
    _deliver(db, payload)


def handle_inbound(db, job) -> None:
    from app.platform.customers import phone_e164
    from app.platform.ids import new_id
    from app.platform.models import Customer
    p = job.payload
    customer = db.get(Customer, p["customer_id"])
    ts = int(clock.now().timestamp())
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "sim-waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "contacts": [{"wa_id": phone_e164(customer).lstrip("+")}],
        "messages": [{"from": phone_e164(customer).lstrip("+"), "id": f"sim.wamid.in.{new_id()}", "timestamp": str(ts),
                      "type": "text", "text": {"body": p["text"]}}]}}]}]}
    _deliver(db, payload)
    for i, follow in enumerate(p.get("follow_ups") or []):
        jobs.enqueue(db, "sim_whatsapp_inbound", {"customer_id": customer.id, "text": follow["text"], "follow_ups": []},
                     merchant_id=job.merchant_id, run_at=clock.now() + timedelta(minutes=int(follow.get("after_minutes", 5)) * (i + 1)))
