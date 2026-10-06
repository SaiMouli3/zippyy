package carriers

import (
	"context"
	"net/http"
	"strings"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// FastShipAdapter speaks FastShip's snake_case / kg contract.
type FastShipAdapter struct {
	http *httpClient
	cfg  Config
}

func NewFastShip(cfg Config) *FastShipAdapter {
	return &FastShipAdapter{http: newHTTPClient(cfg), cfg: cfg}
}

func (a *FastShipAdapter) Code() string        { return FastShip }
func (a *FastShipAdapter) Name() string        { return "FastShip" }
func (a *FastShipAdapter) WebhookPath() string { return "fastship" }

func fsPaymentMode(o domain.Order) string {
	if o.PaymentType == domain.PaymentCOD {
		return "COD"
	}
	return "PREPAID"
}

type fsRateRequest struct {
	OriginPin      string  `json:"origin_pin"`
	DestinationPin string  `json:"destination_pin"`
	WeightKg       float64 `json:"weight_kg"`
	PaymentMode    string  `json:"payment_mode"`
	InvoiceValue   float64 `json:"invoice_value"`
}

func (a *FastShipAdapter) buildRateRequest(o domain.Order) fsRateRequest {
	return fsRateRequest{
		OriginPin: o.PickupAddress.Pincode, DestinationPin: o.DeliveryAddress.Pincode,
		WeightKg: float64(o.Package.WeightGrams) / 1000, PaymentMode: fsPaymentMode(o), InvoiceValue: o.CODAmount,
	}
}

type fsRateResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Service *struct {
		ServiceCode   string  `json:"service_code"`
		ServiceName   string  `json:"service_name"`
		FreightCharge float64 `json:"freight_charge"`
		CODCharge     float64 `json:"cod_charge"`
		Tax           float64 `json:"tax"`
		TotalAmount   float64 `json:"total_amount"`
		EstimatedDays int     `json:"estimated_days"`
	} `json:"service"`
}

func (a *FastShipAdapter) GetRates(ctx context.Context, o domain.Order) ([]domain.Quote, error) {
	data, status, err := a.http.do(ctx, http.MethodPost, "/fastship/api/v1/rate", a.buildRateRequest(o))
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, &CarrierError{Kind: domain.FailHTTPError, Message: "FastShip rate API returned HTTP " + http.StatusText(status)}
	}
	return a.normalizeRates(data)
}

func (a *FastShipAdapter) normalizeRates(data []byte) ([]domain.Quote, error) {
	var r fsRateResponse
	if err := decode(data, &r); err != nil {
		return nil, err
	}
	if !r.Success {
		return nil, &CarrierError{Kind: domain.FailUnavailable, Message: "FastShip reported no service: " + r.Message}
	}
	s := r.Service
	if s == nil || s.ServiceCode == "" || s.ServiceName == "" || s.TotalAmount <= 0 || s.EstimatedDays <= 0 || !nonNegative(s.FreightCharge, s.CODCharge, s.Tax) {
		return nil, malformed("FastShip service block missing or invalid", nil)
	}
	if err := checkTotal(s.TotalAmount, s.FreightCharge, s.CODCharge, s.Tax); err != nil {
		return nil, err
	}
	return []domain.Quote{{
		CarrierCode: FastShip, CarrierName: "FastShip", ServiceCode: s.ServiceCode, ServiceName: s.ServiceName,
		BaseCharge: domain.Round2(s.FreightCharge), CODCharge: domain.Round2(s.CODCharge), AdditionalCharges: 0,
		Tax: domain.Round2(s.Tax), TotalCharge: domain.Round2(s.TotalAmount),
		EstimatedMinDays: s.EstimatedDays, EstimatedMaxDays: s.EstimatedDays, Raw: data,
	}}, nil
}

