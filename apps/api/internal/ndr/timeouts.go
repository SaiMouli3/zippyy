package ndr

import (
	"context"
	"fmt"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

const (
	TriggerReevaluate    = "REEVALUATE"
	TriggerBuyerTimeout  = "BUYER_TIMEOUT"
	TriggerSellerTimeout = "SELLER_TIMEOUT"
	TriggerRetryAction   = "RETRY_ACTION"
)

type ProcessResult struct {
	Trigger string        `json:"trigger"`
	Summary string        `json:"summary"`
	Case    store.NDRCase `json:"case"`
}

// Process advances a case one deterministic step for the given trigger.
func (s *Service) Process(ctx context.Context, ref, trigger string) (*ProcessResult, error) {
	if trigger == "" {
		trigger = TriggerReevaluate
	}
	res := &ProcessResult{Trigger: trigger}
	err := s.withCase(ctx, ref, func(ctx context.Context, c *store.NDRCase) error {
		if c.State == domain.CaseClosed {
			return domain.Conflict("CASE_CLOSED", "this NDR case is closed")
		}
		r := s.Store.R()
		order, err := r.GetOrder(ctx, c.OrderID, false)
		if err != nil {
			return err
		}
		switch trigger {
		case TriggerReevaluate:
			res.Summary, err = s.reevaluate(ctx, c, order)
		case TriggerRetryAction:
			if len(c.Plan) == 0 || string(c.Plan) == "null" {
				return domain.Conflict("NO_PLAN", "there is no planned action to retry")
			}
			if c.State == domain.CaseEscalated {
				if err := s.move(ctx, c, domain.CaseActionPending, actorFromCtx(ctx), "ACTION_RETRY", "Retrying the planned carrier action", nil); err != nil {
					return err
				}
			}
			if c.State != domain.CaseActionPending {
				return domain.Conflict("INVALID_CASE_STATE", "case is not waiting to execute an action")
			}
			err = s.executePlan(ctx, c, order)
			res.Summary = "retried planned carrier action"
		case TriggerBuyerTimeout:
			res.Summary, err = s.buyerTimeout(ctx, c, order)
		case TriggerSellerTimeout:
			res.Summary, err = s.sellerTimeout(ctx, c, order)
		default:
			return domain.Validation("unknown trigger", map[string]string{"trigger": "must be REEVALUATE, BUYER_TIMEOUT, SELLER_TIMEOUT or RETRY_ACTION"})
		}
		if err != nil {
			return err
		}
		if fresh, e := r.GetCase(ctx, c.ID, false); e == nil {
			res.Case = *fresh
		}
		return nil
	})
	return res, err
}

func (s *Service) reevaluate(ctx context.Context, c *store.NDRCase, order *domain.Order) (string, error) {
	r := s.Store.R()
	if (c.State == domain.CaseActionPending) && len(c.Plan) > 0 {
		return "resumed pending carrier action", s.executePlan(ctx, c, order)
	}
	msgs, err := r.ListMessages(ctx, c.ID)
	if err != nil {
		return "", err
	}
	for i := len(msgs) - 1; i >= 0; i-- {
		m := msgs[i]
		if m.Direction == "INBOUND" && !m.Processed {
			return "", domain.Conflict("USE_BUYER_REPLY", "unprocessed buyer message exists but case is "+string(c.State))
		}
	}
	if c.State == domain.CaseIntentExtracted {
		var intent domain.ExtractedIntent
		if err := jsonUnmarshal(c.BuyerIntent, &intent); err == nil && intent.Intent != "" {
			_, err := s.evaluateAndAct(ctx, c, order, intent, "")
			return "re-evaluated stored intent", err
		}
	}
	return "nothing to process in state " + string(c.State), nil
}

// buyerTimeout escalates channels, then applies the seller's default no-response rule.
func (s *Service) buyerTimeout(ctx context.Context, c *store.NDRCase, order *domain.Order) (string, error) {
	if c.State != domain.CaseBuyerContactPending {
		return "", domain.Conflict("INVALID_CASE_STATE", "buyer timeout only applies while waiting for the buyer (state is "+string(c.State)+")")
	}
	r := s.Store.R()
	seller, err := r.GetOrCreateSellerRules(ctx, order.MerchantID)
	if err != nil {
		return "", err
	}
	if err := s.note(ctx, c, systemActor, "BUYER_TIMEOUT", "Buyer did not respond within the timeout", map[string]any{"contactAttempts": c.ContactAttempts}); err != nil {
		return "", err
	}
	attempts, err := r.ListCommAttempts(ctx, c.ID)
	if err != nil {
		return "", err
	}
	used := map[string]bool{}
	for _, a := range attempts {
		if a.Status == "SENT" || a.Status == "DELIVERED" {
			used[a.Channel] = true
		}
	}
	for _, ch := range rules.ChannelOrder(*seller) {
		if !used[ch] {
			if _, err := s.contactCase(ctx, c, ContactOptions{Channel: ch, Reminder: true}); err != nil {
				return "", err
			}
			return "escalated to next channel: " + ch, nil
		}
	}
	// every channel used: apply the default rule
	carrier, err := r.GetCarrierRules(ctx, c.CarrierCode)
	if err != nil {
		return "", err
	}
	if err := s.finalAttemptDecision(ctx, c, order, seller, carrier, "buyer did not respond on any channel"); err != nil {
		return "", err
	}
	return "all channels exhausted; default no-response rule applied", nil
}

// finalAttemptDecision applies rules.DefaultOnNoResponse (reattempt, or the seller RTO decision on the final attempt).
func (s *Service) finalAttemptDecision(ctx context.Context, c *store.NDRCase, order *domain.Order, seller *domain.SellerRules, carrier *domain.CarrierRules, why string) error {
	synthetic := domain.ExtractedIntent{Confidence: 1, InternalSummary: "no buyer response: " + why}
	in, err := s.rulesInput(ctx, c, order, synthetic)
	if err != nil {
		return err
	}
	d := rules.DefaultOnNoResponse(in)
	if len(d.Approvals) > 0 {
		_ = s.note(ctx, c, agentActor, "SELLER_ALERT", fmt.Sprintf("Seller alerted: final attempt (%d), %s. Default if no response: %s.", c.AttemptNumber, why, seller.DefaultOnSilence), map[string]any{"defaultOnSilence": seller.DefaultOnSilence})
	}
	_, err = s.recordAndApply(ctx, c, order, in, d, synthetic, "")
	return err
}

// sellerTimeout applies the seller's default when they never answered a blocking approval.
func (s *Service) sellerTimeout(ctx context.Context, c *store.NDRCase, order *domain.Order) (string, error) {
	if c.State != domain.CaseAwaitingApproval {
		return "", domain.Conflict("INVALID_CASE_STATE", "seller timeout only applies while awaiting approval (state is "+string(c.State)+")")
	}
	r := s.Store.R()
	approvals, err := r.ListApprovals(ctx, "PENDING", c.ID, 50)
	if err != nil {
		return "", err
	}
	if len(approvals) == 0 {
		return "no pending approvals", nil
	}
	now := s.Now()
	var final *store.Approval
	for i := range approvals {
		a := &approvals[i]
		a.Status, a.DecidedBy, a.DecidedAt, a.DecisionNote = "EXPIRED", "system (default rule)", &now, "seller did not respond within the timeout"
		if err := r.UpdateApproval(ctx, a); err != nil {
			return "", err
		}
		if a.Kind == "FINAL_ATTEMPT_DECISION" {
			final = a
		}
	}
	if err := s.note(ctx, c, systemActor, "SELLER_TIMEOUT", "Seller did not respond within the timeout; applying the default rule", nil); err != nil {
		return "", err
	}
	if final == nil {
		if err := s.move(ctx, c, domain.CaseEscalated, systemActor, "ESCALATED", "Seller did not respond to an approval request: escalated to ops", nil); err != nil {
			return "", err
		}
		return "approval expired; escalated to ops", nil
	}
	in, err := s.rulesInput(ctx, c, order, domain.ExtractedIntent{Confidence: 1})
	if err != nil {
		return "", err
	}
	d := rules.RTOByDefault(in)
	if _, err := s.recordAndApply(ctx, c, order, in, d, domain.ExtractedIntent{Confidence: 1}, ""); err != nil {
		return "", err
	}
	return "default RTO rule applied", nil
}

// SweepTimeouts is the background worker body: it fires the same triggers a human can fire from the UI.
func (s *Service) SweepTimeouts(ctx context.Context) {
	log := platform.L(ctx)
	cases, err := s.Store.R().ListCases(ctx, store.CaseFilter{OpenOnly: true, Limit: 500})
	if err != nil {
		log.Error("timeout sweep failed", "error", err.Error())
		return
	}
	now := s.Now()
	for _, c := range cases {
		order, err := s.Store.R().GetOrder(ctx, c.OrderID, false)
		if err != nil {
			continue
		}
		seller, err := s.Store.R().GetOrCreateSellerRules(ctx, order.MerchantID)
		if err != nil {
			continue
		}
		switch c.State {
		case domain.CaseBuyerContactPending:
			if c.LastContactedAt != nil && now.Sub(*c.LastContactedAt) > time.Duration(seller.BuyerResponseTimeoutMinutes)*time.Minute {
				if _, err := s.Process(ctx, c.ID, TriggerBuyerTimeout); err != nil {
					log.Warn("buyer timeout processing failed", "ndrCaseId", c.ID, "error", err.Error())
				}
			}
		case domain.CaseAwaitingApproval:
			if now.Sub(c.UpdatedAt) > time.Duration(seller.SellerResponseTimeoutMinutes)*time.Minute {
				if _, err := s.Process(ctx, c.ID, TriggerSellerTimeout); err != nil {
					log.Warn("seller timeout processing failed", "ndrCaseId", c.ID, "error", err.Error())
				}
			}
		}
	}
}
