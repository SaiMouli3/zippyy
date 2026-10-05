package carriers

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// ReliableCourierAdapter speaks ReliableCourier's GET + nested envelope contract.
type ReliableCourierAdapter struct {
	http *httpClient
	cfg  Config
}

func NewReliable(cfg Config) *ReliableCourierAdapter {
	return &ReliableCourierAdapter{http: newHTTPClient(cfg), cfg: cfg}
}

func (a *ReliableCourierAdapter) Code() string        { return Reliable }
func (a *ReliableCourierAdapter) Name() string        { return "ReliableCourier" }
func (a *ReliableCourierAdapter) WebhookPath() string { return "reliable" }

func (a *ReliableCourierAdapter) buildRateQuery(o domain.Order) string {
	q := url.Values{}
	q.Set("from", o.PickupAddress.Pincode)
	q.Set("to", o.DeliveryAddress.Pincode)
	q.Set("weight", strconv.Itoa(o.Package.WeightGrams))
	q.Set("cod", strconv.FormatBool(o.PaymentType == domain.PaymentCOD))
	q.Set("amount", strconv.FormatFloat(o.CODAmount, 'f', -1, 64))
	return q.Encode()
}

func (a *ReliableCourierAdapter) GetRates(ctx context.Context, o domain.Order) ([]domain.Quote, error) {
	data, status, err := a.http.do(ctx, http.MethodGet, "/reliablecourier/shipping-options?"+a.buildRateQuery(o), nil)
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, &CarrierError{Kind: domain.FailHTTPError, Message: "ReliableCourier returned HTTP " + http.StatusText(status)}
	}
	return a.normalizeRates(data)
}

func (a *ReliableCourierAdapter) normalizeRates(data []byte) ([]domain.Quote, error) {
	var r struct {
		Code int `json:"code"`
		Data []struct {
			ID   string `json:"id"`
			Name string `json:"name"`
			Rate *struct {
				Base      float64 `json:"base"`
				Handling  float64 `json:"handling"`
				CashFee   float64 `json:"cashCollectionFee"`
				TaxAmount float64 `json:"taxAmount"`
				Grand     float64 `json:"grandTotal"`
			} `json:"rate"`
			ETA string `json:"eta"`
		} `json:"data"`
	}
	if err := decode(data, &r); err != nil {
		return nil, err
	}
	if r.Code != 200 {
		return nil, &CarrierError{Kind: domain.FailUnavailable, Message: fmt.Sprintf("ReliableCourier envelope code %d", r.Code)}
	}
	if len(r.Data) == 0 {
		return nil, &CarrierError{Kind: domain.FailUnavailable, Message: "ReliableCourier returned no shipping options"}
	}
	out := make([]domain.Quote, 0, len(r.Data))
	for _, d := range r.Data {
		if d.ID == "" || d.Name == "" || d.Rate == nil || d.Rate.Grand <= 0 || !nonNegative(d.Rate.Base, d.Rate.Handling, d.Rate.CashFee, d.Rate.TaxAmount) {
			return nil, malformed("ReliableCourier option missing or invalid fields", nil)
		}
		lo, hi, ok := parseETA(d.ETA)
		if !ok {
			return nil, malformed("cannot parse ReliableCourier eta "+d.ETA, nil)
		}
		if err := checkTotal(d.Rate.Grand, d.Rate.Base, d.Rate.Handling, d.Rate.CashFee, d.Rate.TaxAmount); err != nil {
			return nil, err
		}
		out = append(out, domain.Quote{
			CarrierCode: Reliable, CarrierName: "ReliableCourier", ServiceCode: d.ID, ServiceName: d.Name,
			BaseCharge: domain.Round2(d.Rate.Base), CODCharge: domain.Round2(d.Rate.CashFee), AdditionalCharges: domain.Round2(d.Rate.Handling),
			Tax: domain.Round2(d.Rate.TaxAmount), TotalCharge: domain.Round2(d.Rate.Grand), EstimatedMinDays: lo, EstimatedMaxDays: hi,
			Raw: data,
		})
	}
	return out, nil
}

