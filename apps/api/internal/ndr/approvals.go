package ndr

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

func (s *Service) createApproval(ctx context.Context, c *store.NDRCase, order *domain.Order, in rules.Input, req rules.ApprovalReq, intent domain.ExtractedIntent, granted []string) error {
	r := s.Store.R()
	evidence := map[string]any{"attempt": c.AttemptNumber, "carrier": c.CarrierCode, "carrierRemark": c.CarrierRemark, "carrierReasonCode": c.CarrierReasonCode,
		"normalizedReason": c.NormalizedReason, "intent": intent, "language": c.Language}
	buyerText := ""
	if msgs, err := r.ListMessages(ctx, c.ID); err == nil {
		for i := len(msgs) - 1; i >= 0; i-- {
			if msgs[i].Direction == "INBOUND" {
				buyerText = msgs[i].OriginalText
				evidence["buyerMessage"] = msgs[i].OriginalText
				evidence["buyerMessageLanguage"] = msgs[i].Language
				break
			}
		}
	}
	if ev, err := r.GetShipmentEvent(ctx, c.ShipmentEventID); err == nil {
		evidence["attemptTime"] = ev.EventTime
		evidence["attemptLocation"] = ev.Location
		evidence["carrierDescription"] = ev.Description
	}
	if req.Kind == "DISPUTE_DRAFT" {
		evidence["disputeDraft"] = map[string]any{
			"summary":   "Buyer states no delivery attempt was made. Requesting the carrier to verify attempt GPS/timestamp, call logs and delivery-executive statement.",
			"asks":      []string{"GPS location of attempt", "call log to buyer number", "delivery executive statement", "photo evidence if any"},
			"buyerNote": buyerText, "tone": "factual; no accusation (buyer-facing messages never blame the carrier)",
		}
	}
	var granted2 []string
	for _, g := range granted {
		if slices.Contains(req.Roles, g) {
			granted2 = append(granted2, g)
		}
	}
	a, err := r.InsertApproval(ctx, store.NewApproval{CaseID: c.ID, OrderID: c.OrderID, ShipmentID: c.ShipmentID, Kind: req.Kind, BuyerRequest: buyerText, Reason: req.Reason,
		Proposed: req.Plan, Evidence: evidence, RequiredRoles: req.Roles, GrantedRoles: granted2, Blocking: req.Blocking})
	if err != nil {
		return err
	}
	if len(granted2) == len(req.Roles) { // fully pre-approved by the acting seller/ops user
		a.Status = "APPROVED"
		a.DecidedBy = actorFromCtx(ctx).Actor
		now := s.Now()
		a.DecidedAt = &now
		a.DecisionNote = "approved at request time by the acting user"
		if err := r.UpdateApproval(ctx, a); err != nil {
			return err
		}
	}
	return s.note(ctx, c, agentActor, "APPROVAL_REQUESTED", fmt.Sprintf("%s approval requested (%s): %s", strings.Join(req.Roles, "+"), req.Kind, req.Reason),
		map[string]any{"approvalId": a.ID, "kind": req.Kind, "requiredRoles": req.Roles, "blocking": req.Blocking, "status": a.Status})
}

