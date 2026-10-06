package service

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"

	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

// WebhookVerifier authenticates carrier callbacks. The default is an HMAC-SHA256 signature over the raw body.
type WebhookVerifier interface {
	Verify(carrierCode string, body []byte, signature string) error
}

type HMACVerifier struct {
	Secrets  map[string]string
	Required bool
}

var ErrBadSignature = errors.New("invalid webhook signature")

func (v HMACVerifier) Verify(carrierCode string, body []byte, signature string) error {
	secret := v.Secrets[carrierCode]
	if secret == "" {
		if v.Required {
			return ErrBadSignature // required but no secret configured: fail closed
		}
		return nil
	}
	if signature == "" {
		return ErrBadSignature
	}
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(body)
	want := hex.EncodeToString(m.Sum(nil))
	if !hmac.Equal([]byte(want), []byte(signature)) {
		return ErrBadSignature
	}
	return nil
}

type WebhookResult struct {
	Status         string `json:"status"` // processed | duplicate
	EventID        string `json:"eventId,omitempty"`
	ShipmentStatus string `json:"shipmentStatus,omitempty"`
	StateChanged   bool   `json:"stateChanged"`
	NDRCaseID      string `json:"ndrCaseId,omitempty"`
}

// HandleWebhook is the single pipeline for all carriers: verify -> normalize (adapter) -> derive idempotency
// key -> lock shipment -> transition check -> persist event -> update state -> hand NDRs to the NDR module.
func (s *Services) HandleWebhook(ctx context.Context, carrierPath string, body []byte, signature string) (*WebhookResult, error) {
	adapter, ok := s.Registry.GetByWebhookPath(carrierPath)
	if !ok {
		return nil, domain.NotFound("carrier webhook")
	}
	code := adapter.Code()
	ctx = platform.With(ctx, "carrier", code)
	log := platform.L(ctx)
	inbox := func(outcome, detail string) {
		if err := s.Store.R().InsertWebhookInbox(ctx, code, body, outcome, detail, platform.RequestID(ctx)); err != nil {
			log.Error("webhook inbox write failed", "error", err.Error())
		}
		s.Metrics.Inc("webhooks_total", "carrier", code, "outcome", outcome)
	}

	if err := s.Verifier.Verify(code, body, signature); err != nil {
		inbox("REJECTED_SIGNATURE", "signature verification failed")
		log.Warn("webhook signature rejected", "event", "WEBHOOK_REJECTED")
		return nil, domain.NewError(http.StatusUnauthorized, "INVALID_SIGNATURE", "webhook signature verification failed")
	}
	ev, err := adapter.NormalizeWebhook(body)
	if err != nil {
		inbox("MALFORMED", err.Error())
		log.Warn("malformed webhook", "event", "WEBHOOK_MALFORMED", "error", err.Error())
		return nil, domain.NewError(http.StatusBadRequest, "MALFORMED_WEBHOOK", "webhook payload could not be normalized").With("detail", err.Error())
	}
	log.Info("webhook received", "event", "WEBHOOK_RECEIVED", "trackingNumber", ev.TrackingNumber, "carrierStatus", ev.CarrierStatus, "normalizedStatus", ev.Status)
	key := deriveEventKey(ev)

	var (
		result   *WebhookResult
		rejected *domain.AppError
		newCase  string
		outcome  = "PROCESSED"
	)
	err = s.Store.InTx(ctx, func(r *store.Repo) error {
		sh, err := r.LockShipmentByTracking(ctx, code, ev.TrackingNumber, ev.CarrierShipmentID)
		if err == store.ErrNotFound {
			outcome = "UNKNOWN_TRACKING"
			return domain.NotFound("shipment for tracking number "+ev.TrackingNumber).With("trackingNumber", ev.TrackingNumber)
		} else if err != nil {
			return err
		}
		ctx := platform.With(ctx, "shipmentId", sh.ID, "orderId", sh.ZippyOrderID)

		decision := domain.CheckTransition(sh.CurrentStatus, ev.Status)
		disp := "APPLIED"
		if decision == domain.TransitionReject {
			disp = "REJECTED_TRANSITION"
		}
		evID, inserted, err := r.InsertShipmentEvent(ctx, store.NewShipmentEvent{ShipmentID: sh.ID, IdempotencyKey: key, CarrierCode: code, CarrierEventID: ev.CarrierEventID,
			CarrierStatus: ev.CarrierStatus, Status: ev.Status, Description: ev.Description, Location: ev.Location, EventTime: ev.EventTime,
			NDRReasonCode: ev.NDRReasonCode, NDRRemark: ev.NDRRemark, Disposition: disp, Raw: body})
		if err != nil {
			return err
		}
		if !inserted { // duplicate delivery: succeed without touching anything
			outcome = "DUPLICATE"
			result = &WebhookResult{Status: "duplicate", ShipmentStatus: string(sh.CurrentStatus)}
			return nil
		}
		if decision == domain.TransitionReject {
			outcome = "REJECTED_TRANSITION"
			rejected = domain.Conflict("INVALID_STATUS_TRANSITION", "carrier event would regress shipment status; stored for investigation and ignored").
				With("currentStatus", sh.CurrentStatus).With("eventStatus", ev.Status)
			s.audit(ctx, r, store.AuditEntry{Action: "WEBHOOK_TRANSITION_REJECTED", ShipmentID: sh.ID, Actor: code, ActorType: domain.ActorCarrier,
				PreviousState: string(sh.CurrentStatus), NewState: string(ev.Status), Evidence: map[string]any{"eventId": evID, "reason": "regression"}})
			return nil
		}
		result = &WebhookResult{Status: "processed", EventID: evID, ShipmentStatus: string(ev.Status)}
		if decision == domain.TransitionApply {
			if err := r.SetShipmentStatus(ctx, sh.ID, ev.Status); err != nil {
				return err
			}
			if o, err := r.GetOrder(ctx, sh.OrderID, false); err == nil {
				_ = r.SetOrderStatus(ctx, o.ID, string(ev.Status))
			}
			result.StateChanged = true
			s.audit(ctx, r, store.AuditEntry{Action: "SHIPMENT_STATUS_CHANGED", ShipmentID: sh.ID, OrderID: sh.OrderID, Actor: code, ActorType: domain.ActorCarrier,
				PreviousState: string(sh.CurrentStatus), NewState: string(ev.Status), Evidence: map[string]any{"eventId": evID, "carrierStatus": ev.CarrierStatus, "location": ev.Location}})
			updated := *sh
			updated.CurrentStatus = ev.Status
			if s.NDR != nil {
				if ev.Status == domain.StatusDeliveryFailed {
					id, err := s.NDR.OnDeliveryFailed(ctx, r, &updated, evID, ev)
					if err != nil {
						return err
					}
					newCase, result.NDRCaseID = id, id
				} else if err := s.NDR.OnShipmentStatus(ctx, r, &updated, ev.Status); err != nil {
					return err
				}
			}
		}
		return nil
	})
	if err != nil {
		if ae, ok := domain.AsAppError(err); ok && outcome == "UNKNOWN_TRACKING" {
			inbox("UNKNOWN_TRACKING", ae.Message)
			log.Warn("webhook for unknown tracking number", "event", "WEBHOOK_UNKNOWN_TRACKING", "trackingNumber", ev.TrackingNumber)
			return nil, ae
		}
		return nil, err
	}
	inbox(outcome, "")
	if rejected != nil {
		log.Warn("webhook transition rejected", "event", "WEBHOOK_TRANSITION_REJECTED", "trackingNumber", ev.TrackingNumber)
		return nil, rejected
	}
	if newCase != "" && s.NDR != nil {
		s.NDR.AfterCommit(ctx, newCase)
	}
	return result, nil
}

var _ = carriers.FastShip
