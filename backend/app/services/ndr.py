from psycopg.types.json import Jsonb

from .. import db, rules
from ..ai.intent import extractor
from ..carriers.registry import BY_CODE
from ..util import ApiError

REASON_TEXT = {
    "CUSTOMER_UNAVAILABLE": "we couldn't reach you at the delivery address",
    "CUSTOMER_REFUSED": "the delivery was refused",
    "ADDRESS_ISSUE": "the delivery address looks incomplete or incorrect",
    "PHONE_UNREACHABLE": "the courier couldn't reach you by phone",
    "COD_NOT_READY": "the cash on delivery amount wasn't ready",
}
OPEN_STATUSES = ("OPEN", "NEEDS_APPROVAL", "ACTION_FAILED")  # rules still gate the action


def _msg(c, case_id: str, sender: str, text: str):
    c.execute("INSERT INTO conversation_messages(ndr_case_id, sender, message) VALUES (%s,%s,%s)",
              (case_id, sender, text))


def _case_row(c, case_id: str, lock: bool = False) -> dict:
    row = c.execute(
        f"""SELECT n.*, o.customer_name, o.phone, o.address, o.delivery_pincode, o.payment_mode, o.cod_amount,
                   s.carrier, s.service, s.tracking_number, s.status AS shipment_status
            FROM ndr_cases n JOIN orders o ON o.id=n.order_id JOIN shipments s ON s.id=n.shipment_id
            WHERE n.id=%s {'FOR UPDATE OF n' if lock else ''}""", (case_id,)).fetchone()
    if not row:
        raise ApiError(404, f"NDR case {case_id} not found")
    return row


def list_cases() -> list[dict]:
    with db.conn() as c:
        return c.execute(
            """SELECT n.id, n.order_id, n.reason, n.attempt_number, n.status, n.created_at,
                      o.customer_name, s.carrier, s.tracking_number
               FROM ndr_cases n JOIN orders o ON o.id=n.order_id JOIN shipments s ON s.id=n.shipment_id
               ORDER BY n.created_at DESC, n.id DESC""").fetchall()


def case_detail(case_id: str) -> dict:
    with db.conn() as c:
        row = _case_row(c, case_id)
        row["messages"] = c.execute(
            "SELECT id, sender, message, timestamp FROM conversation_messages WHERE ndr_case_id=%s ORDER BY id",
            (case_id,)).fetchall()
        row["actions"] = c.execute(
            "SELECT * FROM carrier_actions WHERE ndr_case_id=%s ORDER BY id", (case_id,)).fetchall()
        row["audit"] = c.execute(
            """SELECT event, details, created_at FROM audit_logs
               WHERE entity_type='ndr_case' AND entity_id=%s ORDER BY id""", (case_id,)).fetchall()
        return row


def contact_buyer(case_id: str) -> dict:
    with db.conn() as c:
        case = _case_row(c, case_id, lock=True)
        if c.execute("SELECT 1 FROM conversation_messages WHERE ndr_case_id=%s AND sender='AGENT'", (case_id,)).fetchone():
            return case_detail_after(case_id)
        first = case["customer_name"].split()[0]
        _msg(c, case_id, "AGENT",
             f"Hi {first}, your parcel could not be delivered today because {REASON_TEXT[case['reason']]}. "
             "Would you like us to attempt delivery again?")
        db.audit(c, "BUYER_CONTACTED", "ndr_case", case_id, {"channel": "WHATSAPP_SIMULATED"})
    return case_detail(case_id)


def case_detail_after(case_id):
    return case_detail(case_id)


def _agent_reply(decision: dict, intent: dict) -> str:
    when = " ".join(x for x in (intent.get("date"), f"({intent['time_window']})" if intent.get("time_window")
                                else intent.get("time")) if x)
    out = decision["outcome"]
    if out == rules.ALLOWED:
        return (f"Thanks! I've noted your request for {when or 'the next available slot'}. "
                "I'll check this with the carrier and update you once they respond.")
    if out == rules.REQUIRES_APPROVAL:
        return "Thanks for letting us know. This change needs approval from the seller, so I've passed it to our team. We'll update you shortly."
    if out == rules.NEEDS_CLARIFICATION:
        return "Sorry, I didn't quite get that. Would you like us to try delivering again? If so, which day and time suits you?"
    return "Thanks, I've passed your message to our team."


