package carriers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

func sampleOrder() domain.Order {
	return domain.Order{
		OrderID: "ZPY-ORD-10001", MerchantID: "MRC-100",
		Customer:        domain.Customer{Name: "Rahul Sharma", Phone: "9876543210"},
		PickupAddress:   domain.Address{Pincode: "560001"},
		DeliveryAddress: domain.Address{Pincode: "110001"},
		Package:         domain.Package{WeightGrams: 1500, LengthCm: 20, WidthCm: 15, HeightCm: 10},
		PaymentType:     domain.PaymentCOD, CODAmount: 2500,
	}
}

// capture spins a server that records the last request and replies with a fixed body.
type capture struct {
	srv    *httptest.Server
	method string
	path   string
	query  string
	body   map[string]any
}

func newCapture(t *testing.T, status int, resp string) *capture {
	c := &capture{}
	c.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c.method, c.path, c.query = r.Method, r.URL.Path, r.URL.RawQuery
		b, _ := io.ReadAll(r.Body)
		c.body = nil
		_ = json.Unmarshal(b, &c.body)
		w.WriteHeader(status)
		_, _ = w.Write([]byte(resp))
	}))
	t.Cleanup(c.srv.Close)
	return c
}

func cfg(url string) Config {
	return Config{BaseURL: url, Timeout: time.Second, ZippyPublicURL: "http://zippy-backend"}
}

const fsRateOK = `{"success":true,"service":{"service_code":"FAST-AIR","service_name":"FastShip Air Express","freight_charge":120.00,"cod_charge":35.00,"tax":27.90,"total_amount":182.90,"estimated_days":2}}`
const qeRateOK = `{"status":"AVAILABLE","quoteId":"QE-Q-90001","charges":{"shipping":115.00,"cod":40.00,"fuelSurcharge":12.00,"gst":30.06},"payable":197.06,"deliveryEstimate":{"minimumDays":2,"maximumDays":3},"product":"EXPRESS"}`
const rcRateOK = `{"code":200,"data":[{"id":"RC-SURFACE","name":"Reliable Surface","rate":{"base":95.00,"handling":10.00,"cashCollectionFee":30.00,"taxAmount":24.30,"grandTotal":159.30},"eta":"4-5 business days"},{"id":"RC-AIR","name":"Reliable Air","rate":{"base":130.00,"handling":12.00,"cashCollectionFee":30.00,"taxAmount":30.96,"grandTotal":202.96},"eta":"2-3 business days"}]}`

func TestFastShipRequestMappingAndNormalization(t *testing.T) {
	c := newCapture(t, 200, fsRateOK)
	qs, err := NewFastShip(cfg(c.srv.URL)).GetRates(context.Background(), sampleOrder())
	if err != nil {
		t.Fatal(err)
	}
	if c.method != "POST" || c.path != "/fastship/api/v1/rate" {
		t.Fatalf("wrong endpoint %s %s", c.method, c.path)
	}
	want := map[string]any{"origin_pin": "560001", "destination_pin": "110001", "weight_kg": 1.5, "payment_mode": "COD", "invoice_value": 2500.0}
	for k, v := range want {
		if c.body[k] != v {
			t.Errorf("request %s = %v, want %v", k, c.body[k], v)
		}
	}
	q := qs[0]
	if q.CarrierCode != "FASTSHIP" || q.ServiceCode != "FAST-AIR" || q.BaseCharge != 120 || q.CODCharge != 35 || q.AdditionalCharges != 0 || q.Tax != 27.9 || q.TotalCharge != 182.9 || q.EstimatedMinDays != 2 || q.EstimatedMaxDays != 2 || q.QuoteReference != nil {
		t.Fatalf("bad normalization: %+v", q)
	}
}

