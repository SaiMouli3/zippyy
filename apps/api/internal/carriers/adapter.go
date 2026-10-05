// Package carriers contains the carrier adapter boundary. Only adapters know carrier wire formats;
// the rest of Zippy talks to the Adapter interface and Zippy's normalized types.
package carriers

import (
	"context"
	"sort"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

const (
	FastShip     = "FASTSHIP"
	QuickExpress = "QUICKEXPRESS"
	Reliable     = "RELIABLE"
)

// ShipmentBooking is the normalized result of creating a shipment with a carrier.
type ShipmentBooking struct {
	CarrierShipmentID string
	TrackingNumber    string
	LabelURL          string
	Raw               []byte
}

// NormalizedEvent is a carrier webhook translated into Zippy's vocabulary.
type NormalizedEvent struct {
	CarrierCode       string
	TrackingNumber    string
	CarrierShipmentID string
	CarrierStatus     string
	Status            domain.ShipmentStatus
	Description       string
	Location          string
	EventTime         time.Time
	CarrierEventID    string // empty when the carrier supplies no stable id

	// Only for DELIVERY_FAILED events.
	NDRReasonCode string           // raw carrier code
	NDRReason     domain.NDRReason // normalized; empty when the code is unknown/generic
	NDRRemark     string
}

// ActionRequest is a carrier-agnostic instruction (reattempt, reschedule, ...).
type ActionRequest struct {
	ZippyOrderID      string
	CarrierShipmentID string
	TrackingNumber    string
	IdempotencyKey    string
	Action            domain.PlannedAction
}

// Adapter is implemented once per carrier.
type Adapter interface {
	Code() string
	Name() string
	// WebhookPath is the final URL segment of /api/webhooks/{path}.
	WebhookPath() string
	GetRates(ctx context.Context, order domain.Order) ([]domain.Quote, error)
	CreateShipment(ctx context.Context, order domain.Order, quote domain.Quote) (ShipmentBooking, error)
	NormalizeWebhook(body []byte) (NormalizedEvent, error)
	SubmitAction(ctx context.Context, req ActionRequest) (domain.CarrierActionResult, error)
}

// CarrierError classifies a downstream failure so aggregators can report it without leaking formats.
type CarrierError struct {
	Kind    domain.FailureKind
	Message string
	Err     error
}

func (e *CarrierError) Error() string { return string(e.Kind) + ": " + e.Message }
func (e *CarrierError) Unwrap() error { return e.Err }

// Registry resolves adapters by carrier code or webhook path.
type Registry struct {
	byCode map[string]Adapter
	byPath map[string]Adapter
}

func NewRegistry(adapters ...Adapter) *Registry {
	r := &Registry{byCode: map[string]Adapter{}, byPath: map[string]Adapter{}}
	for _, a := range adapters {
		r.byCode[a.Code()] = a
		r.byPath[a.WebhookPath()] = a
	}
	return r
}

func (r *Registry) Get(code string) (Adapter, bool)           { a, ok := r.byCode[code]; return a, ok }
func (r *Registry) GetByWebhookPath(p string) (Adapter, bool) { a, ok := r.byPath[p]; return a, ok }

// All returns adapters in a stable order.
func (r *Registry) All() []Adapter {
	out := make([]Adapter, 0, len(r.byCode))
	for _, a := range r.byCode {
		out = append(out, a)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Code() < out[j].Code() })
	return out
}

// Config is shared by all adapters.
type Config struct {
	BaseURL        string
	Timeout        time.Duration
	ZippyPublicURL string
}
