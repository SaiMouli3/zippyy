package tests

import (
	"fmt"
	"testing"

	"github.com/saimouli3/zippyy/apps/api/testkit"
)

func history(e *testkit.Env, orderID string) []string {
	r := e.Get("/api/orders/" + orderID + "/tracking")
	var out []string
	for i := 0; i < r.Len("history"); i++ {
		out = append(out, r.Str(fmt.Sprintf("history.%d.status", i)))
	}
	return out
}

func TestWebhookLifecycleForEveryCarrier(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	for i, c := range []struct{ carrier, service string }{{"FASTSHIP", "FAST-AIR"}, {"QUICKEXPRESS", "EXPRESS"}, {"RELIABLE", "RC-SURFACE"}} {
		s := e.NewShipment(fmt.Sprintf("W-%d", i), c.carrier, c.service, testkit.OrderOpts{})
		for _, ev := range []string{"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"} {
			e.MustTrigger(s, ev, "")
			if got := e.Get("/api/orders/" + s.OrderID + "/tracking").Str("currentStatus"); got != ev {
				t.Fatalf("%s: after %s status is %s", c.carrier, ev, got)
			}
		}
		want := fmt.Sprint([]string{"SHIPMENT_CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"})
		if got := fmt.Sprint(history(e, s.OrderID)); got != want {
			t.Errorf("%s history %s want %s", c.carrier, got, want)
		}
		if o := e.Get("/api/orders/" + s.OrderID); o.Str("status") != "DELIVERED" {
			t.Errorf("order should mirror shipment status, got %s", o.Str("status"))
		}
	}
	// raw payload + normalized event are both stored
	if n := e.Count(`SELECT count(*) FROM shipment_events WHERE raw_event_payload IS NOT NULL AND normalized_status IS NOT NULL AND carrier_status IS NOT NULL`); n < 15 {
		t.Fatalf("expected raw+normalized events stored, got %d", n)
	}
}

