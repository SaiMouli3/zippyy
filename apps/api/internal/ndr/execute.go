package ndr

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

func (s *Service) submitWithRetry(ctx context.Context, ad carriers.Adapter, req carriers.ActionRequest) (domain.CarrierActionResult, error) {
	var res domain.CarrierActionResult
	var err error
	for i := 0; i < s.Cfg.ActionRetries; i++ {
		res, err = ad.SubmitAction(ctx, req)
		if err == nil {
			return res, nil
		}
		var ce *carriers.CarrierError
		if !errors.As(err, &ce) || ce.Kind == domain.FailMalformed {
			return res, err
		}
		platform.L(ctx).Warn("carrier action failed, will retry with the same idempotency key", "event", "CARRIER_ACTION_RETRY", "attempt", i+1, "kind", ce.Kind)
		select {
		case <-time.After(s.Cfg.RetryBackoff << i):
		case <-ctx.Done():
			return res, ctx.Err()
		}
	}
	return res, err
}

// executePlan submits each planned action to the carrier in order. The case only advances to
// CARRIER_ACCEPTED / REATTEMPT_SCHEDULED after the carrier answers ACCEPTED, and the buyer is only told the
// carrier "accepted" after that. Before acceptance the buyer is only told the request was "submitted".
func (s *Service) executePlan(ctx context.Context, c *store.NDRCase, order *domain.Order) error {
	var plan []domain.PlannedAction
	if err := json.Unmarshal(c.Plan, &plan); err != nil || len(plan) == 0 {
		return domain.NewError(422, "NO_PLAN", "case has no planned carrier actions")
	}
	adapter, ok := s.Registry.Get(c.CarrierCode)
	if !ok {
		return domain.Validation("unknown carrier", map[string]string{"carrier": c.CarrierCode})
	}
	r := s.Store.R()
	sh, err := r.GetShipment(ctx, c.ShipmentID)
	if err != nil {
		return err
	}
	hash := sha256.Sum256(c.Plan)
	planHash := hex.EncodeToString(hash[:6])
	summary := rules.Summarize(plan)
	told := false

	for idx, act := range plan {
		if c.State != domain.CaseActionPending {
			if err := s.move(ctx, c, domain.CaseActionPending, agentActor, "ACTION_PENDING", "Next carrier action queued: "+string(act.Type), map[string]any{"index": idx}); err != nil {
				return err
			}
		}
		existing, err := r.ListActions(ctx, c.ID)
		if err != nil {
			return err
		}
		prefix := fmt.Sprintf("%s:%s:%d:", c.ID, planHash, idx)
		retry := 0
		for _, e := range existing {
			if strings.HasPrefix(e.IdempotencyKey, prefix) && e.Status != "ACCEPTED" && e.Status != "PENDING" {
				retry++
			}
		}
		key := fmt.Sprintf("%sr%d", prefix, retry)
		row, _, err := r.GetOrCreateAction(ctx, c.ID, c.ShipmentID, c.CarrierCode, act, key)
		if err != nil {
			return err
		}
		if row.Status == "ACCEPTED" { // resume after a crash: already done
			if err := s.move(ctx, c, domain.CaseActionSubmitted, agentActor, "ACTION_RESUMED", "Action already accepted earlier; resuming", nil); err != nil {
				return err
			}
			if err := s.move(ctx, c, domain.CaseCarrierAccepted, carrierActor(c.CarrierCode), "CARRIER_ACCEPTED", fmt.Sprintf("%s was already accepted by the carrier", act.Type), map[string]any{"reference": row.CarrierReference}); err != nil {
				return err
			}
			continue
		}
		if err := s.move(ctx, c, domain.CaseActionSubmitted, agentActor, "ACTION_SUBMITTED", fmt.Sprintf("Submitted %s to %s", act.Type, c.CarrierCode),
			map[string]any{"action": act, "idempotencyKey": key}); err != nil {
			return err
		}
		if !told {
			told = true
			s.sendToBuyer(ctx, c, order, "submitted", map[string]string{"summary": summary})
		}
		req := carriers.ActionRequest{ZippyOrderID: c.ZippyOrderID, CarrierShipmentID: sh.CarrierShipmentID, TrackingNumber: sh.TrackingNumber, IdempotencyKey: key, Action: act}
		reqJSON, _ := json.Marshal(req)
		start := time.Now()
		res, err := s.submitWithRetry(ctx, adapter, req)
		s.Metrics.Observe("carrier_action_latency", time.Since(start), "carrier", c.CarrierCode, "action", string(act.Type))
		if err != nil {
			_ = r.FinishAction(ctx, row.ID, "FAILED", reqJSON, nil, "", err.Error())
			s.Metrics.Inc("carrier_actions_total", "carrier", c.CarrierCode, "action", string(act.Type), "status", "FAILED")
			_ = r.InsertAudit(ctx, store.AuditEntry{Actor: "zippy-agent", ActorType: domain.ActorAgent, Action: "CARRIER_ACTION_FAILED", OrderID: c.OrderID, ShipmentID: c.ShipmentID, NDRCaseID: c.ID,
				PreviousState: string(c.State), RequestPayload: json.RawMessage(reqJSON), Evidence: map[string]any{"error": err.Error()}, RequestID: platform.RequestID(ctx)})
			if e := s.move(ctx, c, domain.CaseEscalated, agentActor, "ACTION_FAILED", fmt.Sprintf("Carrier call for %s failed: %s", act.Type, err.Error()), map[string]any{"action": act}); e != nil {
				return e
			}
			s.sendToBuyer(ctx, c, order, "rejected.carrier", nil)
			return nil
		}
		status := string(res.Status)
		_ = r.FinishAction(ctx, row.ID, status, reqJSON, res.Response, res.Reference, res.Reason)
		s.Metrics.Inc("carrier_actions_total", "carrier", c.CarrierCode, "action", string(act.Type), "status", status)
		_ = r.InsertAudit(ctx, store.AuditEntry{Actor: c.CarrierCode, ActorType: domain.ActorCarrier, Action: "CARRIER_ACTION_" + status, OrderID: c.OrderID, ShipmentID: c.ShipmentID, NDRCaseID: c.ID,
			PreviousState: string(c.State), RequestPayload: json.RawMessage(reqJSON), ResponsePayload: json.RawMessage(res.Response), Evidence: map[string]any{"reference": res.Reference, "reason": res.Reason}, RequestID: platform.RequestID(ctx)})
		if res.Status != domain.ActionAccepted {
			if e := s.move(ctx, c, domain.CaseEscalated, carrierActor(c.CarrierCode), "CARRIER_REJECTED", fmt.Sprintf("Carrier rejected %s: %s", act.Type, res.Reason), map[string]any{"action": act, "reason": res.Reason}); e != nil {
				return e
			}
			s.sendToBuyer(ctx, c, order, "rejected.carrier", nil)
			return nil
		}
		if err := s.applyAcceptedSideEffects(ctx, c, order, act); err != nil {
			return err
		}
		if err := s.move(ctx, c, domain.CaseCarrierAccepted, carrierActor(c.CarrierCode), "CARRIER_ACCEPTED", fmt.Sprintf("Carrier accepted %s (ref %s)", act.Type, res.Reference),
			map[string]any{"action": act, "reference": res.Reference}); err != nil {
			return err
		}
	}

	// every action was accepted: now (and only now) tell the buyer the carrier accepted
	c.Plan, c.Pending = nil, nil
	var lastDelivery *domain.PlannedAction
	rto := false
	for i := range plan {
		switch plan[i].Type {
		case domain.ActionReattempt, domain.ActionReschedule:
			lastDelivery = &plan[i]
		case domain.ActionInitiateRTO:
			rto = true
		}
	}
	switch {
	case rto:
		if err := s.move(ctx, c, domain.CaseRTOInitiated, agentActor, "RTO_INITIATED", "Carrier accepted the return (RTO) instruction", nil); err != nil {
			return err
		}
		s.sendToBuyer(ctx, c, order, "accepted.rto", nil)
	case lastDelivery != nil:
		if err := s.move(ctx, c, domain.CaseReattemptScheduled, agentActor, "REATTEMPT_SCHEDULED", "Reattempt scheduled with the carrier for "+lastDelivery.Date, map[string]any{"date": lastDelivery.Date}); err != nil {
			return err
		}
		s.sendToBuyer(ctx, c, order, "accepted.reattempt", map[string]string{"date": humanDate(lastDelivery.Date), "timeNote": timeNote(*lastDelivery)})
	default:
		if err := s.Store.R().SaveCase(ctx, c); err != nil {
			return err
		}
		s.sendToBuyer(ctx, c, order, "accepted.generic", map[string]string{"summary": summary})
	}
	return nil
}

