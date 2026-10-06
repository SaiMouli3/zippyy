package service

import (
	"context"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type RatesResponse struct {
	OrderID         string                 `json:"orderId"`
	Complete        bool                   `json:"complete"`
	ShippingOptions []domain.Quote         `json:"shippingOptions"`
	FailedCarriers  []domain.FailedCarrier `json:"failedCarriers"`
	Cached          bool                   `json:"cached"`
	FetchedAt       *time.Time             `json:"fetchedAt,omitempty"`
	ExpiresAt       *time.Time             `json:"expiresAt,omitempty"`
	Expired         bool                   `json:"expired"`
	CacheKey        string                 `json:"cacheKey,omitempty"`
}

func sortedCopy(qs []domain.Quote, key domain.SortKey) []domain.Quote {
	out := append([]domain.Quote(nil), qs...)
	domain.SortQuotes(out, key)
	return out
}

// FetchRates aggregates carrier rates (cache-aware) and persists them as the order's latest quote set.
func (s *Services) FetchRates(ctx context.Context, ref string, refresh bool, sortKey domain.SortKey) (*RatesResponse, error) {
	order, err := s.GetOrder(ctx, ref)
	if err != nil {
		return nil, err
	}
	if s.hasShipment(ctx, order.ID) {
		return nil, domain.Conflict("SHIPMENT_EXISTS", "a shipment has already been created for this order; rates are locked")
	}
	ctx = platform.With(ctx, "orderId", order.OrderID)
	res, err := s.Rates.GetRates(ctx, *order, refresh)
	if err != nil {
		return nil, err
	}
	// Persist this order's own snapshot of the quote set. The expiry follows the cache entry so a quote
	// served from a nearly-expired cache entry is not valid for longer than the price was.
	err = s.Store.InTx(ctx, func(r *store.Repo) error {
		if _, err := r.InsertQuoteGroup(ctx, order.ID, res.CacheKey, res.Options, res.Raws, res.ExpiresAt); err != nil {
			return err
		}
		s.audit(ctx, r, store.AuditEntry{Action: "RATES_FETCHED", OrderID: order.ID, Evidence: map[string]any{"cached": res.Cached, "options": len(res.Options), "failedCarriers": res.FailedCarriers, "refresh": refresh}})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return s.GetRates(ctx, ref, sortKey, &res.RateResult, res.CacheKey)
}

func (s *Services) hasShipment(ctx context.Context, orderID string) bool {
	_, err := s.Store.R().GetShipmentByOrder(ctx, orderID)
	return err == nil
}

// GetRates returns the order's latest persisted quote set (no carrier calls).
func (s *Services) GetRates(ctx context.Context, ref string, sortKey domain.SortKey, agg *domain.RateResult, cacheKey string) (*RatesResponse, error) {
	order, err := s.GetOrder(ctx, ref)
	if err != nil {
		return nil, err
	}
	stored, err := s.Store.R().LatestQuotes(ctx, order.ID)
	if err != nil {
		return nil, err
	}
	if len(stored) == 0 {
		return nil, domain.NotFound("rates for this order (call POST /rates first)")
	}
	quotes := make([]domain.Quote, len(stored))
	for i, q := range stored {
		quotes[i] = q.Quote
	}
	domain.SortQuotes(quotes, sortKey)
	resp := &RatesResponse{OrderID: order.OrderID, ShippingOptions: quotes, FailedCarriers: []domain.FailedCarrier{}, CacheKey: cacheKey}
	exp := stored[0].ExpiresAt
	created := stored[0].CreatedAt
	resp.ExpiresAt, resp.FetchedAt = exp, &created
	resp.Expired = exp != nil && !exp.After(s.Now())
	if agg != nil {
		resp.Complete, resp.Cached = agg.Complete, agg.Cached
		resp.FailedCarriers = agg.FailedCarriers
		if resp.FailedCarriers == nil {
			resp.FailedCarriers = []domain.FailedCarrier{}
		}
		return resp, nil
	}
	// Reconstruct completeness for a later GET: a registered carrier absent from the set did not quote.
	present := map[string]bool{}
	for _, q := range quotes {
		present[q.CarrierCode] = true
	}
	for _, a := range s.Registry.All() {
		if !present[a.Code()] {
			resp.FailedCarriers = append(resp.FailedCarriers, domain.FailedCarrier{CarrierCode: a.Code(), Kind: domain.FailUnavailable, Message: "carrier did not return a quote in the latest set"})
		}
	}
	resp.Complete = len(resp.FailedCarriers) == 0
	return resp, nil
}