func (a *FastShipAdapter) CreateShipment(ctx context.Context, o domain.Order, q domain.Quote) (ShipmentBooking, error) {
	body := map[string]any{
		"reference_number": o.OrderID,
		"service_code":     q.ServiceCode,
		"shipper":          map[string]any{"name": "Zippy Merchant", "postal_code": o.PickupAddress.Pincode},
		"consignee":        map[string]any{"name": o.Customer.Name, "phone": o.Customer.Phone, "postal_code": o.DeliveryAddress.Pincode},
		"parcel":           map[string]any{"weight_kg": float64(o.Package.WeightGrams) / 1000},
		"cod":              map[string]any{"enabled": o.PaymentType == domain.PaymentCOD, "amount": o.CODAmount},
		"callback_url":     strings.TrimRight(a.cfg.ZippyPublicURL, "/") + "/api/webhooks/fastship",
	}
	data, status, err := a.http.do(ctx, http.MethodPost, "/fastship/api/v1/shipments", body)
	if err != nil {
		return ShipmentBooking{}, err
	}
	var r struct {
		Success    bool   `json:"success"`
		ShipmentID string `json:"shipment_id"`
		Tracking   string `json:"tracking_number"`
		LabelURL   string `json:"label_url"`
		Message    string `json:"message"`
	}
	if err := decode(data, &r); err != nil {
		return ShipmentBooking{}, err
	}
	if status != http.StatusOK && status != http.StatusCreated || !r.Success {
		return ShipmentBooking{}, &CarrierError{Kind: domain.FailUnavailable, Message: "FastShip rejected shipment: " + r.Message}
	}
	if r.ShipmentID == "" || r.Tracking == "" {
		return ShipmentBooking{}, malformed("FastShip booking response missing shipment_id/tracking_number", nil)
	}
	return ShipmentBooking{CarrierShipmentID: r.ShipmentID, TrackingNumber: r.Tracking, LabelURL: r.LabelURL, Raw: data}, nil
}

var fsStatus = map[string]domain.ShipmentStatus{
	"BOOKED": domain.StatusShipmentCreated, "PICKED_UP": domain.StatusPickedUp, "IN_TRANSIT": domain.StatusInTransit,
	"OUT_FOR_DELIVERY": domain.StatusOutForDelivery, "DELIVERED": domain.StatusDelivered,
	"DELIVERY_FAILED": domain.StatusDeliveryFailed, "RETURNED": domain.StatusRTO,
}

// FastShip NDR reason codes -> Zippy taxonomy.
var fsNDR = map[string]domain.NDRReason{
	"CONSIGNEE_UNAVAILABLE": domain.ReasonCustUnavailable, "CONSIGNEE_REFUSED": domain.ReasonCustRefused,
	"ADDRESS_INCOMPLETE": domain.ReasonAddressIssue, "PHONE_NOT_REACHABLE": domain.ReasonPhoneUnreachable,
	"COD_NOT_READY": domain.ReasonCODNotReady, "FUTURE_DELIVERY_REQUESTED": domain.ReasonFutureDelivery,
	"ACCESS_DENIED": domain.ReasonAccessRestricted, "OUT_OF_DELIVERY_AREA": domain.ReasonOutOfArea,
	"ATTEMPT_ANOMALY": domain.ReasonSuspectFalse,
}