func TestQuickExpressRequestMappingAndNormalization(t *testing.T) {
	c := newCapture(t, 200, qeRateOK)
	qs, err := NewQuickExpress(cfg(c.srv.URL)).GetRates(context.Background(), sampleOrder())
	if err != nil {
		t.Fatal(err)
	}
	if c.path != "/quickexpress/rates/check" || c.body["pickupPincode"] != "560001" || c.body["weightInGrams"] != 1500.0 || c.body["isCod"] != true || c.body["collectableAmount"] != 2500.0 {
		t.Fatalf("bad request: %s %v", c.path, c.body)
	}
	dim := c.body["dimensions"].(map[string]any)
	if dim["length"] != 20.0 || dim["breadth"] != 15.0 || dim["height"] != 10.0 {
		t.Fatalf("dimensions mapped wrong: %v", dim)
	}
	q := qs[0]
	if q.ServiceCode != "EXPRESS" || q.BaseCharge != 115 || q.CODCharge != 40 || q.AdditionalCharges != 12 || q.Tax != 30.06 || q.TotalCharge != 197.06 || q.EstimatedMinDays != 2 || q.EstimatedMaxDays != 3 || q.QuoteReference == nil || *q.QuoteReference != "QE-Q-90001" {
		t.Fatalf("bad normalization: %+v", q)
	}
}

func TestReliableRequestMappingAndNormalization(t *testing.T) {
	c := newCapture(t, 200, rcRateOK)
	qs, err := NewReliable(cfg(c.srv.URL)).GetRates(context.Background(), sampleOrder())
	if err != nil {
		t.Fatal(err)
	}
	if c.method != "GET" || c.path != "/reliablecourier/shipping-options" {
		t.Fatalf("wrong endpoint %s %s", c.method, c.path)
	}
	if c.query != "amount=2500&cod=true&from=560001&to=110001&weight=1500" {
		t.Fatalf("bad query %q", c.query)
	}
	if len(qs) != 2 {
		t.Fatalf("want 2 options, got %d", len(qs))
	}
	s := qs[0]
	if s.ServiceCode != "RC-SURFACE" || s.BaseCharge != 95 || s.CODCharge != 30 || s.AdditionalCharges != 10 || s.Tax != 24.3 || s.TotalCharge != 159.3 || s.EstimatedMinDays != 4 || s.EstimatedMaxDays != 5 {
		t.Fatalf("bad normalization: %+v", s)
	}
}

func TestMalformedAndFailedRateResponses(t *testing.T) {
	cases := []struct {
		name string
		mk   func(string) Adapter
		body string
		kind domain.FailureKind
	}{
		{"fastship truncated json", func(u string) Adapter { return NewFastShip(cfg(u)) }, `{"success": true, "service"`, domain.FailMalformed},
		{"fastship missing service", func(u string) Adapter { return NewFastShip(cfg(u)) }, `{"success":true}`, domain.FailMalformed},
		{"fastship arithmetic mismatch", func(u string) Adapter { return NewFastShip(cfg(u)) }, `{"success":true,"service":{"service_code":"X","service_name":"X","freight_charge":120,"cod_charge":35,"tax":27.9,"total_amount":999,"estimated_days":2}}`, domain.FailMalformed},
		{"fastship success=false", func(u string) Adapter { return NewFastShip(cfg(u)) }, `{"success":false,"message":"no lane"}`, domain.FailUnavailable},
		{"quick not available", func(u string) Adapter { return NewQuickExpress(cfg(u)) }, `{"status":"NOT_SERVICEABLE"}`, domain.FailUnavailable},
		{"quick missing charges", func(u string) Adapter { return NewQuickExpress(cfg(u)) }, `{"status":"AVAILABLE","quoteId":"QE-Q-1","payable":10}`, domain.FailMalformed},
		{"reliable bad eta", func(u string) Adapter { return NewReliable(cfg(u)) }, `{"code":200,"data":[{"id":"A","name":"A","rate":{"base":1,"handling":0,"cashCollectionFee":0,"taxAmount":0,"grandTotal":1},"eta":"soon"}]}`, domain.FailMalformed},
		{"reliable empty", func(u string) Adapter { return NewReliable(cfg(u)) }, `{"code":200,"data":[]}`, domain.FailUnavailable},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := newCapture(t, 200, tc.body)
			_, err := tc.mk(c.srv.URL).GetRates(context.Background(), sampleOrder())
			ce, ok := err.(*CarrierError)
			if !ok || ce.Kind != tc.kind {
				t.Fatalf("want %s carrier error, got %v", tc.kind, err)
			}
		})
	}
}

