package mockcarriers

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http/httptest"
	"strings"
	"testing"
)

func call(t *testing.T, s *Server, method, path, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.App().Test(req, 2000)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(resp.Body)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	return resp.StatusCode, out
}

func newServer() *Server {
	return New(Config{ZippyWebhookBase: "http://127.0.0.1:1"}, slog.New(slog.NewJSONHandler(io.Discard, nil)))
}

func TestDocumentedSamplePricesAreReproduced(t *testing.T) {
	s := newServer()
	_, fs := call(t, s, "POST", "/fastship/api/v1/rate", `{"origin_pin":"560001","destination_pin":"110001","weight_kg":1.5,"payment_mode":"COD","invoice_value":2500}`)
	svc := fs["service"].(map[string]any)
	if svc["total_amount"] != 182.9 || svc["freight_charge"] != 120.0 || svc["cod_charge"] != 35.0 || svc["tax"] != 27.9 {
		t.Fatalf("%v", svc)
	}
	_, qe := call(t, s, "POST", "/quickexpress/rates/check", `{"pickupPincode":"560001","deliveryPincode":"110001","weightInGrams":1500,"dimensions":{"length":20,"breadth":15,"height":10},"isCod":true,"collectableAmount":2500}`)
	if qe["payable"] != 197.06 || qe["quoteId"] != "QE-Q-90001" || qe["status"] != "AVAILABLE" {
		t.Fatalf("%v", qe)
	}
	_, rc := call(t, s, "GET", "/reliablecourier/shipping-options?from=560001&to=110001&weight=1500&cod=true&amount=2500", "")
	opts := rc["data"].([]any)
	surface := opts[0].(map[string]any)["rate"].(map[string]any)
	air := opts[1].(map[string]any)["rate"].(map[string]any)
	if surface["grandTotal"] != 159.3 || air["grandTotal"] != 202.96 {
		t.Fatalf("%v %v", surface, air)
	}
}

func TestPrepaidHasNoCODCharge(t *testing.T) {
	s := newServer()
	_, fs := call(t, s, "POST", "/fastship/api/v1/rate", `{"origin_pin":"560001","destination_pin":"110001","weight_kg":1.5,"payment_mode":"PREPAID","invoice_value":0}`)
	if fs["service"].(map[string]any)["cod_charge"] != 0.0 {
		t.Fatalf("%v", fs)
	}
}

func TestBadRequestsAreRejected(t *testing.T) {
	s := newServer()
	if code, _ := call(t, s, "POST", "/fastship/api/v1/rate", `{"origin_pin":"1"}`); code != 400 {
		t.Fatal(code)
	}
	if code, _ := call(t, s, "POST", "/quickexpress/booking/create", `{"clientOrderId":"X","quoteId":"NOPE","receiverDetails":{"mobileNumber":"9876543210"}}`); code != 400 {
		t.Fatal(code)
	}
}

func TestFaultInjection(t *testing.T) {
	s := newServer()
	call(t, s, "POST", "/control/config", `{"carrier":"FASTSHIP","fault":"http500"}`)
	if code, _ := call(t, s, "POST", "/fastship/api/v1/rate", `{"origin_pin":"560001","destination_pin":"110001","weight_kg":1.5,"payment_mode":"COD","invoice_value":2500}`); code != 500 {
		t.Fatal(code)
	}
	if code, _ := call(t, s, "POST", "/control/config", `{"carrier":"FASTSHIP","fault":"bogus"}`); code != 400 {
		t.Fatal("unknown fault must be rejected")
	}
	call(t, s, "POST", "/control/config", `{"carrier":"FASTSHIP","fault":""}`)
	if code, _ := call(t, s, "POST", "/fastship/api/v1/rate", `{"origin_pin":"560001","destination_pin":"110001","weight_kg":1.5,"payment_mode":"COD","invoice_value":2500}`); code != 200 {
		t.Fatal(code)
	}
}

func TestActionsAreIdempotentPerRequestIDAndHonourHoldWindow(t *testing.T) {
	s := newServer()
	_, b := call(t, s, "POST", "/fastship/api/v1/shipments", `{"reference_number":"Z1","service_code":"FAST-AIR","consignee":{"name":"R","phone":"9876543210","postal_code":"110001"}}`)
	track := b["tracking_number"].(string)
	body := `{"request_id":"k1","tracking_number":"` + track + `","preferred_date":"2000-01-01"}`
	_, a1 := call(t, s, "POST", "/fastship/api/v1/actions/reattempt", body)
	_, a2 := call(t, s, "POST", "/fastship/api/v1/actions/reattempt", body)
	if a1["reference"] != a2["reference"] || a1["action_status"] != a2["action_status"] {
		t.Fatalf("same request id must return the same decision: %v %v", a1, a2)
	}
	_, far := call(t, s, "POST", "/fastship/api/v1/actions/reattempt", `{"request_id":"k2","tracking_number":"`+track+`","preferred_date":"2999-01-01"}`)
	if far["action_status"] != "REJECTED" || !strings.Contains(far["reason"].(string), "hold window") {
		t.Fatalf("%v", far)
	}
	call(t, s, "POST", "/control/config", `{"rejectActions":true}`)
	_, rej := call(t, s, "POST", "/fastship/api/v1/actions/rto", `{"request_id":"k3","tracking_number":"`+track+`"}`)
	if rej["action_status"] != "REJECTED" {
		t.Fatalf("%v", rej)
	}
}

func TestControlTriggerBuildsCarrierNativePayloads(t *testing.T) {
	for carrier, want := range map[string]string{"FASTSHIP": "event_code", "QUICKEXPRESS": "event", "RELIABLE": "statusId"} {
		b, err := buildWebhook(carrier, &Shipment{Tracking: "T1", ShipmentID: "S1"}, triggerRequest{Event: "NDR"}, "CUST_UNAVAILABLE", timeNow())
		if err != nil || !strings.Contains(string(b), want) {
			t.Fatalf("%s: %s %v", carrier, b, err)
		}
	}
}