// requestApprovals creates approval rows. If the acting user already satisfies every blocking approval
// (seller/ops-initiated actions) the plan proceeds immediately; otherwise the case waits in AWAITING_APPROVAL
// and NOTHING is sent to the carrier.
func (s *Service) requestApprovals(ctx context.Context, c *store.NDRCase, order *domain.Order, in rules.Input, d rules.Decision, intent domain.ExtractedIntent, actorRole string) error {
	var preGranted []string
	if actorRole != "" {
		preGranted = []string{actorRole}
	}
	blockingOpen := false
	for _, a := range d.Approvals {
		if err := s.createApproval(ctx, c, order, in, a, intent, preGranted); err != nil {
			return err
		}
		if a.Blocking {
			satisfied := true
			for _, role := range a.Roles {
				if role != actorRole {
					satisfied = false
				}
			}
			blockingOpen = blockingOpen || !satisfied
		}
	}
	c.ActualAction = d.ActualAction
	c.Plan = jsonRaw(d.Plan)
	c.Pending = nil
	if !blockingOpen {
		if err := s.move(ctx, c, domain.CaseActionPending, actorFromCtx(ctx), "APPROVAL_SATISFIED", "Required approvals were satisfied by the acting user; executing", map[string]any{"plan": d.Plan}); err != nil {
			return err
		}
		return s.executePlan(ctx, c, order)
	}
	if err := s.move(ctx, c, domain.CaseAwaitingApproval, agentActor, "AWAITING_APPROVAL", "Waiting for approval; the shipment is NOT modified until approved", map[string]any{"plan": d.Plan, "reason": d.Reason}); err != nil {
		return err
	}
	if actorRole == "" && intent.Intent != "" && d.BuyerKey == "approval.pending" {
		s.sendToBuyer(ctx, c, order, "approval.pending", map[string]string{"summary": rules.Summarize(d.Plan)})
	}
	return nil
}

func (s *Service) ListApprovals(ctx context.Context, status, caseRef string) ([]store.Approval, error) {
	r := s.Store.R()
	caseID := ""
	if caseRef != "" {
		c, err := s.caseByRef(ctx, r, caseRef)
		if err != nil {
			return nil, err
		}
		caseID = c.ID
	}
	return r.ListApprovals(ctx, status, caseID, 200)
}

func (s *Service) GetApproval(ctx context.Context, id string) (*store.Approval, error) {
	a, err := s.Store.R().GetApproval(ctx, id, false)
	if err == store.ErrNotFound {
		return nil, domain.NotFound("approval")
	}
	return a, err
}

// Decide records a seller/ops decision. Only users whose role is listed in required_roles may decide; a
// SELLER+OPS approval needs both roles. Role is taken from the authenticated request context.
func (s *Service) Decide(ctx context.Context, approvalID string, approve bool, note string) (*store.Approval, error) {
	actor := platform.ActorFrom(ctx)
	if actor.Role != domain.RoleSeller && actor.Role != domain.RoleOps {
		return nil, domain.Forbidden("a SELLER or OPS role is required to decide approvals")
	}
	var a *store.Approval
	err := s.Store.InTx(ctx, func(r *store.Repo) error {
		cur, err := r.GetApproval(ctx, approvalID, true)
		if err == store.ErrNotFound {
			return domain.NotFound("approval")
		} else if err != nil {
			return err
		}
		if cur.Status != "PENDING" {
			return domain.Conflict("APPROVAL_ALREADY_DECIDED", "this approval is already "+strings.ToLower(cur.Status))
		}
		if !slices.Contains(cur.RequiredRoles, actor.Role) {
			return domain.Forbidden(fmt.Sprintf("role %s may not decide this approval (requires %s)", actor.Role, strings.Join(cur.RequiredRoles, " and ")))
		}
		if slices.Contains(cur.GrantedRoles, actor.Role) {
			return domain.Conflict("ALREADY_GRANTED", "this role has already approved; waiting for the other required role")
		}
		now := s.Now()
		cur.DecisionNote = note
		if !approve {
			cur.Status, cur.DecidedBy, cur.DecidedAt = "REJECTED", actor.Name+" ("+actor.Role+")", &now
		} else {
			cur.GrantedRoles = append(cur.GrantedRoles, actor.Role)
			if len(cur.GrantedRoles) == len(cur.RequiredRoles) {
				cur.Status, cur.DecidedAt = "APPROVED", &now
			}
			cur.DecidedBy = strings.TrimSpace(cur.DecidedBy + " " + actor.Name + " (" + actor.Role + ")")
		}
		a = cur
		return r.UpdateApproval(ctx, cur)
	})
	if err != nil {
		return nil, err
	}
	s.Metrics.Inc("ndr_approvals_total", "kind", a.Kind, "status", a.Status)
	if a.Status == "PENDING" { // first of two roles
		err = s.withCase(ctx, a.CaseID, func(ctx context.Context, c *store.NDRCase) error {
			return s.note(ctx, c, actorFromCtx(ctx), "APPROVAL_PARTIAL", fmt.Sprintf("%s approved %s; waiting for %s", actor.Role, a.Kind, strings.Join(missingRoles(a), ", ")), map[string]any{"approvalId": a.ID})
		})
		return a, err
	}
	err = s.withCase(ctx, a.CaseID, func(ctx context.Context, c *store.NDRCase) error { return s.afterDecision(ctx, c, a, approve) })
	return a, err
}