def buyer_message(case_id: str, text: str) -> dict:
    text = text.strip()
    if not text:
        raise ApiError(422, "Message is empty")
    with db.conn() as c:
        case = _case_row(c, case_id, lock=True)
        if case["status"] in ("ACTION_SUBMITTED", "CARRIER_ACCEPTED", "RESOLVED"):
            raise ApiError(409, f"Case is {case['status']}; no further buyer requests accepted")
        _msg(c, case_id, "BUYER", text)
        db.audit(c, "BUYER_MESSAGE_RECEIVED", "ndr_case", case_id, {"message": text})

        intent = extractor.extract(text).model_dump()
        db.audit(c, "INTENT_EXTRACTED", "ndr_case", case_id, intent)

        order = {"delivery_pincode": case["delivery_pincode"]}
        decision = rules.evaluate(intent, order).to_dict()
        status = "NEEDS_APPROVAL" if decision["outcome"] == rules.REQUIRES_APPROVAL else "OPEN"
        c.execute("""UPDATE ndr_cases SET last_intent=%s, last_decision=%s, status=%s, updated_at=now()
                     WHERE id=%s""", (Jsonb(intent), Jsonb(decision), status, case_id))
        _msg(c, case_id, "AGENT", _agent_reply(decision, intent))
    return case_detail(case_id)


def reattempt(case_id: str) -> dict:
    # --- 1. validate against *rules* (never trust a stored decision) and record submission
    with db.conn() as c:
        case = _case_row(c, case_id, lock=True)
        if case["status"] not in OPEN_STATUSES:
            raise ApiError(409, f"Case is {case['status']}; reattempt cannot be requested")
        if not case["last_intent"]:
            raise ApiError(409, "No buyer request on this case yet")
        decision = rules.evaluate(case["last_intent"], {"delivery_pincode": case["delivery_pincode"]})
        if decision.outcome != rules.ALLOWED:
            raise ApiError(409, "Rules engine does not allow an automatic reattempt",
                           decision=decision.to_dict())
        request = {"requestedDate": decision.requested_date, "window": decision.requested_window,
                   "attempt": case["attempt_number"], "tracking": case["tracking_number"]}
        action_id = c.execute(
            """INSERT INTO carrier_actions(ndr_case_id, action_type, status, request)
               VALUES (%s,'REATTEMPT','ACTION_SUBMITTED',%s) RETURNING id""", (case_id, Jsonb(request))).fetchone()["id"]
        c.execute("UPDATE ndr_cases SET status='ACTION_SUBMITTED', last_decision=%s, updated_at=now() WHERE id=%s",
                  (Jsonb(decision.to_dict()), case_id))
        # Safety rule: only claim what is true - the request is submitted, not confirmed.
        _msg(c, case_id, "AGENT", "Your reattempt request has been submitted to the carrier.")
        db.audit(c, "CARRIER_ACTION_SUBMITTED", "ndr_case", case_id, request)
        adapter = BY_CODE[case["carrier"]]

    # --- 2. call the carrier outside any transaction
    try:
        res = adapter.request_reattempt(case["tracking_number"], decision.requested_date,
                                        decision.requested_window, case["attempt_number"])
        accepted, resp = res.status == "ACCEPTED", {"status": res.status, "message": res.message, "raw": res.raw}
    except Exception as e:  # noqa: BLE001
        accepted, resp = False, {"status": "ERROR", "message": str(e)}

    # --- 3. only now may we tell the buyer anything about the outcome
    with db.conn() as c:
        if accepted:
            c.execute("UPDATE carrier_actions SET status='CARRIER_ACCEPTED', response=%s, updated_at=now() WHERE id=%s",
                      (Jsonb(resp), action_id))
            c.execute("UPDATE ndr_cases SET status='CARRIER_ACCEPTED', updated_at=now() WHERE id=%s", (case_id,))
            _msg(c, case_id, "AGENT", "The carrier has accepted the reattempt request.")
            db.audit(c, "CARRIER_ACTION_ACCEPTED", "ndr_case", case_id, resp)
            c.execute("UPDATE ndr_cases SET status='RESOLVED', resolved_at=now(), updated_at=now() WHERE id=%s", (case_id,))
        else:
            c.execute("UPDATE carrier_actions SET status='REJECTED', response=%s, updated_at=now() WHERE id=%s",
                      (Jsonb(resp), action_id))
            c.execute("UPDATE ndr_cases SET status='ACTION_FAILED', updated_at=now() WHERE id=%s", (case_id,))
            _msg(c, case_id, "AGENT", "The carrier could not confirm the reattempt yet. Our team will follow up with you.")
            db.audit(c, "CARRIER_ACTION_REJECTED", "ndr_case", case_id, resp)
    return case_detail(case_id)