func TestHTTP500AndTimeoutClassification(t *testing.T) {
	c := newCapture(t, 500, `{"error":"boom"}`)
	_, err := NewFastShip(cfg(c.srv.URL)).GetRates(context.Background(), sampleOrder())
	if ce, ok := err.(*CarrierError); !ok || ce.Kind != domain.FailHTTPError {
		t.Fatalf("want HTTP_ERROR got %v", err)
	}
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { time.Sleep(300 * time.Millisecond) }))
	defer slow.Close()
	_, err = NewQuickExpress(Config{BaseURL: slow.URL, Timeout: 50 * time.Millisecond}).GetRates(context.Background(), sampleOrder())
	if ce, ok := err.(*CarrierError); !ok || ce.Kind != domain.FailTimeout {
		t.Fatalf("want TIMEOUT got %v", err)
	}
}

func TestShipmentCreationMapping(t *testing.T) {
	order := sampleOrder()
	ref := "QE-Q-90001"

	fs := newCapture(t, 200, `{"success":true,"shipment_id":"FS-700001","tracking_number":"FST123456789","label_url":"http://x/l.pdf","status":"BOOKED"}`)
	b, err := NewFastShip(cfg(fs.srv.URL)).CreateShipment(context.Background(), order, domain.Quote{ServiceCode: "FAST-AIR"})
	if err != nil || b.CarrierShipmentID != "FS-700001" || b.TrackingNumber != "FST123456789" {
		t.Fatalf("fastship booking: %+v %v", b, err)
	}
	if fs.path != "/fastship/api/v1/shipments" || fs.body["reference_number"] != "ZPY-ORD-10001" || fs.body["service_code"] != "FAST-AIR" ||
		fs.body["callback_url"] != "http://zippy-backend/api/webhooks/fastship" {
		t.Fatalf("fastship request: %v", fs.body)
	}
	if cod := fs.body["cod"].(map[string]any); cod["enabled"] != true || cod["amount"] != 2500.0 {
		t.Fatalf("cod mapping: %v", cod)
	}

	qe := newCapture(t, 200, `{"bookingStatus":"CONFIRMED","booking":{"bookingId":"QE-B-800001","awb":"QE987654321","currentState":"SHIPMENT_CREATED"}}`)
	b, err = NewQuickExpress(cfg(qe.srv.URL)).CreateShipment(context.Background(), order, domain.Quote{ServiceCode: "EXPRESS", QuoteReference: &ref})
	if err != nil || b.CarrierShipmentID != "QE-B-800001" || b.TrackingNumber != "QE987654321" {
		t.Fatalf("quick booking: %+v %v", b, err)
	}
	if qe.body["quoteId"] != "QE-Q-90001" || qe.body["productType"] != "EXPRESS" || qe.body["webhook"] != "http://zippy-backend/api/webhooks/quickexpress" {
		t.Fatalf("quick request: %v", qe.body)
	}
	if pay := qe.body["payment"].(map[string]any); pay["mode"] != "CASH_ON_DELIVERY" || pay["amountToCollect"] != 2500.0 {
		t.Fatalf("payment mapping: %v", pay)
	}
	if _, err := NewQuickExpress(cfg(qe.srv.URL)).CreateShipment(context.Background(), order, domain.Quote{ServiceCode: "EXPRESS"}); err == nil {
		t.Fatal("quickexpress booking must require the quote reference")
	}

	rc := newCapture(t, 200, `{"result":"ACCEPTED","deliveryOrder":{"id":"RC-DO-600001","trackingCode":"RC1122334455"},"message":"ok"}`)
	b, err = NewReliable(cfg(rc.srv.URL)).CreateShipment(context.Background(), order, domain.Quote{ServiceCode: "RC-SURFACE"})
	if err != nil || b.CarrierShipmentID != "RC-DO-600001" || b.TrackingNumber != "RC1122334455" {
		t.Fatalf("reliable booking: %+v %v", b, err)
	}
	if rc.method != "PUT" || rc.path != "/reliablecourier/orders" || rc.body["selectedOption"] != "RC-SURFACE" || rc.body["collectionType"] != "COD" {
		t.Fatalf("reliable request: %s %v", rc.method, rc.body)
	}
}