func (a *FastShipAdapter) NormalizeWebhook(body []byte) (NormalizedEvent, error) {
	var w struct {
		ShipmentID  string `json:"shipment_id"`
		Tracking    string `json:"tracking_number"`
		EventCode   string `json:"event_code"`
		Description string `json:"event_description"`
		EventTime   string `json:"event_time"`
		Location    string `json:"location"`
		EventID     string `json:"event_id"`
		NDRReason   string `json:"ndr_reason"`
		NDRRemark   string `json:"ndr_remark"`
	}
	if err := decode(body, &w); err != nil {
		return NormalizedEvent{}, err
	}
	st, ok := fsStatus[strings.ToUpper(w.EventCode)]
	if !ok {
		return NormalizedEvent{}, malformed("unknown FastShip event_code "+w.EventCode, nil)
	}
	if w.Tracking == "" && w.ShipmentID == "" {
		return NormalizedEvent{}, malformed("webhook has neither tracking_number nor shipment_id", nil)
	}
	t, err := parseTime(w.EventTime)
	if err != nil {
		return NormalizedEvent{}, malformed(err.Error(), nil)
	}
	ev := NormalizedEvent{CarrierCode: FastShip, TrackingNumber: w.Tracking, CarrierShipmentID: w.ShipmentID, CarrierStatus: strings.ToUpper(w.EventCode),
		Status: st, Description: w.Description, Location: w.Location, EventTime: t, CarrierEventID: w.EventID}
	if st == domain.StatusDeliveryFailed {
		ev.NDRReasonCode, ev.NDRRemark = w.NDRReason, w.NDRRemark
		ev.NDRReason = fsNDR[strings.ToUpper(w.NDRReason)]
	}
	return ev, nil
}

func (a *FastShipAdapter) SubmitAction(ctx context.Context, r ActionRequest) (domain.CarrierActionResult, error) {
	var path string
	body := map[string]any{"request_id": r.IdempotencyKey, "shipment_id": r.CarrierShipmentID, "tracking_number": r.TrackingNumber, "remark": r.Action.Remark}
	switch r.Action.Type {
	case domain.ActionReattempt, domain.ActionReschedule:
		path = "/fastship/api/v1/actions/reattempt"
		if r.Action.Type == domain.ActionReschedule {
			path = "/fastship/api/v1/actions/reschedule"
		}
		body["preferred_date"] = r.Action.Date
		if r.Action.TimeStart != "" || r.Action.TimeEnd != "" {
			body["time_window"] = map[string]any{"from": r.Action.TimeStart, "to": r.Action.TimeEnd}
		}
	case domain.ActionUpdatePhone:
		path = "/fastship/api/v1/actions/update-phone"
		body["new_phone"] = r.Action.Phone
	case domain.ActionUpdateAddress:
		path = "/fastship/api/v1/actions/update-address"
		body["new_address"] = map[string]any{"line1": addrLine(r.Action.Address), "landmark": r.Action.Landmark, "postal_code": addrPin(r.Action.Address), "city": addrCity(r.Action.Address)}
	case domain.ActionConvertPrepaid:
		path = "/fastship/api/v1/actions/convert-prepaid"
	case domain.ActionInitiateRTO:
		path = "/fastship/api/v1/actions/rto"
	default:
		return domain.CarrierActionResult{}, malformed("unsupported action "+string(r.Action.Type), nil)
	}
	data, _, err := a.http.do(ctx, http.MethodPost, path, body)
	if err != nil {
		return domain.CarrierActionResult{}, err
	}
	var resp struct {
		Success      bool   `json:"success"`
		ActionStatus string `json:"action_status"`
		Reference    string `json:"reference"`
		Reason       string `json:"reason"`
	}
	if err := decode(data, &resp); err != nil {
		return domain.CarrierActionResult{}, err
	}
	res := domain.CarrierActionResult{Reference: resp.Reference, Reason: resp.Reason, Response: data}
	switch strings.ToUpper(resp.ActionStatus) {
	case "ACCEPTED":
		res.Status = domain.ActionAccepted
	case "REJECTED":
		res.Status = domain.ActionRejected
	default:
		return res, malformed("unknown FastShip action_status "+resp.ActionStatus, nil)
	}
	return res, nil
}

func addrLine(a *domain.Address) string {
	if a == nil {
		return ""
	}
	return a.AddressLine1
}
func addrPin(a *domain.Address) string {
	if a == nil {
		return ""
	}
	return a.Pincode
}
func addrCity(a *domain.Address) string {
	if a == nil {
		return ""
	}
	return a.City
}
