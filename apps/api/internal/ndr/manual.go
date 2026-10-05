package ndr

import (
	"context"
	"fmt"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type ManualActionInput struct {
	Type      domain.ActionType `json:"type"`
	Date      string            `json:"date,omitempty"`
	TimeStart string            `json:"timeStart,omitempty"`
	Phone     string            `json:"phone,omitempty"`
	Address   *domain.Address   `json:"address,omitempty"`
	Landmark  string            `json:"landmark,omitempty"`
	Note      string            `json:"note,omitempty"`
}

type ManualActionResult struct {
	Decision *rules.Decision `json:"decision"`
	Case     store.NDRCase   `json:"case"`
}

func sp(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// SubmitManualAction lets a seller/ops user drive a carrier action (e.g. supply an alternate phone). It goes
// through the SAME rules engine as buyer-driven actions: a manual request cannot bypass carrier capability or
// seller policy, and approvals the acting user cannot grant are still raised.
func (s *Service) SubmitManualAction(ctx context.Context, ref string, in ManualActionInput, actorRole string) (*ManualActionResult, error) {
	if actorRole != domain.RoleSeller && actorRole != domain.RoleOps {
		return nil, domain.Forbidden("a SELLER or OPS role is required to submit carrier actions")
	}
	if !in.Type.Valid() {
		return nil, domain.Validation("unknown action type", map[string]string{"type": "must be one of REQUEST_REATTEMPT, RESCHEDULE, UPDATE_PHONE, UPDATE_ADDRESS, CONVERT_TO_PREPAID, INITIATE_RTO"})
	}
	var out *ManualActionResult
	err := s.withCase(ctx, ref, func(ctx context.Context, c *store.NDRCase) error {
		if c.State == domain.CaseClosed {
			return domain.Conflict("CASE_CLOSED", "this NDR case is closed")
		}
		r := s.Store.R()
		order, err := r.GetOrder(ctx, c.OrderID, false)
		if err != nil {
			return err
		}
		intent := domain.ExtractedIntent{Confidence: 1, DetectedLanguage: c.Language, SpecialInstruction: sp(in.Note)}
		var pending *rules.Pending
		switch in.Type {
		case domain.ActionReattempt, domain.ActionReschedule:
			intent.Intent, intent.PreferredDate, intent.PreferredTimeStart = domain.IntentReattempt, sp(in.Date), sp(in.TimeStart)
			if in.Date != "" {
				intent.Intent = domain.IntentRescheduleDelivery
			}
		case domain.ActionUpdatePhone:
			intent.Intent, intent.NewPhone = domain.IntentPhoneUpdate, sp(in.Phone)
		case domain.ActionUpdateAddress:
			intent.Intent, intent.Landmark = domain.IntentAddressCorrection, sp(in.Landmark)
			if in.Address != nil {
				intent.NewAddressLine, intent.NewPincode, intent.NewCity = sp(in.Address.AddressLine1), sp(in.Address.Pincode), sp(in.Address.City)
			}
		case domain.ActionConvertPrepaid:
			intent.Intent = domain.IntentPaymentDone // seller/ops attests that payment was received
			pending = &rules.Pending{Type: "PAYMENT_LINK_SENT"}
		case domain.ActionInitiateRTO:
			intent.Intent = domain.IntentCancelOrder
		}
		intent.InternalSummary = fmt.Sprintf("manual %s by %s", in.Type, actorRole)
		rin, err := s.rulesInput(ctx, c, order, intent)
		if err != nil {
			return err
		}
		if pending != nil {
			rin.Pending = pending
		}
		d := rules.Evaluate(rin)
		switch d.Outcome {
		case rules.AgentAllowed, rules.SellerApproval, rules.SellerOpsApproval, rules.OpsApproval:
		default:
			_ = s.note(ctx, c, actorFromCtx(ctx), "MANUAL_ACTION_BLOCKED", fmt.Sprintf("Manual %s blocked by rules: %s", in.Type, d.Reason), map[string]any{"outcome": d.Outcome, "checks": d.Checks})
			return domain.NewError(422, "ACTION_NOT_PERMITTED", "rules do not permit this action: "+d.Reason).With("outcome", d.Outcome).With("checks", d.Checks).With("offered", d.BuyerParams)
		}
		if err := s.note(ctx, c, actorFromCtx(ctx), "MANUAL_ACTION_REQUESTED", fmt.Sprintf("%s requested %s", actorRole, in.Type), map[string]any{"input": in}); err != nil {
			return err
		}
		dec, err := s.recordAndApply(ctx, c, order, rin, d, intent, actorRole)
		if err != nil {
			return err
		}
		fresh, _ := s.Store.R().GetCase(ctx, c.ID, false)
		out = &ManualActionResult{Decision: dec}
		if fresh != nil {
			out.Case = *fresh
		}
		return nil
	})
	return out, err
}