func TestWebhookNormalization(t *testing.T) {
	fs := NewFastShip(Config{})
	qe := NewQuickExpress(Config{})
	rc := NewReliable(Config{})

	fsCases := map[string]domain.ShipmentStatus{"BOOKED": domain.StatusShipmentCreated, "PICKED_UP": domain.StatusPickedUp, "IN_TRANSIT": domain.StatusInTransit,
		"OUT_FOR_DELIVERY": domain.StatusOutForDelivery, "DELIVERED": domain.StatusDelivered, "DELIVERY_FAILED": domain.StatusDeliveryFailed, "RETURNED": domain.StatusRTO}
	for code, want := range fsCases {
		ev, err := fs.NormalizeWebhook([]byte(`{"shipment_id":"FS-700001","tracking_number":"FST123456789","event_code":"` + code + `","event_description":"d","event_time":"2026-07-16T10:30:00Z","location":"Bengaluru Hub"}`))
		if err != nil || ev.Status != want {
			t.Errorf("fastship %s -> %v (%v), want %s", code, ev.Status, err, want)
		}
	}
	qeCases := map[string]domain.ShipmentStatus{"SC": domain.StatusShipmentCreated, "PU": domain.StatusPickedUp, "IT": domain.StatusInTransit, "OFD": domain.StatusOutForDelivery, "DLV": domain.StatusDelivered, "NDR": domain.StatusDeliveryFailed, "RTO": domain.StatusRTO}
	for code, want := range qeCases {
		ev, err := qe.NormalizeWebhook([]byte(`{"awb":"QE987654321","event":{"type":"` + code + `","message":"m","occurredAt":"2026-07-17T08:15:00Z"},"facility":{"city":"New Delhi","code":"DEL-01"}}`))
		if err != nil || ev.Status != want {
			t.Errorf("quick %s -> %v (%v), want %s", code, ev.Status, err, want)
		}
	}
	rcCases := map[int]domain.ShipmentStatus{10: domain.StatusShipmentCreated, 20: domain.StatusPickedUp, 30: domain.StatusInTransit, 40: domain.StatusOutForDelivery, 50: domain.StatusDelivered, 60: domain.StatusDeliveryFailed, 70: domain.StatusRTO}
	for code, want := range rcCases {
		body, _ := json.Marshal(map[string]any{"trackingCode": "RC1122334455", "statusId": code, "statusText": "x", "updatedOn": "2026-07-19T15:45:00Z"})
		ev, err := rc.NormalizeWebhook(body)
		if err != nil || ev.Status != want {
			t.Errorf("reliable %d -> %v (%v), want %s", code, ev.Status, err, want)
		}
	}
	// documented sample payload
	ev, err := qe.NormalizeWebhook([]byte(`{"awb":"QE987654321","event":{"type":"OFD","message":"Shipment is out for delivery","occurredAt":"2026-07-17T08:15:00Z"},"facility":{"city":"New Delhi","code":"DEL-01"}}`))
	if err != nil || ev.TrackingNumber != "QE987654321" || ev.Location != "New Delhi DEL-01" || ev.EventTime.Hour() != 8 {
		t.Fatalf("sample payload: %+v %v", ev, err)
	}
}

