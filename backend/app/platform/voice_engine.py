"""Turn-by-turn multilingual voice conversation engine.

Used by the voice simulator (and usable behind any streaming telephony + STT/TTS runtime). For each customer
turn it:
  1. detects the language (Sarvam LID when configured, heuristic otherwise) with a confidence;
  2. feeds it to a SwitchTracker so one ambiguous word never flips the call, but a clear switch is followed
     immediately without restarting the workflow (context, intent and history are kept);
  3. extracts intent with the same extractor used for WhatsApp;
  4. reads important information back and accepts corrections;
  5. handles silence, unsupported languages and repeated misunderstanding by ending politely and handing
     over (callback / human) instead of looping.

The output never claims a delivery time is confirmed: the closing line says the request will be sent to the
courier and confirmed separately.
"""
from dataclasses import dataclass, field
from datetime import date

from app.platform import i18n
from app.platform import language as lang_svc
from app.platform.intent import ExtractionContext, IntentResult, RuleExtractor
from app.platform.providers.base import CallTurn

AGENT_SECONDS_PER_WORD = 0.42
CUSTOMER_SECONDS_PER_WORD = 0.5


@dataclass
class CallScript:
    """The customer's side of a call (simulation). `None` is silence; turns are consumed in order."""
    turns: list[str | None]


@dataclass
class CallOutcome:
    result: str  # preference_captured | refused | callback_requested | review_needed | opted_out | no_response
    # | unsupported_language | unresolved | available_confirmed
    turns: list[CallTurn] = field(default_factory=list)
    intent: IntentResult | None = None
    start_language: str = "en"
    final_language: str = "en"
    switches: list[dict] = field(default_factory=list)
    duration_seconds: int = 0
    confirmed_by_customer: bool = False

    def final_variables(self) -> dict:
        i = self.intent
        return {
            "intent": i.intent if i else None,
            "requested_date": i.requested_date.isoformat() if i and i.requested_date else None,
            "requested_window": i.requested_window if i else None,
            "customer_language": self.final_language,
            "language_switches": self.switches,
            "confirmed_by_customer": self.confirmed_by_customer,
            "result": self.result,
        }


def _fmt_date(d: date, lang: str) -> str:
    return d.strftime("%d %b")


def _fmt_window(w: str | None, lang: str) -> str:
    if not w:
        return ""
    a, b = w.split("-")
    return f", {a}–{b}"


