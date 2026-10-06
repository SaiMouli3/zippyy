package ndr

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/saimouli3/zippyy/apps/api/internal/agent"
	"github.com/saimouli3/zippyy/apps/api/internal/comms"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type ReplyResult struct {
	MessageID string                 `json:"messageId"`
	Intent    domain.ExtractedIntent `json:"intent"`
	Decision  *rules.Decision        `json:"decision,omitempty"`
	Case      store.NDRCase          `json:"case"`
}

// BuyerReply stores the buyer's message verbatim, applies language switching, extracts intent (AI) and, when
// autoProcess is true, immediately runs the deterministic pipeline.
func (s *Service) BuyerReply(ctx context.Context, ref, text, channel string, autoProcess bool) (*ReplyResult, error) {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil, domain.Validation("message text is required", map[string]string{"text": "must not be empty"})
	}
	if len(text) > 2000 {
		return nil, domain.Validation("message too long", map[string]string{"text": "max 2000 characters"})
	}
	if channel == "" {
		channel = comms.WhatsApp
	}
	var out *ReplyResult
	err := s.withCase(ctx, ref, func(ctx context.Context, c *store.NDRCase) error {
		if c.State == domain.CaseClosed {
			return domain.Conflict("CASE_CLOSED", "this NDR case is closed")
		}
		r := s.Store.R()
		order, err := r.GetOrder(ctx, c.OrderID, false)
		if err != nil {
			return err
		}
		intent, err := s.LLM.ExtractIntent(ctx, text, agent.IntentContext{Now: s.Now(), CaseLanguage: c.Language, Reason: c.NormalizedReason,
			DeliveryPincode: order.DeliveryAddress.Pincode, DeliveryCity: order.DeliveryAddress.City})
		if err != nil {
			return err
		}
		// language-first: the buyer's live reply outranks every other language source
		replyLang := intent.DetectedLanguage
		msgLang := c.Language
		if replyLang != "" && intent.LanguageConfidence >= 0.6 {
			msgLang = replyLang
		}

		var msgID string
		if err := s.Store.InTx(ctx, func(tr *store.Repo) error {
			id, err := tr.InsertMessage(ctx, store.Message{CaseID: c.ID, Direction: "INBOUND", SenderType: domain.ActorBuyer, Channel: channel, Language: msgLang,
				OriginalText: text, InternalText: intent.InternalSummary, Interpretation: jsonRaw(intent), DeliveryStatus: "RECEIVED", Processed: false})
			msgID = id
			return err
		}); err != nil {
			return err
		}

		if c.State == domain.CaseReattemptScheduled || c.State == domain.CaseCarrierAccepted {
			if err := s.move(ctx, c, domain.CaseBuyerContactPending, buyerActor, "BUYER_REOPENED", "Buyer wrote after the reattempt was scheduled; reopening for changes", nil); err != nil {
				return err
			}
		}
		if c.State == domain.CaseOpened || c.State == domain.CaseEscalated {
			if err := s.move(ctx, c, domain.CaseBuyerContactPending, buyerActor, "BUYER_CONTACT_REOPENED", "Buyer replied before/after escalation; resuming conversation", nil); err != nil {
				return err
			}
		}
		if err := s.switchLanguage(ctx, c, order, replyLang, intent.LanguageConfidence, text); err != nil {
			return err
		}
		if c.State == domain.CaseBuyerContactPending {
			if err := s.move(ctx, c, domain.CaseBuyerResponded, buyerActor, "BUYER_RESPONDED", "Buyer replied on "+channel, map[string]any{"messageId": msgID, "channel": channel, "originalText": text}); err != nil {
				return err
			}
			if err := s.Store.InTx(ctx, func(tr *store.Repo) error {
				c.BuyerIntent = jsonRaw(intent)
				if err := tr.UpdateMessageProcessed(ctx, msgID, intent, intent.InternalSummary); err != nil {
					return err
				}
				return s.moveR(ctx, tr, c, domain.CaseIntentExtracted, agentActor, "INTENT_EXTRACTED",
					fmt.Sprintf("Intent extracted: %s (confidence %.2f)", intent.Intent, intent.Confidence), map[string]any{"intent": intent, "provider": s.LLM.Name()})
			}); err != nil {
				return err
			}
		} else {
			// reply received while awaiting approval / action: keep it, do not disturb the workflow
			_ = s.Store.R().UpdateMessageProcessed(ctx, msgID, intent, intent.InternalSummary)
			if err := s.note(ctx, c, buyerActor, "BUYER_MESSAGE_WHILE_BUSY", fmt.Sprintf("Buyer messaged while the case is %s; recorded without changing the workflow", c.State), map[string]any{"messageId": msgID, "intent": intent.Intent}); err != nil {
				return err
			}
			out = &ReplyResult{MessageID: msgID, Intent: intent, Case: *c}
			return nil
		}
		out = &ReplyResult{MessageID: msgID, Intent: intent}
		if autoProcess {
			d, err := s.evaluateAndAct(ctx, c, order, intent, "")
			if err != nil {
				return err
			}
			out.Decision = d
		}
		fresh, _ := s.Store.R().GetCase(ctx, c.ID, false)
		if fresh != nil {
			out.Case = *fresh
		}
		return nil
	})
	return out, err
}

