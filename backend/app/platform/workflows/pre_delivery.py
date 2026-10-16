"""Pre-delivery availability confirmation (one task per shipment per delivery cycle).

Out-for-delivery -> eligibility & consent -> language -> approved template -> wait for reply
  "available"              -> preference confirmed, task done (no carrier change)
  another day/time         -> policy -> carrier reschedule (if the carrier API supports it) -> confirm after the
                              carrier accepts; otherwise store as a note for the driver, without promising a slot
  refusal / address / etc. -> flagged for the operations team
no reply by the deadline   -> for COD orders, one voice call if allowed; otherwise stop quietly
Delivery, a failed attempt (NDR takes over) or RTO close the task, cancelling its timers.
"""
from datetime import timedelta

from sqlalchemy import select

from app.platform import clock, outbox
from app.platform.calls import CallBlocked
from app.platform.messaging import Blocked
from app.platform.models import CarrierAction, Conversation, DeliveryPreference, Message, VoiceCall
from app.platform.workflows.base import Workflow
from app.platform.workflows.engine import close_task


class PreDeliveryWorkflow(Workflow):
    agent_name = "delivery_readiness_agent"

    def handle(self, trigger: str, data: dict) -> None:
        {
            "start": self.on_start,
            "customer_reply": self.on_reply,
            "call_completed": self.on_call_completed,
            "carrier_response": self.on_carrier_response,
            "message_failed": self.on_message_failed,
            "timer:reply_deadline": self.on_deadline,
            "timer:contact_retry": self.on_start,
        }.get(trigger, self.unknown)(data)

    def unknown(self, data: dict) -> None:
        self.rec.note("note", "Trigger not used by the pre-delivery workflow", status="skipped")

    def done(self, reason: str, attention: bool = False) -> None:
        self.update_state(outcome=reason, needs_attention=attention)
        close_task(self.db, self.task, "completed", reason)
        if attention:
            outbox.emit(self.db, self.merchant.id, "agent_task", self.task.id, "predelivery.needs_attention",
                        {"shipmentId": self.shipment.id, "reason": reason})

    def on_start(self, data: dict) -> None:
        status = self.tools.call("get_shipment_status", "Confirm the parcel is out for delivery", shipment_id=self.shipment.id)
        if status.status != "OUT_FOR_DELIVERY":
            self.done(f"shipment is {status.status}")
            return
        prefs = self.tools.call("get_customer_preferences", "Check consent and earlier preferences", shipment_id=self.shipment.id)
        if prefs.opted_out:
            self.rec.note("note", "Customer opted out; no pre-delivery contact", status="cancelled")
            self.done("customer opted out")
            return
        lang = self.contact_language().language
        code = self.order.code or self.order.merchant_order_id
        try:
            self.tools.call("send_whatsapp_template", "Ask whether someone will be available today",
                            shipment_id=self.shipment.id, template_code="predelivery_availability", language=lang,
                            params=[self.customer.name.split()[0][:30], self.merchant.brand_name, code],
                            purpose="pre_delivery", idempotency_key=self.key("availability"))
        except Blocked as exc:
            self.rec.note("note", f"Not sent: {exc.reason.replace('_', ' ')}", status="cancelled", output={"blocked": exc.reason})
            if exc.retry_at and exc.retry_at < clock.now() + timedelta(hours=6):
                self.tools.call("schedule_followup", "Retry when the contact window opens", name="contact_retry", at=exc.retry_at)
                return
            self.done(f"not contacted: {exc.reason}")
            return
        at = clock.now() + timedelta(minutes=self.cfg.pre_delivery_reply_wait_minutes)
        self.tools.call("schedule_followup", "Wait for the customer's answer", name="reply_deadline", at=at)
        self.task.waiting_for = "customer_reply"
        self.next_action = f"Wait for reply until {self.local_dt(at):%H:%M}"

    def reply(self, key: str, conv_id: str | None, **fmt) -> None:
        if not conv_id:
            return
        try:
            self.tools.call("send_whatsapp_reply", f"Reply ({key.replace('_', ' ')})", conversation_id=conv_id, key=key,
                            language=self.state.get("language", "en"),
                            idempotency_key=self.key(f"reply:{key}:{self.rec.run.id[:8]}"), fmt=fmt)
        except Blocked as exc:
            self.rec.note("note", f"Reply not sent: {exc.reason}", status="cancelled")

    def on_reply(self, data: dict) -> None:
        msg = self.db.get(Message, data["message_id"])
        self.tools.call("cancel_obsolete_followup", "Customer answered", name="reply_deadline")
        self.record_message_language(msg)
        result, extraction = self.extract(msg.body, "pre_delivery", message=msg, expecting=self.state.get("expecting"))
        self.handle_intent(result, extraction, msg.conversation_id, "whatsapp")

    def handle_intent(self, result, extraction, conv_id, channel) -> None:
        if result.intent == "opt_out":
            from app.platform import audit, customers
            self.reply("opt_out_ack", conv_id)
            customers.record_opt_out(self.db, self.customer, "customer_message", audit.AGENT, f"pre-delivery {extraction.id}")
            self.done("customer opted out")
            return
        if result.intent == "available":
            self.tools.call("save_delivery_preference", "Customer confirmed they are available",
                            shipment_id=self.shipment.id, requested_date=self.today(), status="confirmed_available",
                            source_channel=channel, extraction_id=extraction.id, language=self.state.get("language"))
            self.reply("available_ack", conv_id)
            self.done("customer confirmed availability")
            return
        if result.clarification_needed:
            n = int(self.state.get("clarifications", 0)) + 1
            self.update_state(clarifications=n, expecting="date")
            if n > self.cfg.max_clarifications:
                self.done("could not understand the customer", attention=True)
                return
            self.reply("ask_date" if result.clarification_topic == "date" else "ask_again", conv_id)
            self.tools.call("schedule_followup", "Wait for the clarification", name="reply_deadline",
                            at=clock.now() + timedelta(minutes=self.cfg.pre_delivery_reply_wait_minutes))
            return
        if result.intent in ("reschedule", "reattempt_today", "cod_not_ready", "cod_ready"):
            decision, row = self.decide(result, extraction, "pre_delivery")
            if decision.verdict == "ALLOWED" and decision.action in ("reschedule", "reattempt"):
                self.tools.call("save_delivery_preference", "Save the requested slot", shipment_id=self.shipment.id,
                                requested_date=decision.requested_date, requested_window=result.requested_window,
                                status="carrier_pending", source_channel=channel, extraction_id=extraction.id,
                                language=self.state.get("language"))
                tool = "request_reschedule" if decision.action == "reschedule" else "request_reattempt"
                self.tools.call(tool, "Ask the carrier to deliver at the requested time", shipment_id=self.shipment.id,
                                decision_id=row.id)
                self.reply("preference_received", conv_id, date=self.fmt_date(decision.requested_date),
                           window=self.fmt_window(result.requested_window if decision.carrier_window_supported else None))
                self.task.waiting_for = "carrier_response"
                self.next_action = "Wait for the carrier"
                return
            self.tools.call("save_delivery_preference", "Carrier cannot change the slot; keep it as a note for the driver",
                            shipment_id=self.shipment.id, requested_date=result.requested_date,
                            requested_window=result.requested_window, status="noted", source_channel=channel,
                            extraction_id=extraction.id, language=self.state.get("language"))
            self.reply("preference_noted", conv_id, date=self.fmt_date(result.requested_date),
                       window=self.fmt_window(result.requested_window))
            self.done("preference noted (carrier cannot reschedule)", attention=decision.verdict == "REQUIRES_APPROVAL")
            return
        self.reply("under_review", conv_id)
        self.done(f"customer said '{result.intent}'; operations team to review", attention=True)

    def on_deadline(self, data: dict) -> None:
        if self.order.payment_type == "COD" and "voice" in self.cfg.channels:
            try:
                self.tools.call("schedule_voice_call", "No reply on a COD order; confirm availability by phone",
                                shipment_id=self.shipment.id, purpose="pre_delivery",
                                language=self.state.get("language", "en"), idempotency_key=self.key("call"))
                self.task.waiting_for = "call_result"
                return
            except CallBlocked as exc:
                self.rec.note("note", f"Call not placed: {exc.reason}", status="cancelled")
        self.done("no reply before the delivery window")

    def on_call_completed(self, data: dict) -> None:
        call = self.db.get(VoiceCall, data["call_id"])
        fv = data.get("final_variables") or {}
        if call.status != "completed" or not fv.get("intent"):
            self.done(f"call ended: {call.status}")
            return
        from app.platform.workflows.ndr_recovery import NdrRecoveryWorkflow
        result = NdrRecoveryWorkflow.intent_from_call(self, fv, call)
        if result is None:
            self.done("call gave no usable answer")
            return
        extraction = self.store_extraction(result, call=call)
        conv = self.db.scalars(select(Conversation).where(Conversation.shipment_id == self.shipment.id)).first()
        self.handle_intent(result, extraction, conv.id if conv else None, "voice")

    def on_carrier_response(self, data: dict) -> None:
        action = self.db.get(CarrierAction, data["action_id"])
        pref = self.db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == self.shipment.id)
                               .order_by(DeliveryPreference.created_at.desc())).first()
        if action.status == "accepted":
            if pref:
                pref.status, pref.carrier_confirmation_status = "carrier_confirmed", "accepted"
            try:
                self.tools.call("send_whatsapp_template", "Confirm the carrier-accepted slot", shipment_id=self.shipment.id,
                                template_code="reattempt_confirmed", language=self.state.get("language", "en"),
                                params=[self.order.code or self.order.merchant_order_id, self.shipment.carrier_code.title(),
                                        self.fmt_date(action.requested_date)],
                                purpose="confirmation", idempotency_key=self.key(f"confirm:{action.id}"))
            except Blocked:
                pass
            self.done("carrier confirmed the new slot")
            return
        if pref:
            pref.status, pref.carrier_confirmation_status = "carrier_rejected", action.status
        self.done(f"carrier {action.status} the reschedule", attention=True)

    def on_message_failed(self, data: dict) -> None:
        self.rec.note("note", "Pre-delivery message failed", status="failed", message_id=data.get("message_id"))
        self.done("message could not be delivered")