class ConversationEngine:
    def __init__(self, supported: list[str], switch_threshold: float, max_clarifications: int = 2,
                 detector=None, extractor=None):
        self.supported = supported
        self.threshold = switch_threshold
        self.max_clar = max_clarifications
        self.detect = detector or lang_svc.detect
        self.extractor = extractor or RuleExtractor()

    def run(self, script: CallScript, start_language: str, purpose: str, today: date, names: dict) -> CallOutcome:
        lang = start_language if start_language in i18n.FLUENT else "en"
        out = CallOutcome("unresolved", start_language=lang, final_language=lang)
        tracker = lang_svc.SwitchTracker(lang, self.threshold)
        clock = 0.0
        silences = 0
        clarifications = 0
        unsupported_strikes = 0
        pending: IntentResult | None = None
        expecting: str | None = None

        def say(key: str, table=i18n.VOICE, **kw) -> None:
            nonlocal clock
            text, used = i18n.line(table, key, tracker.current, **kw)
            out.turns.append(CallTurn(speaker="agent", text=text, language=used, offset_seconds=round(clock, 1)))
            clock += max(2.0, len(text.split()) * AGENT_SECONDS_PER_WORD)

        say("greet_ndr" if purpose == "ndr_recovery" else "greet_pre", **names)
        for utterance in script.turns:
            if utterance is None:
                silences += 1
                out.turns.append(CallTurn(speaker="customer", text=None, kind="silence", offset_seconds=round(clock, 1)))
                clock += 5.0
                if silences >= 2:
                    say("silence_end")
                    out.result = "no_response"
                    break
                say("silence")
                continue
            silences = 0
            det = self.detect(utterance)
            words = len(utterance.split())
            previous = tracker.current
            current, switched, ask_lang = tracker.observe(det, words)
            turn = CallTurn(speaker="customer", text=utterance, language=det.language,
                            language_confidence=det.confidence, code_mixed=det.code_mixed,
                            offset_seconds=round(clock, 1))
            out.turns.append(turn)
            clock += max(1.5, words * CUSTOMER_SECONDS_PER_WORD)

            heard = det.language
            if heard and heard != previous and det.confidence >= 0.6 and (heard not in self.supported or heard not in i18n.FLUENT):
                # A language we cannot handle reliably: say so and offer alternatives; never switch into it.
                tracker.current, tracker._pending = previous, None
                unsupported_strikes += 1
                say("unsupported_language", language=i18n.lang_name(heard, "en"))
                if unsupported_strikes >= 2:
                    out.result = "unsupported_language"
                    break
                continue
            if switched:
                turn.switched_from = previous
                out.switches.append({"from": previous, "to": current, "turn": len(out.turns) - 1,
                                     "confidence": det.confidence, "code_mixed": det.code_mixed})
            ctx = ExtractionContext(today=today, purpose=purpose, expecting=expecting)
            result = self.extractor.extract(utterance, ctx)

            if (not switched and ask_lang and not result.requested_language
                    and det.language in self.supported and det.language in i18n.FLUENT):
                say("confirm_language", language=i18n.lang_name(det.language, tracker.current))
                expecting = "language"
                continue

            if expecting == "language" and result.intent == "available" and tracker._pending:
                tracker.current = tracker._pending
                out.switches.append({"from": previous, "to": tracker.current, "turn": len(out.turns) - 1,
                                     "confidence": det.confidence, "code_mixed": det.code_mixed, "confirmed": True})
                tracker._pending = None
                expecting = None
                say("ask_date")
                continue

            req = result.requested_language
            if req and out.switches and out.switches[-1]["to"] == req and req == tracker.current:
                out.switches[-1]["requested"] = True  # they asked for it in that very language
            if req and req != tracker.current and req in self.supported and req in i18n.FLUENT:
                # Explicit request ("speak in Hindi"): switch now and keep processing the same turn.
                out.switches.append({"from": tracker.current, "to": req, "turn": len(out.turns) - 1,
                                     "confidence": 1.0, "requested": True})
                tracker.current = req
            if result.intent == "language_change" and req:
                if req in self.supported and req in i18n.FLUENT:
                    say("ask_date")
                else:
                    say("unsupported_language", language=i18n.lang_name(req, "en"))
                    unsupported_strikes += 1
                    if unsupported_strikes >= 2:
                        out.result = "unsupported_language"
                        break
                continue

            if expecting == "confirmation" and pending is not None:
                if result.intent in ("available",) or (result.accepts_delivery and result.requested_date is None):
                    out.intent = pending
                    out.confirmed_by_customer = True
                    out.result = "preference_captured"
                    say("confirmed_end")
                    break
                if result.requested_date or result.requested_window:  # correction
                    pending = pending.model_copy(update={
                        "requested_date": result.requested_date or pending.requested_date,
                        "requested_window": result.requested_window or pending.requested_window,
                        "notes": [*pending.notes, "customer corrected the read-back"],
                    })
                    say("readback", date=_fmt_date(pending.requested_date, tracker.current),
                        window=_fmt_window(pending.requested_window, tracker.current))
                    continue
                expecting = "date"
                pending = None
                say("ask_date")
                continue

            if result.intent == "opt_out":
                out.intent, out.result = result, "opted_out"
                say("opt_out_end")
                break
            if result.intent in ("refuse", "cancel_order"):
                out.intent, out.result = result, "refused"
                say("refused_end")
                break
            if result.intent in ("address_change", "phone_change") or (result.validation_status == "invalid" and result.intent == "other"):
                out.intent, out.result = result, "review_needed"
                say("review_end")
                break
            if result.intent == "callback":
                out.intent, out.result = result, "callback_requested"
                say("callback_end", table=i18n.VOICE, when="later today")
                break
            if purpose == "pre_delivery" and result.intent == "available":
                out.intent, out.result, out.confirmed_by_customer = result, "available_confirmed", True
                say("confirmed_end")
                break
            if result.clarification_needed:
                clarifications += 1
                if clarifications > self.max_clar:
                    out.intent, out.result = result, "unresolved"
                    say("unresolved_end")
                    break
                expecting = "date"
                say("ask_date" if result.clarification_topic == "date" else "ask_again")
                continue
            if result.intent in ("reschedule", "reattempt_today", "cod_ready", "cod_not_ready") and result.requested_date:
                pending = result
                expecting = "confirmation"
                say("readback", date=_fmt_date(result.requested_date, tracker.current),
                    window=_fmt_window(result.requested_window, tracker.current))
                continue
            if result.intent in ("cod_ready", "available"):
                pending = result.model_copy(update={"requested_date": today if purpose == "pre_delivery" else None})
                expecting = "date"
                say("ask_date")
                continue
            clarifications += 1
            if clarifications > self.max_clar:
                out.intent, out.result = result, "unresolved"
                say("unresolved_end")
                break
            expecting = "date"
            say("ask_again")
        else:
            if out.result == "unresolved" and pending is not None and expecting == "confirmation":
                # Customer hung up after the read-back without confirming: keep it, but unconfirmed.
                out.intent = pending

        out.final_language = tracker.current
        out.duration_seconds = int(clock) + 3
        return out