// switchLanguage changes case.language when the buyer writes in a different supported language.
func (s *Service) switchLanguage(ctx context.Context, c *store.NDRCase, order *domain.Order, detected string, conf float64, sample string) error {
	if detected == "" || conf < 0.6 || !domain.SupportedLanguage(detected) {
		return nil
	}
	if detected == c.Language {
		if c.LanguageSource != "reply" {
			c.LanguageSource = "reply"
			return s.Store.R().SaveCase(ctx, c)
		}
		return nil
	}
	from := c.Language
	err := s.Store.InTx(ctx, func(tr *store.Repo) error {
		c.Language, c.LanguageSource = detected, "reply"
		if err := tr.SaveCase(ctx, c); err != nil {
			return err
		}
		if err := tr.UpsertBuyerLanguage(ctx, order.Customer.Phone, order.Customer.Name, detected); err != nil {
			return err
		}
		return s.noteR(ctx, tr, c, agentActor, "LANGUAGE_SWITCHED", fmt.Sprintf("Language switched from %s to %s (buyer replied in %s)", agent.LanguageName(from), agent.LanguageName(detected), agent.LanguageName(detected)),
			map[string]any{"from": from, "to": detected, "confidence": conf, "source": "reply", "sample": sample})
	})
	if err == nil {
		s.Metrics.Inc("ndr_language_switches_total", "from", from, "to", detected)
	}
	return err
}

func (s *Service) pendingOf(c *store.NDRCase) *rules.Pending {
	if len(c.Pending) == 0 || string(c.Pending) == "null" {
		return nil
	}
	var p rules.Pending
	if json.Unmarshal(c.Pending, &p) != nil {
		return nil
	}
	return &p
}

func (s *Service) rulesInput(ctx context.Context, c *store.NDRCase, order *domain.Order, intent domain.ExtractedIntent) (rules.Input, error) {
	r := s.Store.R()
	seller, err := r.GetOrCreateSellerRules(ctx, order.MerchantID)
	if err != nil {
		return rules.Input{}, err
	}
	carrier, err := r.GetCarrierRules(ctx, c.CarrierCode)
	if err != nil {
		return rules.Input{}, err
	}
	actions, err := r.ListActions(ctx, c.ID)
	if err != nil {
		return rules.Input{}, err
	}
	prior := false
	for _, a := range actions {
		if a.ActionType == string(domain.ActionReattempt) && a.Status == "ACCEPTED" {
			prior = true
		}
	}
	return rules.Input{Reason: c.NormalizedReason, Attempt: c.AttemptNumber, Intent: intent, Seller: *seller, Carrier: *carrier, Now: s.Now(), ConfidenceMin: s.Cfg.ConfidenceMin,
		Pending: s.pendingOf(c), PriorReattemptAccepted: prior,
		Order: rules.OrderFacts{PaymentType: order.PaymentType, CODAmount: order.CODAmount, DeliveryAddress: order.DeliveryAddress, CustomerPhone: order.Customer.Phone}}, nil
}

// evaluateAndAct runs the deterministic rules engine and applies its decision. actorRole is set for
// seller/ops-initiated actions so approvals they can personally grant are satisfied.
func (s *Service) evaluateAndAct(ctx context.Context, c *store.NDRCase, order *domain.Order, intent domain.ExtractedIntent, actorRole string) (*rules.Decision, error) {
	in, err := s.rulesInput(ctx, c, order, intent)
	if err != nil {
		return nil, err
	}
	d := rules.Evaluate(in)
	return s.recordAndApply(ctx, c, order, in, d, intent, actorRole)
}

func (s *Service) recordAndApply(ctx context.Context, c *store.NDRCase, order *domain.Order, in rules.Input, d rules.Decision, intent domain.ExtractedIntent, actorRole string) (*rules.Decision, error) {
	if err := s.note(ctx, c, agentActor, "RULES_CHECKED", fmt.Sprintf("Rules engine evaluated: %s — %s", d.Outcome, d.Reason),
		map[string]any{"outcome": d.Outcome, "checks": d.Checks, "plan": d.Plan, "attempt": in.Attempt, "intent": intent.Intent}); err != nil {
		return nil, err
	}
	s.Metrics.Inc("ndr_decisions_total", "outcome", string(d.Outcome))
	if d.ReasonOverride != "" && d.ReasonOverride != c.NormalizedReason {
		prev := c.NormalizedReason
		c.NormalizedReason, c.ReasonSource = d.ReasonOverride, "BUYER_STATEMENT"
		if err := s.Store.R().SaveCase(ctx, c); err != nil {
			return nil, err
		}
		if err := s.note(ctx, c, agentActor, "REASON_RECLASSIFIED", fmt.Sprintf("Case reclassified %s → %s based on the buyer's statement", prev, d.ReasonOverride), map[string]any{"statement": intent.InternalSummary}); err != nil {
			return nil, err
		}
	}
	return &d, s.apply(ctx, c, order, in, d, intent, actorRole)
}

