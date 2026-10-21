"""NDR recovery workflow (one task per shipment per failed delivery cycle).

start -> investigate -> contact (WhatsApp, else voice) -> wait
customer_reply / call_completed -> extract intent -> (clarify | policy decision)
  ALLOWED            -> save preference, request carrier action, tell the customer it was *requested*
  REQUIRES_APPROVAL  -> escalate with the pending decision
  DENIED             -> offer the permitted alternative or escalate
carrier_response accepted -> confirm to the customer (only now), wait for the next attempt
carrier_response rejected/failed -> tell the customer honestly, escalate
timers: no reply -> bounded voice attempts -> one follow-up -> escalate / close per policy
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.platform import clock, i18n, intent as intent_svc
from app.platform.calls import CallBlocked
from app.platform.contact_guard import next_allowed_time
from app.platform.messaging import Blocked
from app.platform.models import CarrierAction, Conversation, Message, RuleDecision, VoiceCall
from app.platform.workflows.base import Workflow
from app.platform.workflows.engine import close_task

REASON_TEMPLATE = {
    "customer_unavailable": "ndr_customer_unavailable",
    "address_issue": "ndr_address_issue",
    "cod_not_ready": "ndr_cod_not_ready",
    "customer_refused": "ndr_customer_refused",
    "phone_unreachable": "ndr_generic",
    "other": "ndr_generic",
}


class NdrRecoveryWorkflow(Workflow):
    agent_name = "ndr_recovery_agent"

    def handle(self, trigger: str, data: dict) -> None:
        handler = {
            "start": self.on_start,
            "customer_reply": self.on_customer_reply,
            "call_completed": self.on_call_completed,
            "carrier_response": self.on_carrier_response,
            "message_failed": self.on_message_failed,
            "operator_decision": self.on_operator_decision,
            "operator_retry": self.on_start,
            "timer:no_reply": self.on_no_reply,
            "timer:contact_retry": self.on_start,
            "timer:call_retry": self.on_call_retry,
            "timer:delivery_check": self.on_delivery_check,
        }.get(trigger)
        if handler is None:
            self.rec.note("note", f"No handler for trigger '{trigger}'", status="skipped")
            return
        handler(data)

    # ------------------------------------------------------------ start / contact
    def on_start(self, data: dict) -> None:
        t = self.tools
        sid = self.shipment.id
        status = t.call("get_shipment_status", "Confirm the shipment is still undelivered", shipment_id=sid)
        if status.status != "DELIVERY_FAILED":
            close_task(self.db, self.task, "completed", f"shipment is {status.status}; nothing to recover")
            self.rec.note("note", f"Shipment is {status.status}; workflow closed", status="cancelled")
            return
        attempts = t.call("get_delivery_attempt_history", "Review previous delivery attempts", shipment_id=sid)
        prefs = t.call("get_customer_preferences", "Check language, consent and earlier preferences", shipment_id=sid)
        options = t.call("get_allowed_delivery_options", "Check what the carrier API supports", shipment_id=sid)
        history = t.call("get_conversation_history", "Look for earlier contact on this shipment", shipment_id=sid, limit=10)
        sla = t.call("get_ndr_sla_status", "Check the SLA deadline")
        self.rec.note("investigate", "Investigation summary", output={
            "reason": self.case.reason, "carrierReason": self.case.carrier_reason, "attempts": len(attempts.attempts),
            "optedOut": prefs.opted_out, "carrierCapabilities": sorted(options.capabilities),
            "earlierMessages": len(history.messages), "earlierCalls": len(history.calls),
            "slaMinutesLeft": sla.minutes_left})
        if prefs.opted_out:
            self.escalate("contact_restricted", "medium",
                          "Customer has opted out of automated contact. An operator must decide how to recover this "
                          f"delivery ({self.case.reason.replace('_', ' ')}).")
            return
        if self.shipment.attempt_count >= self.cfg.max_attempts_before_rto:
            self.decide_rto("Maximum delivery attempts reached")
            return
        self.contact_language()
        self.set_case_status("contacting", self.strategy())
        self.first_contact()

    def strategy(self) -> str:
        return {"customer_unavailable": "reschedule_with_customer", "address_issue": "verify_address",
                "cod_not_ready": "confirm_cod_readiness", "customer_refused": "confirm_refusal",
                "phone_unreachable": "reach_customer"}.get(self.case.reason, "reach_customer")

    def first_contact(self) -> None:
        lang = self.state["language"]
        if "whatsapp" in self.cfg.channels:
            sent = self.send_template(REASON_TEMPLATE.get(self.case.reason, "ndr_generic"), lang, "ndr_initial")
            if sent:
                wait = timedelta(minutes=self.cfg.whatsapp_reply_wait_minutes)
                self.tools.call("schedule_followup", "Wait for the customer's reply", name="no_reply", at=clock.now() + wait)
                self.task.waiting_for = "customer_reply"
                self.set_case_status("awaiting_customer")
                self.next_action = f"Wait for reply; voice call if none by {self.local_dt(clock.now() + wait):%d %b %H:%M}"
                return
            if self.state.get("blocked_retry_at"):
                return  # quiet hours etc.: contact_retry timer set by send_template
        self.try_voice("ndr_recovery", "first contact by voice")

    def send_template(self, code: str, lang: str, key: str, extra: list[str] | None = None,
                      purpose: str = "ndr_recovery") -> bool:
        params = [self.customer.name.split()[0][:30], self.merchant.brand_name, self.order.code or self.order.merchant_order_id]
        if code == "ndr_cod_not_ready":
            params.append(f"{float(self.order.cod_amount or 0):,.0f}")
        if extra is not None:
            params = extra
        try:
            self.tools.call("send_whatsapp_template", f"Send '{code}' on WhatsApp", shipment_id=self.shipment.id,
                            template_code=code, language=lang, params=params, purpose=purpose,
                            idempotency_key=self.key(key))
            self.update_state(blocked_retry_at=None)
            return True
        except Blocked as exc:
            self.rec.note("note", f"WhatsApp not sent: {exc.reason.replace('_', ' ')}", status="cancelled",
                          policy_rule=exc.reason[:80], output={"blocked": exc.reason})
            if exc.retry_at:
                self.update_state(blocked_retry_at=exc.retry_at.isoformat())
                self.tools.call("schedule_followup", "Retry contact when the contact window opens",
                                name="contact_retry", at=exc.retry_at)
                self.next_action = f"Contact after {self.local_dt(exc.retry_at):%d %b %H:%M} (contact window)"
            return False

    def reply(self, key: str, conv_id: str | None, **fmt) -> None:
        if not conv_id:
            return
        try:
            self.tools.call("send_whatsapp_reply", f"Reply to the customer ({key.replace('_', ' ')})",
                            conversation_id=conv_id, key=key, language=self.state.get("language", "en"),
                            idempotency_key=self.key(f"reply:{key}:{self.rec.run.id[:8]}"), fmt=fmt)
        except Blocked as exc:
            self.rec.note("note", f"Reply not sent: {exc.reason.replace('_', ' ')}", status="cancelled",
                          output={"blocked": exc.reason})

    def try_voice(self, purpose: str, why: str, at: datetime | None = None) -> bool:
        if "voice" not in self.cfg.channels:
            self.escalate("no_contact_channel", "high", "Voice is disabled and WhatsApp could not be used.")
            return False
        calls_done = len(list(self.db.scalars(select(VoiceCall.id).where(VoiceCall.ndr_case_id == self.case.id))))
        if calls_done >= self.cfg.max_voice_attempts_per_case:
            return self.after_contact_exhausted()
        try:
            self.tools.call("schedule_voice_call", f"Call the customer ({why})", shipment_id=self.shipment.id,
                            purpose=purpose, language=self.state.get("language", "en"), at=at,
                            idempotency_key=self.key(f"call:{calls_done + 1}"))
        except CallBlocked as exc:
            self.rec.note("note", f"Call not placed: {exc.reason.replace('_', ' ')}", status="cancelled",
                          policy_rule=exc.reason[:80], output={"blocked": exc.reason})
            if exc.retry_at and exc.reason in ("outside_voice_window", "quiet_hours", "concurrent_call_limit"):
                self.tools.call("schedule_followup", "Retry the call when allowed", name="call_retry", at=exc.retry_at)
                self.next_action = f"Call after {self.local_dt(exc.retry_at):%d %b %H:%M}"
                return False
            return self.after_contact_exhausted(blocked_reason=exc.reason)
        self.task.waiting_for = "call_result"
        self.set_case_status("contacting")
        self.next_action = "Wait for the call result"
        return True

    def after_contact_exhausted(self, blocked_reason: str | None = None) -> bool:
        if not self.state.get("followup_sent") and "whatsapp" in self.cfg.channels:
            if self.send_template("followup_no_reply", self.state.get("language", "en"), "followup"):
                self.update_state(followup_sent=True)
                self.tools.call("schedule_followup", "Last wait before escalating", name="no_reply",
                                at=clock.now() + timedelta(hours=4))
                self.task.waiting_for = "customer_reply"
                self.next_action = "Wait for a reply to the follow-up"
                return False
        why = f"contact blocked ({blocked_reason.replace('_', ' ')})" if blocked_reason else "no response after all permitted contact attempts"
        if self.cfg.no_response_close_policy == "close_after_sla" and self.case and clock.now() > clock.as_utc(self.case.sla_due_at):
            from app.platform import audit, ndr
            ndr.resolve_case(self.db, self.case, "no_response", audit.AGENT, why)
            close_task(self.db, self.task, "completed", why)
            return False
        self.escalate("no_response", "high", f"Customer could not be reached: {why}.")
        return False

    # ------------------------------------------------------------ customer reply
    def on_customer_reply(self, data: dict) -> None:
        msg = self.db.get(Message, data["message_id"])
        if msg is None:
            return
        self.tools.call("cancel_obsolete_followup", "Customer replied; cancel the no-reply follow-up", name="no_reply")
        self.record_message_language(msg)
        expecting = self.state.get("expecting")
        result, extraction = self.extract(msg.body, "ndr_recovery", message=msg, expecting=expecting)
        self.act_on_intent(result, extraction, msg.conversation_id, "whatsapp")

    def act_on_intent(self, result, extraction, conv_id: str | None, channel: str) -> None:
        if result.validation_status == "invalid" and result.intent == "other":
            self.escalate("suspicious_message", "high", "Customer message tried to change instructions or ask for "
                          "other data. Not acted on; please review.", )
            return
        if result.intent == "opt_out":
            self.reply("opt_out_ack", conv_id)
            self.tools.call("record_customer_opt_out", "Customer asked to stop messages", shipment_id=self.shipment.id,
                            evidence=f"{channel} intent extraction {extraction.id}")
            self.cancel_timers()
            self.escalate("customer_opted_out", "medium", "Customer opted out of automated contact; delivery still "
                          "needs a decision.")
            return
        if result.intent == "language_change" and result.requested_language:
            req = result.requested_language
            if req in self.cfg.supported_languages:
                self.customer.preferred_language = req
                self.customer.preferred_language_source = "customer_stated"
                self.customer.preferred_language_confirmed_at = clock.now()
                self.rec.note("language", f"Customer asked for {req}; saved as their preference",
                              language_before=self.state.get("language"), language_after=req, confidence=1.0)
                self.update_state(language=req, language_source="customer_stated", language_confidence=1.0)
                self.reply("language_ack", conv_id)
                self.reply("ask_date", conv_id)
                self.update_state(expecting="date")
            else:
                self.escalate("unsupported_language", "medium", f"Customer asked for a language ({req}) this merchant "
                              "does not support for automated contact.")
            return
        if result.requested_language and result.requested_language != self.state.get("language") \
                and result.requested_language in self.cfg.supported_languages:
            self.update_state(language=result.requested_language, language_source="customer_stated")
        if result.clarification_needed:
            n = int(self.state.get("clarifications", 0)) + 1
            self.update_state(clarifications=n, expecting="date" if result.clarification_topic == "date" else None)
            if n > self.cfg.max_clarifications:
                self.escalate("low_confidence", "medium", f"Could not understand the customer after {n - 1} "
                              f"clarifications. Last message interpreted as '{result.intent}' "
                              f"(confidence {result.confidence:.2f}).")
                return
            key = "date_in_past" if result.validation_status == "invalid" and result.clarification_topic == "date" else (
                "ask_date" if result.clarification_topic == "date" else "ask_again")
            self.reply(key, conv_id)
            self.tools.call("schedule_followup", "Wait for the clarification", name="no_reply",
                            at=clock.now() + timedelta(minutes=self.cfg.whatsapp_reply_wait_minutes))
            self.task.waiting_for = "customer_reply"
            self.next_action = "Wait for the customer's clarification"
            return
        if result.intent == "callback":
            at = self.callback_time(result)
            self.reply("callback_ack", conv_id, when=self.local_dt(at).strftime("%d %b %H:%M"))
            self.try_voice("callback", "customer asked for a call back", at=at)
            return
        self.update_state(expecting=None, clarifications=0)
        decision, row = self.decide(result, extraction, "ndr_recovery")
        self.apply_decision(decision, row, result, extraction, conv_id, channel)

    def callback_time(self, result) -> datetime:
        if result.requested_date:
            hour = int(result.requested_window[:2]) if result.requested_window else 11
            local = datetime.combine(result.requested_date, datetime.min.time()).replace(hour=hour)
            from zoneinfo import ZoneInfo
            at = local.replace(tzinfo=ZoneInfo(self.merchant.timezone)).astimezone(ZoneInfo("UTC"))
            if at > clock.now():
                return at
        return clock.now() + timedelta(hours=2)

    def apply_decision(self, decision, row: RuleDecision, result, extraction, conv_id, channel) -> None:
        if decision.verdict == "ALLOWED" and decision.action in ("reattempt", "reschedule"):
            pref = self.tools.call("save_delivery_preference", "Save the customer's requested delivery slot",
                                   shipment_id=self.shipment.id, requested_date=decision.requested_date,
                                   requested_window=result.requested_window, language=self.state.get("language"),
                                   language_source=self.state.get("language_source"), status="carrier_pending",
                                   source_channel=channel, extraction_id=extraction.id)
            tool = "request_reattempt" if decision.action == "reattempt" else "request_reschedule"
            action = self.tools.call(tool, f"Ask {self.shipment.carrier_code} to {decision.action}",
                                     shipment_id=self.shipment.id, decision_id=row.id)
            self.update_state(pending_action_id=action.id, preference_id=pref.id)
            self.set_case_status("action_requested")
            window = self.fmt_window(result.requested_window if decision.carrier_window_supported else None)
            self.reply("preference_received", conv_id, date=self.fmt_date(decision.requested_date), window=window)
            self.task.waiting_for = "carrier_response"
            self.cancel_timers()
            self.next_action = "Wait for the carrier to accept or reject the request"
            return
        if decision.verdict == "REQUIRES_APPROVAL":
            self.tools.call("save_delivery_preference", "Record what the customer asked for",
                            shipment_id=self.shipment.id, requested_date=decision.requested_date,
                            requested_window=result.requested_window, language=self.state.get("language"),
                            status="requested", source_channel=channel, extraction_id=extraction.id)
            refused = decision.action == "rto"
            self.reply("refusal_ack" if refused else "under_review", conv_id)
            reason = {"rto": "rto_approval", "address_change": "address_change", "phone_change": "phone_change"}.get(
                decision.action or "", "approval_required")
            self.escalate(reason, "high" if refused else "medium",
                          f"Needs approval: {decision.action or 'action'} — " + "; ".join(decision.reasons),
                          pending_decision_id=row.id)
            self.cancel_timers()
            return
        # DENIED
        if "store_preference" in decision.alternatives:
            self.tools.call("save_delivery_preference", "Carrier cannot change the slot via API; keep it as a note",
                            shipment_id=self.shipment.id, requested_date=result.requested_date,
                            requested_window=result.requested_window, status="noted", source_channel=channel,
                            extraction_id=extraction.id)
            self.reply("preference_noted", conv_id, date=self.fmt_date(result.requested_date),
                       window=self.fmt_window(result.requested_window))
            self.escalate("carrier_capability", "medium", "Customer gave a delivery preference the carrier API "
                          "cannot take. Please pass it to the carrier.")
            return
        if "rto" in decision.alternatives:
            self.decide_rto("; ".join(decision.reasons))
            return
        if any(a.startswith(("latest_date:", "date:")) for a in decision.alternatives):
            n = int(self.state.get("clarifications", 0)) + 1
            self.update_state(clarifications=n, expecting="date")
            if n > self.cfg.max_clarifications:
                self.escalate("policy_denied", "medium", "; ".join(decision.reasons))
                return
            self.reply("ask_date", conv_id)
            self.task.waiting_for = "customer_reply"
            self.next_action = "Ask the customer for a date the carrier can serve"
            return
        self.escalate("policy_denied", "medium", "; ".join(decision.reasons) or "Policy denied the request")

    def decide_rto(self, why: str) -> None:
        fake = intent_svc.IntentResult(intent="refuse", confidence=1.0, validation_status="valid",
                                       extractor="policy:attempts", notes=[why])
        from app.platform.models import IntentExtraction  # noqa: F401
        decision, row = self.decide(fake, None, "ndr_recovery", intent_override="refuse")
        self.escalate("rto_approval", "high", f"Return to origin proposed: {why}.", pending_decision_id=row.id)

    def escalate(self, reason: str, priority: str, summary: str, pending_decision_id: str | None = None) -> None:
        self.tools.call("create_escalation", f"Escalate to a person ({reason.replace('_', ' ')})", reason=reason,
                        priority=priority, summary=summary, pending_decision_id=pending_decision_id)
        self.next_action = "Waiting for an operator"

    def cancel_timers(self) -> None:
        for name in list(self.state.get("timers", {})):
            self.tools.call("cancel_obsolete_followup", f"Cancel '{name}' timer (no longer needed)", name=name)

    # ------------------------------------------------------------ voice
    def on_call_retry(self, data: dict) -> None:
        self.try_voice("ndr_recovery", "retry after the contact window opened")

    def on_no_reply(self, data: dict) -> None:
        self.rec.note("note", "No reply within the wait period")
        if self.state.get("followup_sent"):
            self.after_contact_exhausted()
            return
        self.try_voice("ndr_recovery", "no WhatsApp reply")

    def on_message_failed(self, data: dict) -> None:
        msg = self.db.get(Message, data.get("message_id"))
        self.rec.note("note", f"WhatsApp message failed: {msg.failure_reason if msg else 'unknown'}", status="failed",
                      message_id=msg.id if msg else None)
        if self.task.waiting_for not in (None, "customer_reply"):
            # e.g. a confirmation after the carrier already accepted: nothing to recover by calling again.
            self.next_action = f"Still waiting for {self.task.waiting_for.replace('_', ' ')}"
            return
        self.tools.call("cancel_obsolete_followup", "Message failed; stop waiting for a reply", name="no_reply")
        if "voice" in self.cfg.channels:
            self.try_voice("ndr_recovery", "WhatsApp delivery failed")
        else:
            self.escalate("contact_failed", "high", "WhatsApp message could not be delivered and voice is disabled.")

    def on_call_completed(self, data: dict) -> None:
        call = self.db.get(VoiceCall, data["call_id"])
        fv = data.get("final_variables") or {}
        self.tools.call("get_voice_call_status", "Read the call outcome", call_id=call.id)
        if call.status != "completed":
            n_calls = len(list(self.db.scalars(select(VoiceCall.id).where(VoiceCall.ndr_case_id == self.case.id))))
            self.rec.note("note", f"Call {call.code}: {call.status.replace('_', ' ')}", status="failed" if call.status == "failed" else "completed",
                          call_id=call.id)
            if n_calls < self.cfg.max_voice_attempts_per_case:
                delay = self.cfg.voice_retry_minutes[min(n_calls - 1, len(self.cfg.voice_retry_minutes) - 1)]
                at = clock.now() + timedelta(minutes=delay)
                self.tools.call("schedule_followup", f"Retry the call in {delay} minutes", name="call_retry", at=at)
                call.followup_scheduled = True
                self.next_action = f"Retry call at {self.local_dt(at):%d %b %H:%M}"
            else:
                self.after_contact_exhausted()
            return
        if call.final_language and call.final_language != call.start_language:
            self.rec.note("language", f"Call switched from {call.start_language} to {call.final_language}",
                          call_id=call.id, language_before=call.start_language, language_after=call.final_language)
            self.update_state(language=call.final_language, language_source="detected_in_call")
            requested = any(s.get("requested") for s in (fv.get("language_switches") or []))
            if requested:
                self.customer.preferred_language = call.final_language
                self.customer.preferred_language_source = "customer_stated"
                self.customer.preferred_language_confirmed_at = clock.now()
            else:
                self.customer.predicted_language = call.final_language
                self.customer.predicted_language_source = "recent_interaction"
                self.customer.predicted_language_confidence = 0.9
        result = self.intent_from_call(fv, call)
        if result is None:
            self.rec.note("note", "Call ended without a usable answer", call_id=call.id)
            outcome = fv.get("result") or call.result
            if outcome == "unsupported_language":
                self.escalate("unsupported_language", "medium", "Customer speaks a language the voice agent cannot "
                              "handle reliably. Please call back with a suitable agent.")
            elif outcome == "no_response":
                self.on_call_completed_no_answer(call)
            else:
                self.escalate("low_confidence", "medium", "Voice agent could not understand the customer.")
            return
        extraction = self.store_extraction(result, call=call)
        if fv.get("result") == "preference_captured" and fv.get("confirmed_by_customer"):
            call.preference_captured = True
        self.act_on_intent(result, extraction, self.latest_conversation_id(), "voice")
        pending = self.state.get("pending_action_id")
        if pending:
            call.triggered_carrier_action_id = pending

    def on_call_completed_no_answer(self, call: VoiceCall) -> None:
        n_calls = len(list(self.db.scalars(select(VoiceCall.id).where(VoiceCall.ndr_case_id == self.case.id))))
        if n_calls < self.cfg.max_voice_attempts_per_case:
            at = clock.now() + timedelta(minutes=self.cfg.voice_retry_minutes[0])
            self.tools.call("schedule_followup", "Customer was silent; try again later", name="call_retry", at=at)
        else:
            self.after_contact_exhausted()

    def intent_from_call(self, fv: dict, call: VoiceCall):
        intent = fv.get("intent")
        if not intent or intent not in intent_svc.INTENTS:  # type: ignore[attr-defined]
            return None
        from datetime import date as _date
        try:
            rd = _date.fromisoformat(fv["requested_date"]) if fv.get("requested_date") else None
            res = intent_svc.IntentResult(intent=intent, requested_date=rd, requested_window=fv.get("requested_window"),
                                          language=call.final_language,
                                          confidence=0.9 if fv.get("confirmed_by_customer") else 0.72,
                                          extractor=f"voice:{call.provider}", prompt_version="voice-final-vars-v1",
                                          notes=["read back and confirmed on the call"] if fv.get("confirmed_by_customer")
                                          else ["not explicitly confirmed on the call"])
        except Exception:
            return None
        ctx = intent_svc.ExtractionContext(today=self.today(), purpose="ndr_recovery")
        return intent_svc.validate(res, ctx, self.cfg.intent_confidence_threshold)

    def latest_conversation_id(self) -> str | None:
        conv = self.db.scalars(select(Conversation).where(Conversation.shipment_id == self.shipment.id)
                               .order_by(Conversation.created_at.desc())).first()
        return conv.id if conv else None

    # ------------------------------------------------------------ carrier
    def on_carrier_response(self, data: dict) -> None:
        action = self.db.get(CarrierAction, data["action_id"])
        self.tools.call("get_carrier_action_status", "Read the carrier's answer", action_id=action.id)
        from app.platform.models import DeliveryPreference
        pref = self.db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == self.shipment.id)
                               .order_by(DeliveryPreference.created_at.desc())).first()
        lang = self.state.get("language", "en")
        if action.status == "accepted":
            if pref:
                pref.status = "carrier_confirmed"
                pref.carrier_confirmation_status = "accepted"
                pref.carrier_action_id = action.id
            self.set_case_status("reattempt_scheduled")
            when = self.fmt_date(action.requested_date)
            self.send_template("reattempt_confirmed", lang, f"confirm:{action.id}",
                               extra=[self.order.code or self.order.merchant_order_id, self.shipment.carrier_code.title(), when],
                               purpose="confirmation")
            check_at = clock.now() + timedelta(days=max(1, (action.requested_date - self.today()).days + 1) if action.requested_date else 2)
            self.tools.call("schedule_followup", "Check that the carrier actually attempts delivery", name="delivery_check", at=check_at)
            self.task.waiting_for = "delivery"
            self.next_action = f"Carrier confirmed; next attempt {when}"
            return
        if pref:
            pref.status = "carrier_rejected"
            pref.carrier_confirmation_status = action.status
        self.send_template("reattempt_not_possible", lang, f"rejected:{action.id}",
                           extra=[self.order.code or self.order.merchant_order_id], purpose="confirmation")
        if action.status == "rejected":
            self.escalate("carrier_rejected", "high", f"{self.shipment.carrier_code} rejected the {action.action}: "
                          f"{action.rejection_reason}.")
        else:
            self.escalate("carrier_action_failed", "high", f"Carrier request {action.action} ended as {action.status}: "
                          f"{action.last_error or 'no confirmation'}. Reconcile manually before retrying.")

    def on_delivery_check(self, data: dict) -> None:
        if self.shipment.current_status in ("DELIVERED", "RTO", "RTO_DELIVERED"):
            close_task(self.db, self.task, "completed", f"shipment {self.shipment.current_status}")
            return
        self.escalate("carrier_no_show", "high", "Carrier accepted a reattempt but no new delivery attempt was reported "
                      "by the expected date.")

    def on_operator_decision(self, data: dict) -> None:
        if data.get("approved"):
            self.task.waiting_for = "carrier_response"
            self.next_action = "Operator approved; waiting for the carrier"
        else:
            self.task.waiting_for = "operator"
            self.rec.note("note", "Operator rejected the proposed action; no automatic follow-up", status="rejected",
                          decision_id=data.get("decision_id"))
            self.next_action = "Operator decides the next step"


__all__ = ["NdrRecoveryWorkflow", "next_allowed_time", "i18n"]
