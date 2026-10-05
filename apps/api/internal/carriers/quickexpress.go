package carriers

import (
	"context"
	"net/http"
	"strings"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// QuickExpressAdapter speaks QuickExpress's camelCase / grams / nested contract.
type QuickExpressAdapter struct {
	http *httpClient
	cfg  Config
}

func NewQuickExpress(cfg Config) *QuickExpressAdapter {
	return &QuickExpressAdapter{http: newHTTPClient(cfg), cfg: cfg}
}

func (a *QuickExpressAdapter) Code() string        { return QuickExpress }
func (a *QuickExpressAdapter) Name() string        { return "QuickExpress" }
func (a *QuickExpressAdapter) WebhookPath() string { return "quickexpress" }

type qeRateRequest struct {
	PickupPincode     string       `json:"pickupPincode"`
	DeliveryPincode   string       `json:"deliveryPincode"`
	WeightInGrams     int          `json:"weightInGrams"`
	Dimensions        qeDimensions `json:"dimensions"`
	IsCod             bool         `json:"isCod"`
	CollectableAmount float64      `json:"collectableAmount"`
}
type qeDimensions struct {
	Length  float64 `json:"length"`
	Breadth float64 `json:"breadth"`
	Height  float64 `json:"height"`
}

func (a *QuickExpressAdapter) buildRateRequest(o domain.Order) qeRateRequest {
	return qeRateRequest{
		PickupPincode: o.PickupAddress.Pincode, DeliveryPincode: o.DeliveryAddress.Pincode, WeightInGrams: o.Package.WeightGrams,
		Dimensions: qeDimensions{Length: o.Package.LengthCm, Breadth: o.Package.WidthCm, Height: o.Package.HeightCm},
		IsCod:      o.PaymentType == domain.PaymentCOD, CollectableAmount: o.CODAmount,
	}
}

func (a *QuickExpressAdapter) GetRates(ctx context.Context, o domain.Order) ([]domain.Quote, error) {
	data, status, err := a.http.do(ctx, http.MethodPost, "/quickexpress/rates/check", a.buildRateRequest(o))
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, &CarrierError{Kind: domain.FailHTTPError, Message: "QuickExpress rate API returned HTTP " + http.StatusText(status)}
	}
	return a.normalizeRates(data)
}

func (a *QuickExpressAdapter) normalizeRates(data []byte) ([]domain.Quote, error) {
	var r struct {
		Status  string `json:"status"`
		QuoteID string `json:"quoteId"`
		Charges *struct {
			Shipping      float64 `json:"shipping"`
			COD           float64 `json:"cod"`
			FuelSurcharge float64 `json:"fuelSurcharge"`
			GST           float64 `json:"gst"`
		} `json:"charges"`
		Payable          float64 `json:"payable"`
		DeliveryEstimate *struct {
			Min int `json:"minimumDays"`
			Max int `json:"maximumDays"`
		} `json:"deliveryEstimate"`
		Product string `json:"product"`
	}
	if err := decode(data, &r); err != nil {
		return nil, err
	}
	if strings.ToUpper(r.Status) != "AVAILABLE" {
		return nil, &CarrierError{Kind: domain.FailUnavailable, Message: "QuickExpress status " + r.Status}
	}
	c := r.Charges
	if c == nil || r.DeliveryEstimate == nil || r.Product == "" || r.QuoteID == "" || r.Payable <= 0 || r.DeliveryEstimate.Min <= 0 || r.DeliveryEstimate.Max < r.DeliveryEstimate.Min ||
		!nonNegative(c.Shipping, c.COD, c.FuelSurcharge, c.GST) {
		return nil, malformed("QuickExpress quote missing or invalid fields", nil)
	}
	if err := checkTotal(r.Payable, c.Shipping, c.COD, c.FuelSurcharge, c.GST); err != nil {
		return nil, err
	}
	ref := r.QuoteID
	product := strings.ToUpper(r.Product)
	return []domain.Quote{{
		CarrierCode: QuickExpress, CarrierName: "QuickExpress", ServiceCode: product,
		ServiceName: "QuickExpress " + strings.ToUpper(product[:1]) + strings.ToLower(product[1:]),
		BaseCharge:  domain.Round2(c.Shipping), CODCharge: domain.Round2(c.COD), AdditionalCharges: domain.Round2(c.FuelSurcharge),
		Tax: domain.Round2(c.GST), TotalCharge: domain.Round2(r.Payable),
		EstimatedMinDays: r.DeliveryEstimate.Min, EstimatedMaxDays: r.DeliveryEstimate.Max, QuoteReference: &ref, Raw: data,
	}}, nil
}