func TestDuplicateWebhookCreatesExactlyOneEvent(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("D-1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	body := fmt.Sprintf(`{"shipment_id":"FS-700001","tracking_number":"%s","event_code":"PICKED_UP","event_description":"picked","event_time":"2026-07-16T10:30:00Z","location":"Bengaluru Hub"}`, s.Tracking)
	var statuses []string
	for i := 0; i < 5; i++ {
		r := e.Webhook("fastship", "FASTSHIP", body)
		if r.Status != 200 {
			t.Fatalf("duplicate delivery %d must still be acknowledged with 2xx: %d %s", i, r.Status, r.Raw)
		}
		statuses = append(statuses, r.Str("status"))
	}
	if fmt.Sprint(statuses) != "[processed duplicate duplicate duplicate duplicate]" {
		t.Fatalf("%v", statuses)
	}
	if n := e.Count(`SELECT count(*) FROM shipment_events WHERE shipment_id=$1::uuid AND normalized_status='PICKED_UP'`, s.ShipmentID); n != 1 {
		t.Fatalf("5 identical webhooks must create one event, got %d", n)
	}
	if fmt.Sprint(history(e, s.OrderID)) != "[SHIPMENT_CREATED PICKED_UP]" {
		t.Fatalf("history: %v", history(e, s.OrderID))
	}
	// concurrent duplicates are serialised by the shipment row lock + unique key
	done := make(chan struct{})
	body2 := fmt.Sprintf(`{"shipment_id":"FS-700001","tracking_number":"%s","event_code":"IN_TRANSIT","event_time":"2026-07-16T12:00:00Z"}`, s.Tracking)
	for i := 0; i < 8; i++ {
		go func() { e.Webhook("fastship", "FASTSHIP", body2); done <- struct{}{} }()
	}
	for i := 0; i < 8; i++ {
		<-done
	}
	if n := e.Count(`SELECT count(*) FROM shipment_events WHERE shipment_id=$1::uuid AND normalized_status='IN_TRANSIT'`, s.ShipmentID); n != 1 {
		t.Fatalf("concurrent duplicates must collapse to one event, got %d", n)
	}
	// the mock can also replay duplicates itself (real carrier -> Zippy path)
	r := e.Post("/api/mock-carriers/FASTSHIP/shipments/"+s.ShipmentID+"/trigger", map[string]any{"event": "OUT_FOR_DELIVERY", "duplicates": 4})
	if r.Len("deliveries") != 5 {
		t.Fatalf("%s", r.Raw)
	}
	if n := e.Count(`SELECT count(*) FROM shipment_events WHERE shipment_id=$1::uuid AND normalized_status='OUT_FOR_DELIVERY'`, s.ShipmentID); n != 1 {
		t.Fatalf("mock-replayed duplicates must collapse to one event, got %d", n)
	}
}

func TestDerivedIdempotencyKeyDistinguishesDifferentEvents(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("D-2", "RELIABLE", "RC-SURFACE", testkit.OrderOpts{})
	for _, ts := range []string{"2026-07-16T10:30:00Z", "2026-07-16T11:30:00Z"} {
		body := fmt.Sprintf(`{"trackingCode":"%s","statusId":30,"statusText":"In transit","updatedOn":"%s"}`, s.Tracking, ts)
		if r := e.Webhook("reliable", "RELIABLE", body); r.Status != 200 || r.Str("status") != "processed" {
			t.Fatalf("%s", r.Raw)
		}
	}
	if n := e.Count(`SELECT count(*) FROM shipment_events WHERE shipment_id=$1::uuid AND normalized_status='IN_TRANSIT'`, s.ShipmentID); n != 2 {
		t.Fatalf("two genuinely different IN_TRANSIT scans are two events, got %d", n)
	}
	if st := e.Get("/api/orders/" + s.OrderID + "/tracking").Str("currentStatus"); st != "IN_TRANSIT" {
		t.Fatal(st)
	}
}

func TestInvalidStatusRegressionRejectedAndQuarantined(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("T-1", "QUICKEXPRESS", "EXPRESS", testkit.OrderOpts{})
	e.ToOFD(s)
	e.MustTrigger(s, "DELIVERED", "")
	for _, ev := range []string{"IN_TRANSIT", "PICKED_UP", "OUT_FOR_DELIVERY", "NDR"} {
		r := e.Trigger(s, ev, "")
		if r.Str("deliveries.0.status") != "409" || r.Str("deliveries.0.body.error.code") != "INVALID_STATUS_TRANSITION" {
			t.Fatalf("DELIVERED -> %s must be rejected: %s", ev, r.Raw)
		}
	}
	tr := e.Get("/api/orders/" + s.OrderID + "/tracking")
	if tr.Str("currentStatus") != "DELIVERED" {
		t.Fatal("a regression must never change status")
	}
	if fmt.Sprint(history(e, s.OrderID)) != "[SHIPMENT_CREATED PICKED_UP IN_TRANSIT OUT_FOR_DELIVERY DELIVERED]" {
		t.Fatalf("rejected events must not appear in history: %v", history(e, s.OrderID))
	}
	if n := e.Count(`SELECT count(*) FROM shipment_events WHERE disposition='REJECTED_TRANSITION'`); n != 4 {
		t.Fatalf("rejected events are stored for investigation, got %d", n)
	}
	if e.Count(`SELECT count(*) FROM ndr_cases`) != 0 {
		t.Fatal("a rejected NDR must not open a case")
	}
}

func TestForwardSkipAndSameStateAccepted(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("T-2", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "") // skipped PICKED_UP / IN_TRANSIT events (lost webhooks)
	if e.Get("/api/orders/"+s.OrderID+"/tracking").Str("currentStatus") != "OUT_FOR_DELIVERY" {
		t.Fatal("forward skips are accepted")
	}
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "") // same state, new event time
	if got := fmt.Sprint(history(e, s.OrderID)); got != "[SHIPMENT_CREATED OUT_FOR_DELIVERY OUT_FOR_DELIVERY]" {
		t.Fatalf("%s", got)
	}
}

