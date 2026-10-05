package service

import (
	"context"
	"net/http"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type SelectCarrierInput struct {
	CarrierCode    string  `json:"carrierCode"`
	ServiceCode    string  `json:"serviceCode"`
	QuotedAmount   float64 `json:"quotedAmount"`
	QuoteReference *string `json:"quoteReference"`
}

type SelectionResult struct {
	OrderID      string  `json:"orderId"`
	Status       string  `json:"status"`
	CarrierCode  string  `json:"carrierCode"`
	ServiceCode  string  `json:"serviceCode"`
	QuotedAmount float64 `json:"quotedAmount"`
	QuoteID      string  `json:"quoteId"`
}

// SelectCarrier validates the client's choice against the server-held quote set. The client's amount is only
// ever compared to the stored one — the persisted amount is always the stored quote, never the request value.
func (s *Services) SelectCarrier(ctx context.Context, ref string, in SelectCarrierInput) (*SelectionResult, error) {
	var out *SelectionResult
	err := s.Store.InTx(ctx, func(r *store.Repo) error {
		order, err := r.GetOrder(ctx, ref, true)
		if err == store.ErrNotFound {
			return domain.NotFound("order")
		} else if err != nil {
			return err
		}
		if _, err := r.GetShipmentByOrder(ctx, order.ID); err == nil {
			return domain.Conflict("SHIPMENT_EXISTS", "a shipment already exists; the selection is immutable")
		}
		if _, ok := s.Registry.Get(in.CarrierCode); !ok {
			return domain.Validation("unknown carrier", map[string]string{"carrierCode": "is not a supported carrier"})
		}
		quotes, err := r.LatestQuotes(ctx, order.ID)
		if err != nil {
			return err
		}
		if len(quotes) == 0 {
			return domain.NewError(http.StatusUnprocessableEntity, "NO_QUOTES", "fetch rates for this order before selecting a carrier")
		}
		var match *store.StoredQuote
		serviceExists := false
		for i := range quotes {
			q := quotes[i]
			if q.CarrierCode != in.CarrierCode || q.ServiceCode != in.ServiceCode {
				continue
			}
			serviceExists = true
			if in.QuoteReference != nil && (q.QuoteReference == nil || *q.QuoteReference != *in.QuoteReference) {
				continue
			}
			match = &quotes[i]
		}
		if match == nil {
			if !serviceExists {
				return domain.NewError(http.StatusUnprocessableEntity, "QUOTE_NOT_FOUND", "the carrier/service is not part of the latest quote set for this order")
			}
			return domain.NewError(http.StatusUnprocessableEntity, "QUOTE_REFERENCE_MISMATCH", "quoteReference does not match the stored quote")
		}
		if !match.ExpiresAt.After(s.Now()) {
			return domain.Conflict("QUOTE_EXPIRED", "this quote has expired; refresh rates and select again").With("expiresAt", match.ExpiresAt)
		}
		if !domain.SameAmount(in.QuotedAmount, match.TotalCharge) {
			return domain.Conflict("QUOTED_AMOUNT_MISMATCH", "quotedAmount does not match the stored quote").
				With("storedAmount", match.TotalCharge).With("submittedAmount", in.QuotedAmount)
		}
		if err := r.SelectQuote(ctx, order.ID, *match); err != nil {
			return err
		}
		s.audit(ctx, r, store.AuditEntry{Action: "CARRIER_SELECTED", OrderID: order.ID, PreviousState: order.Status, NewState: domain.OrderCarrierSelected,
			Evidence: map[string]any{"carrier": match.CarrierCode, "service": match.ServiceCode, "quotedAmount": match.TotalCharge, "quoteId": match.ID}})
		out = &SelectionResult{OrderID: order.OrderID, Status: domain.OrderCarrierSelected, CarrierCode: match.CarrierCode, ServiceCode: match.ServiceCode, QuotedAmount: match.TotalCharge, QuoteID: match.ID}
		return nil
	})
	return out, err
}