func (a *QuickExpressAdapter) CreateShipment(ctx context.Context, o domain.Order, q domain.Quote) (ShipmentBooking, error) {
	if q.QuoteReference == nil || *q.QuoteReference == "" {
		return ShipmentBooking{}, malformed("QuickExpress booking requires the quote reference from the accepted quote", nil)
	}
	mode := "PREPAID"
	if o.PaymentType == domain.PaymentCOD {
		mode = "CASH_ON_DELIVERY"
	}
	body := map[string]any{
		"clientOrderId":   o.OrderID,
		"quoteId":         *q.QuoteReference,
		"productType":     q.ServiceCode,
		"receiverDetails": map[string]any{"fullName": o.Customer.Name, "mobileNumber": o.Customer.Phone, "postalCode": o.DeliveryAddress.Pincode},
		"packageDetails":  map[string]any{"deadWeight": o.Package.WeightGrams, "weightUnit": "GRAM"},
		"payment":         map[string]any{"mode": mode, "amountToCollect": o.CODAmount},
		"webhook":         strings.TrimRight(a.cfg.ZippyPublicURL, "/") + "/api/webhooks/quickexpress",
	}
	data, _, err := a.http.do(ctx, http.MethodPost, "/quickexpress/booking/create", body)
	if err != nil {
		return ShipmentBooking{}, err
	}
	var r struct {
		BookingStatus string `json:"bookingStatus"`
		Message       string `json:"message"`
		Booking       *struct {
			BookingID    string `json:"bookingId"`
			AWB          string `json:"awb"`
			CurrentState string `json:"currentState"`
		} `json:"booking"`
	}
	if err := decode(data, &r); err != nil {
		return ShipmentBooking{}, err
	}
	if strings.ToUpper(r.BookingStatus) != "CONFIRMED" {
		return ShipmentBooking{}, &CarrierError{Kind: domain.FailUnavailable, Message: "QuickExpress booking " + r.BookingStatus + ": " + r.Message}
	}
	if r.Booking == nil || r.Booking.BookingID == "" || r.Booking.AWB == "" {
		return ShipmentBooking{}, malformed("QuickExpress booking response missing bookingId/awb", nil)
	}
	return ShipmentBooking{CarrierShipmentID: r.Booking.BookingID, TrackingNumber: r.Booking.AWB, Raw: data}, nil
}

var qeStatus = map[string]domain.ShipmentStatus{
	"SC": domain.StatusShipmentCreated, "PU": domain.StatusPickedUp, "IT": domain.StatusInTransit,
	"OFD": domain.StatusOutForDelivery, "DLV": domain.StatusDelivered, "NDR": domain.StatusDeliveryFailed, "RTO": domain.StatusRTO,
}

var qeNDR = map[string]domain.NDRReason{
	"NDR-01": domain.ReasonCustUnavailable, "NDR-02": domain.ReasonCustRefused, "NDR-03": domain.ReasonAddressIssue,
	"NDR-04": domain.ReasonPhoneUnreachable, "NDR-05": domain.ReasonCODNotReady, "NDR-06": domain.ReasonFutureDelivery,
	"NDR-07": domain.ReasonAccessRestricted, "NDR-08": domain.ReasonOutOfArea, "NDR-09": domain.ReasonSuspectFalse,
}