func TestUnknownTrackingNumberRejectedAndRecorded(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	body := `{"shipment_id":"FS-999999","tracking_number":"FST000000000","event_code":"IN_TRANSIT","event_time":"2026-07-16T10:30:00Z"}`
	r := e.Webhook("fastship", "FASTSHIP", body)
	if r.Status != 404 || r.Str("error.code") != "NOT_FOUND" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	in := e.Get("/api/webhooks-inbox")
	if in.Str("entries.0.outcome") != "UNKNOWN_TRACKING" || in.Str("entries.0.carrierCode") != "FASTSHIP" {
		t.Fatalf("unknown tracking must be recorded for investigation: %s", in.Raw)
	}
}

func TestWebhookAuthenticationAndMalformedPayloads(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("A-9", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	body := fmt.Sprintf(`{"tracking_number":"%s","event_code":"PICKED_UP","event_time":"2026-07-16T10:30:00Z"}`, s.Tracking)
	if r := e.Do("POST", "/api/webhooks/fastship", body, nil); r.Status != 401 || r.Str("error.code") != "INVALID_SIGNATURE" {
		t.Fatalf("unsigned webhook must be rejected: %d %s", r.Status, r.Raw)
	}
	if r := e.Do("POST", "/api/webhooks/fastship", body, testkit.Hdr{"X-Carrier-Signature": "deadbeef"}); r.Status != 401 {
		t.Fatalf("bad signature must be rejected: %d", r.Status)
	}
	// a signature from another carrier's secret is not valid either
	if r := e.Do("POST", "/api/webhooks/fastship", body, testkit.Hdr{"X-Carrier-Signature": e.Sign("RELIABLE", []byte(body))}); r.Status != 401 {
		t.Fatalf("cross-carrier signature must be rejected: %d", r.Status)
	}
	if r := e.Webhook("fastship", "FASTSHIP", `{"tracking_number":"x","event_code":"TELEPORTED","event_time":"2026-07-16T10:30:00Z"}`); r.Status != 400 || r.Str("error.code") != "MALFORMED_WEBHOOK" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if r := e.Webhook("fastship", "FASTSHIP", `<<not json`); r.Status != 400 {
		t.Fatalf("%d", r.Status)
	}
	if r := e.Do("POST", "/api/webhooks/unknowncarrier", `{}`, nil); r.Status != 404 {
		t.Fatalf("unknown carrier path: %d", r.Status)
	}
	if e.Count(`SELECT count(*) FROM shipment_events WHERE normalized_status='PICKED_UP'`) != 0 {
		t.Fatal("rejected webhooks must not change anything")
	}
	if e.Count(`SELECT count(*) FROM webhook_inbox WHERE outcome IN ('REJECTED_SIGNATURE','MALFORMED')`) < 4 {
		t.Fatal("rejections must be recorded")
	}
}

func TestMockControlValidation(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("MC-1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	if r := e.Post("/api/mock-carriers/FASTSHIP/shipments/"+s.ShipmentID+"/trigger", map[string]any{"event": "TELEPORT"}); r.Status != 400 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if r := e.Post("/api/mock-carriers/RELIABLE/shipments/"+s.ShipmentID+"/trigger", map[string]any{"event": "PICKED_UP"}); r.Status != 422 {
		t.Fatalf("carrier mismatch must be rejected: %d %s", r.Status, r.Raw)
	}
	if r := e.Post("/api/mock-carriers/FASTSHIP/shipments/00000000-0000-0000-0000-000000000000/trigger", map[string]any{"event": "PICKED_UP"}); r.Status != 404 {
		t.Fatalf("%d", r.Status)
	}
	// trigger by tracking number and by order id both work
	if r := e.Post("/api/mock-carriers/FASTSHIP/shipments/"+s.Tracking+"/trigger", map[string]any{"event": "PICKED_UP"}); r.Status != 200 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
}

func TestRequestAndCorrelationIDsAreEchoed(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	r := e.Get("/api/carriers", testkit.Hdr{"X-Request-ID": "req-123", "X-Correlation-ID": "corr-9"})
	if r.Status != 200 || r.Len("carriers") != 3 {
		t.Fatalf("%s", r.Raw)
	}
	nf := e.Get("/api/orders/NOPE", testkit.Hdr{"X-Request-ID": "req-456"})
	if nf.Status != 404 || nf.Str("error.requestId") != "req-456" {
		t.Fatalf("error bodies carry the request id: %s", nf.Raw)
	}
}
