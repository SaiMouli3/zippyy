package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

// CreateShipment books the selected carrier/service. It is idempotent per order: a second call returns the
// existing shipment. The order row is locked for the duration so two concurrent calls cannot double-book.
func (s *Services) CreateShipment(ctx context.Context, ref string) (*store.Shipment, bool, error) {
	var ship *store.Shipment
	created := false
	err := s.Store.InTx(ctx, func(r *store.Repo) error {
		order, err := r.GetOrder(ctx, ref, true)
		if err == store.ErrNotFound {
			return domain.NotFound("order")
		} else if err != nil {
			return err
		}
		ctx := platform.With(ctx, "orderId", order.OrderID, "carrier", order.SelectedCarrierCode)
		if existing, err := r.GetShipmentByOrder(ctx, order.ID); err == nil {
			ship = existing
			return nil
		}
		if order.SelectedQuoteID == "" || order.QuotedAmount == nil {
			return domain.NewError(http.StatusUnprocessableEntity, "CARRIER_NOT_SELECTED", "select a carrier before creating a shipment")
		}
		adapter, ok := s.Registry.Get(order.SelectedCarrierCode)
		if !ok {
			return domain.Validation("unknown carrier", map[string]string{"carrierCode": order.SelectedCarrierCode})
		}
		sq, err := r.GetQuote(ctx, order.SelectedQuoteID)
		if err != nil {
			return err
		}
		booking, err := adapter.CreateShipment(ctx, *order, sq.Quote)
		if err != nil {
			var ce *carriers.CarrierError
			if errors.As(err, &ce) {
				platform.L(ctx).Warn("carrier shipment creation failed", "event", "SHIPMENT_CREATE_FAILED", "kind", ce.Kind, "error", ce.Message)
				return domain.NewError(http.StatusBadGateway, "CARRIER_BOOKING_FAILED", "the carrier could not create the shipment").With("carrierCode", adapter.Code()).With("reason", ce.Kind).With("message", ce.Message)
			}
			return err
		}
		// the quoted amount is the stored quote's — immutable from selection time
		sh, err := r.InsertShipment(ctx, order.ID, adapter.Code(), booking.CarrierShipmentID, booking.TrackingNumber, order.SelectedServiceCode, *order.QuotedAmount, booking.LabelURL, booking.Raw)
		if err != nil {
			return err
		}
		if _, _, err := r.InsertShipmentEvent(ctx, store.NewShipmentEvent{ShipmentID: sh.ID, IdempotencyKey: adapter.Code() + ":" + booking.TrackingNumber + ":CREATED", CarrierCode: adapter.Code(),
			CarrierStatus: "CREATED", Status: domain.StatusShipmentCreated, Description: "Shipment created with carrier", EventTime: s.Now().UTC(), Raw: booking.Raw}); err != nil {
			return err
		}
		if err := r.SetOrderStatus(ctx, order.ID, string(domain.StatusShipmentCreated)); err != nil {
			return err
		}
		s.audit(ctx, r, store.AuditEntry{Action: "SHIPMENT_CREATED", OrderID: order.ID, ShipmentID: sh.ID, PreviousState: order.Status, NewState: string(domain.StatusShipmentCreated), ActorType: domain.ActorSystem, Actor: "zippy-api",
			Evidence: map[string]any{"carrier": adapter.Code(), "trackingNumber": sh.TrackingNumber, "carrierShipmentId": sh.CarrierShipmentID, "quotedAmount": sh.QuotedAmount}})
		ship, created = sh, true
		return nil
	})
	return ship, created, err
}

// ---- tracking ----

type TimelineEntry struct {
	Status      string    `json:"status"`
	Label       string    `json:"label"`
	At          time.Time `json:"at"`
	Description string    `json:"description,omitempty"`
	Location    string    `json:"location,omitempty"`
	Source      string    `json:"source"`
}

type TrackingResponse struct {
	Order          *domain.Order         `json:"order"`
	Shipment       *store.Shipment       `json:"shipment"`
	Carrier        *CarrierInfo          `json:"carrier,omitempty"`
	TrackingNumber string                `json:"trackingNumber,omitempty"`
	CurrentStatus  string                `json:"currentStatus"`
	History        []store.ShipmentEvent `json:"history"`
	Timeline       []TimelineEntry       `json:"timeline"`
	NDRCases       []store.NDRCase       `json:"ndrCases"`
}