func (a *ReliableCourierAdapter) CreateShipment(ctx context.Context, o domain.Order, q domain.Quote) (ShipmentBooking, error) {
	coll := "PREPAID"
	if o.PaymentType == domain.PaymentCOD {
		coll = "COD"
	}
	body := map[string]any{
		"orderReference":        o.OrderID,
		"selectedOption":        q.ServiceCode,
		"destination":           map[string]any{"contact": o.Customer.Name, "phone": o.Customer.Phone, "zip": o.DeliveryAddress.Pincode},
		"parcelWeight":          map[string]any{"value": float64(o.Package.WeightGrams) / 1000, "unit": "KG"},
		"collectionType":        coll,
		"collectionAmount":      o.CODAmount,
		"statusNotificationUrl": strings.TrimRight(a.cfg.ZippyPublicURL, "/") + "/api/webhooks/reliable",
	}
	data, _, err := a.http.do(ctx, http.MethodPut, "/reliablecourier/orders", body)
	if err != nil {
		return ShipmentBooking{}, err
	}
	var r struct {
		Result        string `json:"result"`
		Message       string `json:"message"`
		DeliveryOrder *struct {
			ID           string `json:"id"`
			TrackingCode string `json:"trackingCode"`
		} `json:"deliveryOrder"`
	}
	if err := decode(data, &r); err != nil {
		return ShipmentBooking{}, err
	}
	if strings.ToUpper(r.Result) != "ACCEPTED" {
		return ShipmentBooking{}, &CarrierError{Kind: domain.FailUnavailable, Message: "ReliableCourier " + r.Result + ": " + r.Message}
	}
	if r.DeliveryOrder == nil || r.DeliveryOrder.ID == "" || r.DeliveryOrder.TrackingCode == "" {
		return ShipmentBooking{}, malformed("ReliableCourier response missing deliveryOrder id/trackingCode", nil)
	}
	return ShipmentBooking{CarrierShipmentID: r.DeliveryOrder.ID, TrackingNumber: r.DeliveryOrder.TrackingCode, Raw: data}, nil
}

var rcStatus = map[int]domain.ShipmentStatus{
	10: domain.StatusShipmentCreated, 20: domain.StatusPickedUp, 30: domain.StatusInTransit, 40: domain.StatusOutForDelivery,
	50: domain.StatusDelivered, 60: domain.StatusDeliveryFailed, 70: domain.StatusRTO,
}

var rcNDR = map[string]domain.NDRReason{
	"R-11": domain.ReasonCustUnavailable, "R-12": domain.ReasonCustRefused, "R-13": domain.ReasonAddressIssue,
	"R-14": domain.ReasonPhoneUnreachable, "R-15": domain.ReasonCODNotReady, "R-16": domain.ReasonFutureDelivery,
	"R-17": domain.ReasonAccessRestricted, "R-18": domain.ReasonOutOfArea, "R-19": domain.ReasonSuspectFalse,
}

