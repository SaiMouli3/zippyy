package domain

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// Quote is the normalized carrier quote — the only rate shape the rest of the system sees.
type Quote struct {
	ID                string     `json:"id,omitempty"`
	CarrierCode       string     `json:"carrierCode"`
	CarrierName       string     `json:"carrierName"`
	ServiceCode       string     `json:"serviceCode"`
	ServiceName       string     `json:"serviceName"`
	BaseCharge        float64    `json:"baseCharge"`
	CODCharge         float64    `json:"codCharge"`
	AdditionalCharges float64    `json:"additionalCharges"`
	Tax               float64    `json:"tax"`
	TotalCharge       float64    `json:"totalCharge"`
	EstimatedMinDays  int        `json:"estimatedMinDays"`
	EstimatedMaxDays  int        `json:"estimatedMaxDays"`
	QuoteReference    *string    `json:"quoteReference"`
	ExpiresAt         *time.Time `json:"expiresAt,omitempty"`
	Raw               []byte     `json:"-"` // raw carrier response, persisted but never returned
}

type FailureKind string

const (
	FailTimeout     FailureKind = "TIMEOUT"
	FailHTTPError   FailureKind = "HTTP_ERROR"
	FailMalformed   FailureKind = "MALFORMED_RESPONSE"
	FailUnavailable FailureKind = "UNAVAILABLE"
)

type FailedCarrier struct {
	CarrierCode string      `json:"carrierCode"`
	Kind        FailureKind `json:"reason"`
	Message     string      `json:"message"`
}

// RateResult is the aggregated outcome of asking every carrier.
type RateResult struct {
	Options        []Quote         `json:"shippingOptions"`
	FailedCarriers []FailedCarrier `json:"failedCarriers"`
	Complete       bool            `json:"complete"`
	FetchedAt      time.Time       `json:"fetchedAt"`
	ExpiresAt      time.Time       `json:"expiresAt"`
	Cached         bool            `json:"cached"`
}

type SortKey string

const (
	SortPrice   SortKey = "price"
	SortETA     SortKey = "eta"
	SortCarrier SortKey = "carrier"
)

// SortQuotes sorts in place; default (and tie-breaker) is total charge ascending.
func SortQuotes(qs []Quote, key SortKey) {
	byPrice := func(a, b Quote) int {
		switch {
		case Paise(a.TotalCharge) < Paise(b.TotalCharge):
			return -1
		case Paise(a.TotalCharge) > Paise(b.TotalCharge):
			return 1
		}
		return strings.Compare(a.CarrierCode+a.ServiceCode, b.CarrierCode+b.ServiceCode)
	}
	sort.SliceStable(qs, func(i, j int) bool {
		a, b := qs[i], qs[j]
		switch key {
		case SortETA:
			if a.EstimatedMinDays != b.EstimatedMinDays {
				return a.EstimatedMinDays < b.EstimatedMinDays
			}
			if a.EstimatedMaxDays != b.EstimatedMaxDays {
				return a.EstimatedMaxDays < b.EstimatedMaxDays
			}
		case SortCarrier:
			if a.CarrierName != b.CarrierName {
				return a.CarrierName < b.CarrierName
			}
		}
		return byPrice(a, b) < 0
	})
}

// RateCacheKey is built only from fields that influence carrier pricing.
func RateCacheKey(o Order) string {
	return fmt.Sprintf("zippy:rates:%s:%s:%s:%d:%s:%s:%s:%s:%s",
		o.MerchantID, o.PickupAddress.Pincode, o.DeliveryAddress.Pincode, o.Package.WeightGrams,
		trimFloat(o.Package.LengthCm), trimFloat(o.Package.WidthCm), trimFloat(o.Package.HeightCm),
		o.PaymentType, trimFloat(o.CODAmount))
}

func trimFloat(v float64) string {
	s := fmt.Sprintf("%.2f", v)
	s = strings.TrimRight(strings.TrimRight(s, "0"), ".")
	if s == "" {
		return "0"
	}
	return s
}