func humanDate(iso string) string {
	t, err := time.Parse("2006-01-02", iso)
	if err != nil {
		return iso
	}
	return t.Format("02 Jan 2006")
}

func timeNote(a domain.PlannedAction) string {
	switch {
	case a.TimeStart != "" && a.TimeEnd != "":
		return " (" + a.TimeStart + "-" + a.TimeEnd + ")"
	case a.TimeStart != "":
		return " (after " + a.TimeStart + ")"
	case a.TimeEnd != "":
		return " (before " + a.TimeEnd + ")"
	}
	return ""
}

// applyAcceptedSideEffects mirrors accepted carrier changes into Zippy's own records — only after acceptance.
func (s *Service) applyAcceptedSideEffects(ctx context.Context, c *store.NDRCase, order *domain.Order, a domain.PlannedAction) error {
	r := s.Store.R()
	switch a.Type {
	case domain.ActionUpdatePhone:
		if err := r.SetBuyerAlternatePhone(ctx, order.Customer.Phone, a.Phone); err != nil {
			return err
		}
		return r.SetOrderPhone(ctx, order.ID, a.Phone)
	case domain.ActionUpdateAddress:
		if a.Address != nil {
			return r.SetOrderDeliveryAddress(ctx, order.ID, *a.Address)
		}
	case domain.ActionConvertPrepaid:
		return r.SetOrderPaymentPrepaid(ctx, order.ID)
	}
	return nil
}