func missingRoles(a *store.Approval) []string {
	var out []string
	for _, r := range a.RequiredRoles {
		if !slices.Contains(a.GrantedRoles, r) {
			out = append(out, r)
		}
	}
	return out
}

func (s *Service) afterDecision(ctx context.Context, c *store.NDRCase, a *store.Approval, approved bool) error {
	w := actorFromCtx(ctx)
	r := s.Store.R()
	order, err := r.GetOrder(ctx, c.OrderID, false)
	if err != nil {
		return err
	}
	verb := "rejected"
	if approved {
		verb = "approved"
	}
	if !a.Blocking {
		return s.note(ctx, c, w, "APPROVAL_"+strings.ToUpper(verb), fmt.Sprintf("%s %s the %s", w.Type, verb, a.Kind), map[string]any{"approvalId": a.ID, "note": a.DecisionNote})
	}
	if c.State != domain.CaseAwaitingApproval {
		return s.note(ctx, c, w, "APPROVAL_"+strings.ToUpper(verb), fmt.Sprintf("Approval %s arrived while case is %s; recorded only", verb, c.State), map[string]any{"approvalId": a.ID})
	}
	if !approved {
		c.Plan, c.ActualAction = nil, ""
		if a.Kind == "FINAL_ATTEMPT_DECISION" {
			return s.move(ctx, c, domain.CaseEscalated, w, "APPROVAL_REJECTED", "Seller declined the final-attempt decision; escalated to ops", map[string]any{"approvalId": a.ID})
		}
		if err := s.move(ctx, c, domain.CaseBuyerContactPending, w, "APPROVAL_REJECTED", fmt.Sprintf("%s rejected %s: %s", w.Type, a.Kind, a.DecisionNote), map[string]any{"approvalId": a.ID}); err != nil {
			return err
		}
		s.sendToBuyer(ctx, c, order, "approval.rejected", nil)
		return nil
	}
	// all blocking approvals for the case must be approved before anything reaches the carrier
	all, err := r.ListApprovals(ctx, "", c.ID, 100)
	if err != nil {
		return err
	}
	for _, o := range all {
		if o.ID != a.ID && o.Blocking && o.Status == "PENDING" {
			return s.note(ctx, c, w, "APPROVAL_APPROVED", "Approved; other required approvals are still pending", map[string]any{"approvalId": a.ID})
		}
	}
	var plan []domain.PlannedAction
	if err := json.Unmarshal(a.ProposedAction, &plan); err != nil || len(plan) == 0 {
		return domain.NewError(500, "BAD_APPROVAL_PLAN", "approval carries no executable plan")
	}
	c.Plan, c.ActualAction = jsonRaw(plan), string(plan[0].Type)
	if err := s.move(ctx, c, domain.CaseActionPending, w, "APPROVAL_GRANTED", fmt.Sprintf("%s approved %s; executing carrier action", w.Type, a.Kind), map[string]any{"approvalId": a.ID, "plan": plan}); err != nil {
		return err
	}
	return s.executePlan(ctx, c, order)
}