func (a *QuickExpressAdapter) NormalizeWebhook(body []byte) (NormalizedEvent, error) {
	var w struct {
		AWB   string `json:"awb"`
		Event struct {
			Type       string `json:"type"`
			Message    string `json:"message"`
			OccurredAt string `json:"occurredAt"`
			ID         string `json:"id"`
		} `json:"event"`
		Facility struct {
			City string `json:"city"`
			Code string `json:"code"`
		} `json:"facility"`
		NDRDetails *struct {
			Code    string `json:"code"`
			Remarks string `json:"remarks"`
		} `json:"ndrDetails"`
	}
	if err := decode(body, &w); err != nil {
		return NormalizedEvent{}, err
	}
	st, ok := qeStatus[strings.ToUpper(w.Event.Type)]
	if !ok {
		return NormalizedEvent{}, malformed("unknown QuickExpress event type "+w.Event.Type, nil)
	}
	if w.AWB == "" {
		return NormalizedEvent{}, malformed("webhook missing awb", nil)
	}
	t, err := parseTime(w.Event.OccurredAt)
	if err != nil {
		return NormalizedEvent{}, malformed(err.Error(), nil)
	}
	loc := strings.TrimSpace(w.Facility.City + " " + w.Facility.Code)
	ev := NormalizedEvent{CarrierCode: QuickExpress, TrackingNumber: w.AWB, CarrierStatus: strings.ToUpper(w.Event.Type), Status: st,
		Description: w.Event.Message, Location: loc, EventTime: t, CarrierEventID: w.Event.ID}
	if st == domain.StatusDeliveryFailed && w.NDRDetails != nil {
		ev.NDRReasonCode, ev.NDRRemark = w.NDRDetails.Code, w.NDRDetails.Remarks
		ev.NDRReason = qeNDR[strings.ToUpper(w.NDRDetails.Code)]
	}
	return ev, nil
}

func (a *QuickExpressAdapter) SubmitAction(ctx context.Context, r ActionRequest) (domain.CarrierActionResult, error) {
	var path string
	body := map[string]any{"requestId": r.IdempotencyKey, "awb": r.TrackingNumber, "bookingId": r.CarrierShipmentID}
	instr := map[string]any{"date": r.Action.Date, "notes": r.Action.Remark}
	if r.Action.TimeStart != "" || r.Action.TimeEnd != "" {
		instr["slot"] = map[string]any{"start": r.Action.TimeStart, "end": r.Action.TimeEnd}
	}
	switch r.Action.Type {
	case domain.ActionReattempt:
		path, body["instruction"] = "/quickexpress/actions/reattempt", instr
	case domain.ActionReschedule:
		path, body["instruction"] = "/quickexpress/actions/reschedule", instr
	case domain.ActionUpdatePhone:
		path, body["contact"] = "/quickexpress/actions/contact-update", map[string]any{"mobile": r.Action.Phone, "notes": r.Action.Remark}
	case domain.ActionUpdateAddress:
		path, body["address"] = "/quickexpress/actions/address-update", map[string]any{"street": addrLine(r.Action.Address), "landmark": r.Action.Landmark, "postalCode": addrPin(r.Action.Address), "city": addrCity(r.Action.Address)}
	case domain.ActionConvertPrepaid:
		path, body["payment"] = "/quickexpress/actions/payment-mode", map[string]any{"mode": "PREPAID"}
	case domain.ActionInitiateRTO:
		path, body["reason"] = "/quickexpress/actions/return", r.Action.Remark
	default:
		return domain.CarrierActionResult{}, malformed("unsupported action "+string(r.Action.Type), nil)
	}
	data, _, err := a.http.do(ctx, http.MethodPost, path, body)
	if err != nil {
		return domain.CarrierActionResult{}, err
	}
	var resp struct {
		Result *struct {
			State   string `json:"state"`
			Ticket  string `json:"ticket"`
			Message string `json:"message"`
		} `json:"result"`
	}
	if err := decode(data, &resp); err != nil {
		return domain.CarrierActionResult{}, err
	}
	if resp.Result == nil {
		return domain.CarrierActionResult{}, malformed("QuickExpress action response has no result", nil)
	}
	res := domain.CarrierActionResult{Reference: resp.Result.Ticket, Reason: resp.Result.Message, Response: data}
	switch strings.ToUpper(resp.Result.State) {
	case "ACCEPTED":
		res.Status = domain.ActionAccepted
	case "DECLINED":
		res.Status = domain.ActionRejected
	default:
		return res, malformed("unknown QuickExpress state "+resp.Result.State, nil)
	}
	return res, nil
}