func (a *ReliableCourierAdapter) NormalizeWebhook(body []byte) (NormalizedEvent, error) {
	var w struct {
		TrackingCode string `json:"trackingCode"`
		StatusID     *int   `json:"statusId"`
		StatusText   string `json:"statusText"`
		UpdatedOn    string `json:"updatedOn"`
		EventRef     string `json:"eventRef"`
		Hub          string `json:"hub"`
		POD          *struct {
			DeliveryLocation string `json:"deliveryLocation"`
		} `json:"proofOfDelivery"`
		Failure *struct {
			ReasonCode string `json:"reasonCode"`
			Comment    string `json:"comment"`
		} `json:"failure"`
	}
	if err := decode(body, &w); err != nil {
		return NormalizedEvent{}, err
	}
	if w.StatusID == nil {
		return NormalizedEvent{}, malformed("webhook missing statusId", nil)
	}
	st, ok := rcStatus[*w.StatusID]
	if !ok {
		return NormalizedEvent{}, malformed("unknown ReliableCourier statusId "+strconv.Itoa(*w.StatusID), nil)
	}
	if w.TrackingCode == "" {
		return NormalizedEvent{}, malformed("webhook missing trackingCode", nil)
	}
	t, err := parseTime(w.UpdatedOn)
	if err != nil {
		return NormalizedEvent{}, malformed(err.Error(), nil)
	}
	loc := w.Hub
	if w.POD != nil && w.POD.DeliveryLocation != "" {
		loc = w.POD.DeliveryLocation
	}
	ev := NormalizedEvent{CarrierCode: Reliable, TrackingNumber: w.TrackingCode, CarrierStatus: strconv.Itoa(*w.StatusID), Status: st,
		Description: w.StatusText, Location: loc, EventTime: t, CarrierEventID: w.EventRef}
	if st == domain.StatusDeliveryFailed && w.Failure != nil {
		ev.NDRReasonCode, ev.NDRRemark = w.Failure.ReasonCode, w.Failure.Comment
		ev.NDRReason = rcNDR[strings.ToUpper(w.Failure.ReasonCode)]
	}
	return ev, nil
}

var rcActionName = map[domain.ActionType]string{
	domain.ActionReattempt: "REATTEMPT", domain.ActionReschedule: "RESCHEDULE", domain.ActionUpdatePhone: "CONTACT_CHANGE",
	domain.ActionUpdateAddress: "ADDRESS_CHANGE", domain.ActionConvertPrepaid: "PAYMENT_CONVERSION", domain.ActionInitiateRTO: "RETURN",
}

func (a *ReliableCourierAdapter) SubmitAction(ctx context.Context, r ActionRequest) (domain.CarrierActionResult, error) {
	name, ok := rcActionName[r.Action.Type]
	if !ok {
		return domain.CarrierActionResult{}, malformed("unsupported action "+string(r.Action.Type), nil)
	}
	params := map[string]any{}
	if r.Action.Date != "" {
		params["deliveryDate"] = r.Action.Date
	}
	if r.Action.Phone != "" {
		params["phone"] = r.Action.Phone
	}
	if r.Action.Address != nil {
		params["address"] = map[string]any{"line": r.Action.Address.AddressLine1, "zip": r.Action.Address.Pincode, "city": r.Action.Address.City, "landmark": r.Action.Landmark}
	}
	body := map[string]any{"requestKey": r.IdempotencyKey, "trackingCode": r.TrackingNumber, "orderRef": r.CarrierShipmentID, "action": name, "params": params, "note": r.Action.Remark}
	data, _, err := a.http.do(ctx, http.MethodPost, "/reliablecourier/actions", body)
	if err != nil {
		return domain.CarrierActionResult{}, err
	}
	var resp struct {
		Code int `json:"code"`
		Data *struct {
			Decision string `json:"decision"`
			Ref      string `json:"ref"`
			Reason   string `json:"reason"`
		} `json:"data"`
	}
	if err := decode(data, &resp); err != nil {
		return domain.CarrierActionResult{}, err
	}
	if resp.Data == nil {
		return domain.CarrierActionResult{}, malformed("ReliableCourier action response has no data", nil)
	}
	res := domain.CarrierActionResult{Reference: resp.Data.Ref, Reason: resp.Data.Reason, Response: data}
	switch strings.ToUpper(resp.Data.Decision) {
	case "APPROVED":
		res.Status = domain.ActionAccepted
	case "DENIED":
		res.Status = domain.ActionRejected
	default:
		return res, malformed("unknown ReliableCourier decision "+resp.Data.Decision, nil)
	}
	return res, nil
}