func TestWebhookMalformedPayloads(t *testing.T) {
	for name, tc := range map[string]struct {
		a    Adapter
		body string
	}{
		"fastship unknown code": {NewFastShip(Config{}), `{"tracking_number":"X","event_code":"TELEPORTED","event_time":"2026-07-16T10:30:00Z"}`},
		"fastship bad time":     {NewFastShip(Config{}), `{"tracking_number":"X","event_code":"BOOKED","event_time":"yesterday"}`},
		"quick missing awb":     {NewQuickExpress(Config{}), `{"event":{"type":"PU","occurredAt":"2026-07-16T10:30:00Z"}}`},
		"reliable no status":    {NewReliable(Config{}), `{"trackingCode":"X","updatedOn":"2026-07-16T10:30:00Z"}`},
		"reliable unknown":      {NewReliable(Config{}), `{"trackingCode":"X","statusId":99,"updatedOn":"2026-07-16T10:30:00Z"}`},
		"not json":              {NewReliable(Config{}), `<xml/>`},
	} {
		if _, err := tc.a.NormalizeWebhook([]byte(tc.body)); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
}

func TestNDRReasonCodeMapping(t *testing.T) {
	ev, _ := NewFastShip(Config{}).NormalizeWebhook([]byte(`{"tracking_number":"T","event_code":"DELIVERY_FAILED","event_time":"2026-07-16T10:30:00Z","ndr_reason":"ADDRESS_INCOMPLETE","ndr_remark":"landmark missing"}`))
	if ev.NDRReason != domain.ReasonAddressIssue || ev.NDRRemark != "landmark missing" {
		t.Fatalf("fastship ndr: %+v", ev)
	}
	ev, _ = NewQuickExpress(Config{}).NormalizeWebhook([]byte(`{"awb":"T","event":{"type":"NDR","occurredAt":"2026-07-16T10:30:00Z"},"ndrDetails":{"code":"NDR-05","remarks":"no cash"}}`))
	if ev.NDRReason != domain.ReasonCODNotReady {
		t.Fatalf("quick ndr: %+v", ev)
	}
	ev, _ = NewReliable(Config{}).NormalizeWebhook([]byte(`{"trackingCode":"T","statusId":60,"updatedOn":"2026-07-16T10:30:00Z","failure":{"reasonCode":"R-14","comment":"switched off"}}`))
	if ev.NDRReason != domain.ReasonPhoneUnreachable {
		t.Fatalf("reliable ndr: %+v", ev)
	}
	ev, _ = NewFastShip(Config{}).NormalizeWebhook([]byte(`{"tracking_number":"T","event_code":"DELIVERY_FAILED","event_time":"2026-07-16T10:30:00Z","ndr_reason":"OTHER","ndr_remark":"weird"}`))
	if ev.NDRReason != "" || ev.NDRReasonCode != "OTHER" {
		t.Fatalf("unknown code must stay unmapped for remark interpretation: %+v", ev)
	}
}

func TestSubmitActionMappingAndDecisions(t *testing.T) {
	act := ActionRequest{TrackingNumber: "FST1", CarrierShipmentID: "FS-1", IdempotencyKey: "k1", Action: domain.PlannedAction{Type: domain.ActionReattempt, Date: "2026-10-06", TimeStart: "18:00", Remark: "inform guard"}}

	fs := newCapture(t, 200, `{"success":true,"action_status":"ACCEPTED","reference":"FS-ACT-1"}`)
	r, err := NewFastShip(cfg(fs.srv.URL)).SubmitAction(context.Background(), act)
	if err != nil || r.Status != domain.ActionAccepted || r.Reference != "FS-ACT-1" || fs.path != "/fastship/api/v1/actions/reattempt" || fs.body["preferred_date"] != "2026-10-06" || fs.body["request_id"] != "k1" {
		t.Fatalf("fastship action: %+v %v %s %v", r, err, fs.path, fs.body)
	}
	qe := newCapture(t, 200, `{"result":{"state":"DECLINED","message":"too late"}}`)
	r, err = NewQuickExpress(cfg(qe.srv.URL)).SubmitAction(context.Background(), act)
	if err != nil || r.Status != domain.ActionRejected || r.Reason != "too late" || qe.path != "/quickexpress/actions/reattempt" {
		t.Fatalf("quick action: %+v %v", r, err)
	}
	rc := newCapture(t, 200, `{"code":200,"data":{"decision":"APPROVED","ref":"RC-1"}}`)
	r, err = NewReliable(cfg(rc.srv.URL)).SubmitAction(context.Background(), act)
	if err != nil || r.Status != domain.ActionAccepted || rc.body["action"] != "REATTEMPT" {
		t.Fatalf("reliable action: %+v %v %v", r, err, rc.body)
	}
	bad := newCapture(t, 200, `{"result":{"state":"MAYBE"}}`)
	if _, err = NewQuickExpress(cfg(bad.srv.URL)).SubmitAction(context.Background(), act); err == nil {
		t.Fatal("unknown state must be an error, never an acceptance")
	}
}