type CarrierInfo struct {
	Code    string `json:"code"`
	Name    string `json:"name"`
	Service string `json:"service"`
}

func (s *Services) GetTracking(ctx context.Context, ref string) (*TrackingResponse, error) {
	order, err := s.GetOrder(ctx, ref)
	if err != nil {
		return nil, err
	}
	r := s.Store.R()
	resp := &TrackingResponse{Order: order, CurrentStatus: order.Status, History: []store.ShipmentEvent{}, NDRCases: []store.NDRCase{}}
	resp.Timeline = append(resp.Timeline, TimelineEntry{Status: domain.OrderCreated, Label: "Order created", At: order.CreatedAt, Source: "ZIPPY"})
	if order.RatesFetchedAt != nil {
		resp.Timeline = append(resp.Timeline, TimelineEntry{Status: domain.OrderRatesFetched, Label: "Rates fetched", At: *order.RatesFetchedAt, Source: "ZIPPY"})
	}
	if order.SelectedAt != nil {
		resp.Timeline = append(resp.Timeline, TimelineEntry{Status: domain.OrderCarrierSelected, Label: "Carrier selected", At: *order.SelectedAt, Source: "ZIPPY",
			Description: order.SelectedCarrierCode + " " + order.SelectedServiceCode})
	}
	sh, err := r.GetShipmentByOrder(ctx, order.ID)
	if err == store.ErrNotFound {
		return resp, nil
	} else if err != nil {
		return nil, err
	}
	resp.Shipment, resp.TrackingNumber, resp.CurrentStatus = sh, sh.TrackingNumber, string(sh.CurrentStatus)
	if a, ok := s.Registry.Get(sh.CarrierCode); ok {
		resp.Carrier = &CarrierInfo{Code: sh.CarrierCode, Name: a.Name(), Service: sh.ServiceCode}
	}
	events, err := r.ListShipmentEvents(ctx, sh.ID, false)
	if err != nil {
		return nil, err
	}
	resp.History = events
	for _, e := range events {
		label := string(e.NormalizedStatus)
		if e.NormalizedStatus == domain.StatusDeliveryFailed {
			label = "NDR (delivery failed)"
		}
		resp.Timeline = append(resp.Timeline, TimelineEntry{Status: string(e.NormalizedStatus), Label: label, At: e.EventTime, Description: e.Description, Location: e.Location, Source: "CARRIER"})
	}
	if cases, err := r.ListCases(ctx, store.CaseFilter{OrderID: order.OrderID}); err == nil {
		resp.NDRCases = cases
	}
	return resp, nil
}

func (s *Services) GetShipmentForRef(ctx context.Context, ref string) (*store.Shipment, error) {
	r := s.Store.R()
	if sh, err := r.GetShipment(ctx, ref); err == nil {
		return sh, nil
	}
	if o, err := r.GetOrder(ctx, ref, false); err == nil {
		if sh, err := r.GetShipmentByOrder(ctx, o.ID); err == nil {
			return sh, nil
		}
	}
	for _, c := range s.Registry.All() {
		if sh, err := r.LockShipmentByTrackingNoLock(ctx, c.Code(), ref); err == nil {
			return sh, nil
		}
	}
	return nil, domain.NotFound("shipment")
}

func (s *Services) ListShipments(ctx context.Context) ([]store.Shipment, error) {
	return s.Store.R().ListShipments(ctx, 200)
}

func deriveEventKey(ev carriers.NormalizedEvent) string {
	if ev.CarrierEventID != "" {
		return ev.CarrierCode + ":" + ev.TrackingNumber + ":" + ev.CarrierEventID
	}
	h := sha256.Sum256([]byte(ev.CarrierCode + "|" + ev.TrackingNumber + "|" + ev.CarrierStatus + "|" + ev.EventTime.UTC().Format(time.RFC3339Nano) + "|" + ev.NDRReasonCode))
	return ev.CarrierCode + ":" + ev.TrackingNumber + ":h:" + hex.EncodeToString(h[:16])
}
