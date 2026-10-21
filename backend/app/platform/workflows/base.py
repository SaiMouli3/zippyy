"""Shared workflow machinery: context loading, contact language, extraction -> decision, recording."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.platform import clock, intent as intent_svc, language as lang_svc, policies, policy
from app.platform.contact_guard import local_now
from app.platform.models import (Address, AgentTask, Customer, IntentExtraction, Merchant, Message, NdrCase, Order,
                                 RuleDecision, Shipment, VoiceCall)
from app.platform.providers.whatsapp import whatsapp_live
from app.platform.tools import ToolBox, carrier_capabilities
from app.platform.workflows.engine import RunRecorder


class Workflow:
    agent_name = "base"

    def __init__(self, db: Session, task: AgentTask, trigger: str):
        self.db = db
        self.task = task
        self.merchant = db.get(Merchant, task.merchant_id)
        self.shipment = db.get(Shipment, task.shipment_id)
        self.order = db.get(Order, self.shipment.order_id)
        self.customer = db.get(Customer, self.order.customer_id)
        self.address = db.get(Address, self.order.address_id) if self.order.address_id else None
        self.case = db.get(NdrCase, task.ndr_case_id) if task.ndr_case_id else None
        self.cfg_version, self.cfg = policies.agent_config(db, self.merchant.id)
        if "whatsapp" in self.cfg.channels and not whatsapp_live(self.merchant.is_demo):
            # Live merchant, WhatsApp not connected yet: contact by voice instead of a message nobody receives.
            self.cfg = self.cfg.model_copy(update={"channels": [c for c in self.cfg.channels if c != "whatsapp"]})
        self.carrier_caps = carrier_capabilities(db, self.shipment.carrier_code)
        self.rec = RunRecorder(db, task, self.merchant.id, self.agent_name, trigger)
        self.tools = ToolBox(self)
        self.next_action: str | None = None

    # ------------------------------------------------------------ helpers
    @property
    def state(self) -> dict:
        return self.task.state

    def update_state(self, **kw) -> None:
        self.task.state = {**self.task.state, **kw}

    def today(self) -> date:
        return local_now(self.merchant).date()

    def key(self, name: str) -> str:
        """Idempotency key for a consequential operation, scoped to this task and cycle."""
        return f"{self.task.id}:{self.task.delivery_cycle}:{name}"

    def contact_language(self) -> lang_svc.LanguageChoice:
        if self.state.get("language"):
            return lang_svc.LanguageChoice(self.state["language"], self.state.get("language_source", "conversation"),
                                           float(self.state.get("language_confidence", 1.0)), True)
        choice = lang_svc.choose_contact_language(
            self.db, self.customer, list(self.cfg.supported_languages),
            self.address.pincode if self.address else None, self.address.state if self.address else None,
            self.cfg.language_switch_confidence)
        if choice.source == "address_prior" and not self.customer.predicted_language:
            self.customer.predicted_language = choice.language
            self.customer.predicted_language_source = "address_prior"
            self.customer.predicted_language_confidence = choice.confidence
        self.rec.note("language", f"Contact language: {lang_svc.LANG_NAMES.get(choice.language, choice.language)} "
                                  f"({choice.source.replace('_', ' ')})",
                      language_after=choice.language, confidence=choice.confidence,
                      output={"source": choice.source, "supported": choice.supported})
        self.update_state(language=choice.language, language_source=choice.source, language_confidence=choice.confidence)
        return choice

    def record_message_language(self, msg: Message) -> None:
        """A customer message in a different language than we were using switches the conversation, with the same
        hysteresis as voice: a single short/low-confidence message only flags it."""
        current = self.state.get("language")
        if not msg.language or msg.language == current or msg.language not in self.cfg.supported_languages:
            return
        words = len((msg.body or "").split())
        strong = (msg.language_confidence or 0) >= self.cfg.language_switch_confidence and words >= 3
        if strong or self.state.get("pending_language") == msg.language:
            self.rec.note("language", f"Customer wrote in {lang_svc.LANG_NAMES.get(msg.language)}; replying in it",
                          language_before=current, language_after=msg.language, confidence=msg.language_confidence,
                          message_id=msg.id)
            self.update_state(language=msg.language, language_source="detected_in_conversation",
                              language_confidence=msg.language_confidence, pending_language=None)
            if (msg.language_confidence or 0) >= self.cfg.language_preference_save_confidence:
                self.customer.predicted_language = msg.language
                self.customer.predicted_language_source = "recent_interaction"
                self.customer.predicted_language_confidence = msg.language_confidence
        else:
            self.update_state(pending_language=msg.language)

    def extract(self, text: str, purpose: str, message: Message | None = None, call: VoiceCall | None = None,
                expecting: str | None = None) -> tuple[intent_svc.IntentResult, IntentExtraction]:
        ctx = intent_svc.ExtractionContext(today=self.today(), purpose=purpose,
                                           ndr_reason=self.case.reason if self.case else None, expecting=expecting)
        result = intent_svc.get_extractor().extract(text, ctx)
        result = intent_svc.validate(result, ctx, self.cfg.intent_confidence_threshold)
        return result, self.store_extraction(result, message, call, text_ref=message.id if message else (call.id if call else None))

    def store_extraction(self, result, message=None, call=None, text_ref=None) -> IntentExtraction:
        row = IntentExtraction(
            merchant_id=self.merchant.id, ndr_case_id=self.case.id if self.case else None, shipment_id=self.shipment.id,
            message_id=message.id if message else None, call_id=call.id if call else None, intent=result.intent,
            requested_date=result.requested_date, requested_window=result.requested_window,
            address_change_requested=result.address_change_requested, phone_change_requested=result.phone_change_requested,
            accepts_delivery=result.accepts_delivery, language=result.language, confidence=result.confidence,
            extractor=result.extractor, prompt_version=result.prompt_version or intent_svc.PROMPT_VERSION,
            validation_status=result.validation_status, clarification_needed=result.clarification_needed,
            entities={"notes": result.notes, "cod_ready": result.cod_ready, "requested_language": result.requested_language,
                      "clarification_topic": result.clarification_topic},
            latency_ms=result.latency_ms)
        self.db.add(row)
        self.db.flush()
        status = "validated" if result.validation_status == "valid" else "proposed"
        self.rec.note("extraction", f"Interpreted customer {'message' if message else 'call'} as '{result.intent}'"
                      + (f" for {result.requested_date}" if result.requested_date else "")
                      + (f" {result.requested_window}" if result.requested_window else ""),
                      status=status, extraction_id=row.id, message_id=message.id if message else None,
                      call_id=call.id if call else None, confidence=result.confidence, language_after=result.language,
                      output={"intent": result.intent, "date": str(result.requested_date) if result.requested_date else None,
                              "window": result.requested_window, "validation": result.validation_status,
                              "notes": result.notes, "extractor": result.extractor})
        return row

    def decide(self, result, extraction: IntentExtraction, purpose: str, intent_override: str | None = None) -> tuple[policy.PolicyResult, RuleDecision]:
        inp = policy.PolicyInput(
            intent=intent_override or result.intent, intent_valid=result.validation_status == "valid",
            intent_confidence=result.confidence, requested_date=result.requested_date,
            requested_window=result.requested_window, today=self.today(), now=local_now(self.merchant),
            purpose=purpose, case_open=self.case is None or self.case.status not in ("resolved", "closed_no_response"),
            shipment_status=self.shipment.current_status, attempt_count=self.shipment.attempt_count,
            payment_mode=self.order.payment_type, cod_amount_paise=int(float(self.order.cod_amount or 0) * 100),
            sla_due_at=clock.as_utc(self.case.sla_due_at) if self.case else None,
            carrier_capabilities=self.carrier_caps, config=self.cfg,
            customer_opted_out=self.customer.opted_out_at is not None)
        out = policy.evaluate(inp)
        row = RuleDecision(merchant_id=self.merchant.id, ndr_case_id=self.case.id if self.case else None,
                           shipment_id=self.shipment.id, extraction_id=extraction.id if extraction else None,
                           verdict=out.verdict, action=out.action, requested_date=out.requested_date,
                           requested_window=out.requested_window, reasons=out.reasons, rules_fired=out.rules_fired,
                           rules_version=out.rules_version, policy_version_id=self.cfg_version.id,
                           approval_status="pending" if out.verdict == "REQUIRES_APPROVAL" else None)
        self.db.add(row)
        self.db.flush()
        step_status = {"ALLOWED": "validated", "REQUIRES_APPROVAL": "proposed", "DENIED": "rejected"}[out.verdict]
        self.rec.note("decision", f"Policy {out.verdict.replace('_', ' ').lower()}: "
                                  f"{out.action or 'no carrier action'}" + (f" on {out.requested_date}" if out.requested_date else ""),
                      status=step_status, decision_id=row.id, extraction_id=extraction.id if extraction else None,
                      policy_rule=",".join(out.rules_fired)[:80],
                      output={"verdict": out.verdict, "reasons": out.reasons, "rulesVersion": out.rules_version,
                              "policyVersion": self.cfg_version.version, "alternatives": out.alternatives})
        return out, row

    def set_case_status(self, status: str, strategy: str | None = None) -> None:
        if self.case is None or self.case.status in ("resolved", "closed_no_response", "rto"):
            return
        self.case.status = status
        if strategy:
            self.case.recovery_strategy = strategy

    def fmt_date(self, d: date | None) -> str:
        return d.strftime("%a %d %b") if d else "the next working day"

    def fmt_window(self, w: str | None) -> str:
        return f" ({w.replace('-', '–')})" if w else ""

    def local_dt(self, d: datetime) -> datetime:
        return d.astimezone(ZoneInfo(self.merchant.timezone or "Asia/Kolkata"))