func (s *Service) apply(ctx context.Context, c *store.NDRCase, order *domain.Order, in rules.Input, d rules.Decision, intent domain.ExtractedIntent, actorRole string) error {
	r := s.Store.R()
	params := d.BuyerParams
	if params == nil {
		params = map[string]string{}
	}
	c.RecommendedAction = firstNonEmpty(c.RecommendedAction, rules.RecommendedAction(c.NormalizedReason))
	setPending := func() {
		c.Pending = nil
		if d.Pending != nil {
			c.Pending = jsonRaw(d.Pending)
		}
	}

	switch d.Outcome {
	case rules.Clarify, rules.NeedsConfirmation, rules.OfferAlternative, rules.OfferPrepaid, rules.NoAction, rules.SendPaymentLink:
		setPending()
		if d.Outcome == rules.SendPaymentLink {
			params["link"] = fmt.Sprintf("%s/%s", strings.TrimRight(s.Cfg.PaymentBaseURL, "/"), strings.ToLower(c.CaseNumber))
		}
		if d.Outcome == rules.NeedsConfirmation {
			params["summary"] = intent.InternalSummary
		}
		for _, k := range []string{"requested", "date"} {
			if v, ok := params[k]; ok {
				params[k] = humanDate(v)
			}
		}
		if err := s.move(ctx, c, domain.CaseBuyerContactPending, agentActor, "AGENT_REPLIED", fmt.Sprintf("Agent asked the buyer: %s", d.BuyerKey),
			map[string]any{"outcome": d.Outcome, "messageKey": d.BuyerKey, "pending": d.Pending}); err != nil {
			return err
		}
		s.sendToBuyer(ctx, c, order, d.BuyerKey, params)
		return nil

	case rules.SellerApproval, rules.SellerOpsApproval, rules.OpsApproval:
		return s.requestApprovals(ctx, c, order, in, d, intent, actorRole)

	case rules.Escalate:
		c.ActualAction = ""
		if err := s.move(ctx, c, domain.CaseEscalated, agentActor, "ESCALATED", "Escalated to ops: "+d.Reason, map[string]any{"reason": d.Reason, "checks": d.Checks}); err != nil {
			return err
		}
		s.sendToBuyer(ctx, c, order, "escalated", nil)
		return nil

	case rules.AgentAllowed:
		c.ActualAction = d.ActualAction
		c.Plan = jsonRaw(d.Plan)
		c.Pending = nil
		// non-blocking side approvals (e.g. false-attempt dispute draft) are raised alongside
		for _, a := range d.Approvals {
			if err := s.createApproval(ctx, c, order, in, a, intent, nil); err != nil {
				return err
			}
		}
		if err := s.move(ctx, c, domain.CaseActionPending, agentActor, "ACTION_PLANNED", "Agent may act: "+d.ActualAction, map[string]any{"plan": d.Plan}); err != nil {
			return err
		}
		_ = r
		return s.executePlan(ctx, c, order)
	}
	return nil
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// sendToBuyer is best-effort: a failed channel never aborts the workflow, but it is always recorded.
func (s *Service) sendToBuyer(ctx context.Context, c *store.NDRCase, order *domain.Order, key string, params map[string]string) {
	r := s.Store.R()
	seller, err := r.GetOrCreateSellerRules(ctx, order.MerchantID)
	if err != nil {
		return
	}
	text, _ := s.LLM.ComposeMessage(ctx, key, c.Language, params)
	internal, _ := s.LLM.ComposeMessage(ctx, key, "en", params)
	to := order.Customer.Phone
	if latest, err := r.GetOrder(ctx, order.ID, false); err == nil {
		to = latest.Customer.Phone
	}
	channels := rules.ChannelOrder(*seller)
	attempts, delivered := s.Comms.Send(ctx, channels, comms.Message{CaseNumber: c.CaseNumber, To: to, Language: c.Language, Text: text}, nil)
	_ = s.Store.InTx(ctx, func(tr *store.Repo) error {
		for _, a := range attempts {
			status, em := a.Result.Status, ""
			if a.Err != nil {
				status, em = "FAILED", a.Err.Error()
			}
			_ = tr.InsertCommAttempt(ctx, c.ID, a.Channel, status, em, a.Result.ProviderRef)
		}
		ch, st := firstChannel(attempts, channels), "FAILED"
		if delivered {
			last := attempts[len(attempts)-1]
			ch, st = last.Channel, last.Result.Status
		}
		_, err := tr.InsertMessage(ctx, store.Message{CaseID: c.ID, Direction: "OUTBOUND", SenderType: domain.ActorAgent, Channel: ch, Language: c.Language, OriginalText: text, InternalText: internal, DeliveryStatus: st, Processed: true})
		if err != nil {
			return err
		}
		return s.noteR(ctx, tr, c, agentActor, "BUYER_MESSAGE_SENT", fmt.Sprintf("Buyer message (%s) via %s: %s", key, ch, st), map[string]any{"messageKey": key, "channel": ch, "status": st, "language": c.Language})
	})
}
