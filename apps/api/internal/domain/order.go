package domain

import (
	"regexp"
	"strings"
	"time"
)

type Customer struct {
	Name  string `json:"name"`
	Phone string `json:"phone"`
	Email string `json:"email,omitempty"`
}

type Address struct {
	AddressLine1 string `json:"addressLine1"`
	AddressLine2 string `json:"addressLine2,omitempty"`
	City         string `json:"city"`
	State        string `json:"state"`
	Pincode      string `json:"pincode"`
}

type Package struct {
	WeightGrams int     `json:"weightGrams"`
	LengthCm    float64 `json:"lengthCm"`
	WidthCm     float64 `json:"widthCm"`
	HeightCm    float64 `json:"heightCm"`
}

type PaymentType string

const (
	PaymentCOD     PaymentType = "COD"
	PaymentPrepaid PaymentType = "PREPAID"
)

// Order is Zippy's canonical order. Carrier adapters translate it; nothing else knows carrier formats.
type Order struct {
	ID              string      `json:"id"`
	OrderID         string      `json:"orderId"` // human readable ZPY-ORD-xxxxx
	MerchantID      string      `json:"merchantId"`
	MerchantOrderID string      `json:"merchantOrderId"`
	Customer        Customer    `json:"customer"`
	PickupAddress   Address     `json:"pickupAddress"`
	DeliveryAddress Address     `json:"deliveryAddress"`
	Package         Package     `json:"package"`
	PaymentType     PaymentType `json:"paymentType"`
	CODAmount       float64     `json:"codAmount"`
	Language        string      `json:"language,omitempty"`
	Status          string      `json:"status"`

	SelectedCarrierCode string     `json:"selectedCarrierCode,omitempty"`
	SelectedServiceCode string     `json:"selectedServiceCode,omitempty"`
	QuotedAmount        *float64   `json:"quotedAmount,omitempty"`
	SelectedQuoteID     string     `json:"selectedQuoteId,omitempty"`
	SelectedAt          *time.Time `json:"selectedAt,omitempty"`
	RatesFetchedAt      *time.Time `json:"ratesFetchedAt,omitempty"`
	CreatedAt           time.Time  `json:"createdAt"`
	UpdatedAt           time.Time  `json:"updatedAt"`
}

type CreateOrderInput struct {
	MerchantOrderID string      `json:"merchantOrderId"`
	MerchantID      string      `json:"merchantId"`
	Customer        Customer    `json:"customer"`
	PickupAddress   Address     `json:"pickupAddress"`
	DeliveryAddress Address     `json:"deliveryAddress"`
	Package         Package     `json:"package"`
	PaymentType     PaymentType `json:"paymentType"`
	CODAmount       float64     `json:"codAmount"`
	Language        string      `json:"language,omitempty"`
}

var (
	phoneRe   = regexp.MustCompile(`^[6-9][0-9]{9}$`)
	pincodeRe = regexp.MustCompile(`^[1-9][0-9]{5}$`)
	emailRe   = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)
)

func ValidPhone(p string) bool   { return phoneRe.MatchString(p) }
func ValidPincode(p string) bool { return pincodeRe.MatchString(p) }

var supportedLanguages = map[string]bool{"en": true, "hi": true, "te": true, "ta": true, "kn": true}

func SupportedLanguage(l string) bool { return supportedLanguages[l] }

// Validate normalises and validates input, returning per-field messages.
func (in *CreateOrderInput) Validate() *AppError {
	f := map[string]string{}
	req := func(key, val string) {
		if strings.TrimSpace(val) == "" {
			f[key] = "is required"
		}
	}
	in.MerchantOrderID = strings.TrimSpace(in.MerchantOrderID)
	in.MerchantID = strings.TrimSpace(in.MerchantID)
	in.PaymentType = PaymentType(strings.ToUpper(string(in.PaymentType)))
	in.Language = strings.ToLower(strings.TrimSpace(in.Language))

	req("merchantOrderId", in.MerchantOrderID)
	req("merchantId", in.MerchantID)
	req("customer.name", in.Customer.Name)
	if !ValidPhone(in.Customer.Phone) {
		f["customer.phone"] = "must be a valid 10-digit Indian mobile number"
	}
	if in.Customer.Email != "" && !emailRe.MatchString(in.Customer.Email) {
		f["customer.email"] = "is not a valid email"
	}
	for prefix, a := range map[string]Address{"pickupAddress": in.PickupAddress, "deliveryAddress": in.DeliveryAddress} {
		req(prefix+".addressLine1", a.AddressLine1)
		req(prefix+".city", a.City)
		req(prefix+".state", a.State)
		if !ValidPincode(a.Pincode) {
			f[prefix+".pincode"] = "must be a valid 6-digit pincode"
		}
	}
	if in.Package.WeightGrams <= 0 {
		f["package.weightGrams"] = "must be greater than zero"
	}
	if in.Package.LengthCm <= 0 {
		f["package.lengthCm"] = "must be greater than zero"
	}
	if in.Package.WidthCm <= 0 {
		f["package.widthCm"] = "must be greater than zero"
	}
	if in.Package.HeightCm <= 0 {
		f["package.heightCm"] = "must be greater than zero"
	}
	switch in.PaymentType {
	case PaymentCOD:
		if in.CODAmount <= 0 {
			f["codAmount"] = "must be greater than zero for COD orders"
		}
	case PaymentPrepaid:
		if in.CODAmount != 0 {
			f["codAmount"] = "must be zero for PREPAID orders"
		}
	default:
		f["paymentType"] = "must be COD or PREPAID"
	}
	if in.Language != "" && !SupportedLanguage(in.Language) {
		f["language"] = "must be one of en, hi, te, ta, kn"
	}
	if len(f) > 0 {
		return Validation("order validation failed", f)
	}
	return nil
}
