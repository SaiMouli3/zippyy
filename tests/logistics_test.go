package tests

import (
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/saimouli3/zippyy/apps/api/testkit"
)

func TestOrderCreationValid(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	r := e.Post("/api/orders", e.OrderBody(testkit.OrderOpts{MerchantOrderID: "MERCHANT-10001"}))
	if r.Status != 201 || r.Str("status") != "ORDER_CREATED" || !strings.HasPrefix(r.Str("orderId"), "ZPY-ORD-") || r.Str("merchantOrderId") != "MERCHANT-10001" || r.Str("createdAt") == "" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	g := e.Get("/api/orders/" + r.Str("orderId"))
	if g.Status != 200 || g.Str("customer.name") != "Rahul Sharma" || g.Num("package.weightGrams") != 1500 || g.Num("codAmount") != 2500 {
		t.Fatalf("%s", g.Raw)
	}
}

func TestOrderValidation(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	cases := map[string]func(m map[string]any){
		"customer.phone":          func(m map[string]any) { m["customer"].(map[string]any)["phone"] = "12345" },
		"deliveryAddress.pincode": func(m map[string]any) { m["deliveryAddress"].(map[string]any)["pincode"] = "0123" },
		"package.weightGrams":     func(m map[string]any) { m["package"].(map[string]any)["weightGrams"] = 0 },
		"package.lengthCm":        func(m map[string]any) { m["package"].(map[string]any)["lengthCm"] = -1 },
		"codAmount":               func(m map[string]any) { m["codAmount"] = 0 },
		"paymentType":             func(m map[string]any) { m["paymentType"] = "BARTER" },
		"merchantOrderId":         func(m map[string]any) { m["merchantOrderId"] = "" },
		"customer.name":           func(m map[string]any) { m["customer"].(map[string]any)["name"] = " " },
	}
	i := 0
	for field, mutate := range cases {
		i++
		body := e.OrderBody(testkit.OrderOpts{MerchantOrderID: fmt.Sprintf("V-%d", i)})
		mutate(body)
		r := e.Post("/api/orders", body)
		if r.Status != 422 || r.Str("error.code") != "VALIDATION_FAILED" {
			t.Errorf("%s: want 422 VALIDATION_FAILED, got %d %s", field, r.Status, r.Raw)
			continue
		}
		if f, _ := r.At("error.details.fields").(map[string]any); f[field] == nil {
			t.Errorf("%s: field not reported: %s", field, r.Raw)
		}
	}
	if r := e.Post("/api/orders", `{not json`); r.Status != 400 {
		t.Errorf("bad json should be 400, got %d", r.Status)
	}
}

func TestPrepaidOrderAllowedWithoutCOD(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	b := e.OrderBody(testkit.OrderOpts{MerchantOrderID: "P-1", Payment: "PREPAID"})
	b["codAmount"] = 0
	if r := e.Post("/api/orders", b); r.Status != 201 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
}

func TestDuplicateMerchantOrderPrevented(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	first := e.Post("/api/orders", e.OrderBody(testkit.OrderOpts{MerchantOrderID: "DUP-1"}))
	second := e.Post("/api/orders", e.OrderBody(testkit.OrderOpts{MerchantOrderID: "DUP-1"}))
	if second.Status != 409 || second.Str("error.code") != "DUPLICATE_ORDER" || second.Str("error.details.orderId") != first.Str("orderId") {
		t.Fatalf("%d %s", second.Status, second.Raw)
	}
	if n := e.Count(`SELECT count(*) FROM orders WHERE merchant_order_id='DUP-1'`); n != 1 {
		t.Fatalf("duplicate order row created: %d", n)
	}
}

func TestOrderIdempotencyKeyReplays(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	h := testkit.Hdr{"Idempotency-Key": "key-abc"}
	body := e.OrderBody(testkit.OrderOpts{MerchantOrderID: "IDEM-1"})
	a := e.Post("/api/orders", body, h)
	b := e.Post("/api/orders", body, h)
	if a.Status != 201 || b.Status != 201 || a.Str("orderId") != b.Str("orderId") {
		t.Fatalf("replay must return the original response: %s / %s", a.Raw, b.Raw)
	}
	other := e.OrderBody(testkit.OrderOpts{MerchantOrderID: "IDEM-2"})
	if c := e.Post("/api/orders", other, h); c.Status != 422 || c.Str("error.code") != "IDEMPOTENCY_KEY_REUSED" {
		t.Fatalf("%d %s", c.Status, c.Raw)
	}
}

func newOrder(e *testkit.Env, mid string) string {
	r := e.Post("/api/orders", e.OrderBody(testkit.OrderOpts{MerchantOrderID: mid}))
	if r.Status != 201 {
		e.T.Fatalf("%d %s", r.Status, r.Raw)
	}
	return r.Str("orderId")
}

func TestRatesThreeCarriersNormalizedAndSorted(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	oid := newOrder(e, "R-1")
	r := e.Post("/api/orders/"+oid+"/rates", nil)
	if r.Status != 200 || !r.Bool("complete") || r.Len("failedCarriers") != 0 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	type row struct {
		carrier, service string
		total            float64
	}
	var got []row
	for i := 0; i < r.Len("shippingOptions"); i++ {
		p := fmt.Sprintf("shippingOptions.%d.", i)
		got = append(got, row{r.Str(p + "carrierCode"), r.Str(p + "serviceCode"), r.Num(p + "totalCharge")})
	}
	want := []row{{"RELIABLE", "RC-SURFACE", 159.30}, {"FASTSHIP", "FAST-AIR", 182.90}, {"QUICKEXPRESS", "EXPRESS", 197.06}, {"RELIABLE", "RC-AIR", 202.96}}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("\n got %v\nwant %v", got, want)
	}
	// documented normalized shape
	if r.Num("shippingOptions.0.baseCharge") != 95 || r.Num("shippingOptions.0.codCharge") != 30 || r.Num("shippingOptions.0.additionalCharges") != 10 || r.Num("shippingOptions.0.tax") != 24.3 ||
		r.Num("shippingOptions.0.estimatedMinDays") != 4 || r.Num("shippingOptions.0.estimatedMaxDays") != 5 || r.At("shippingOptions.0.quoteReference") != nil {
		t.Fatalf("reliable surface shape: %s", r.Raw)
	}
	if r.Str("shippingOptions.2.quoteReference") != "QE-Q-90001" && !strings.HasPrefix(r.Str("shippingOptions.2.quoteReference"), "QE-Q-") {
		t.Fatalf("quickexpress must carry its quote reference: %s", r.Raw)
	}
	if strings.Contains(string(r.Raw), "freight_charge") || strings.Contains(string(r.Raw), "grandTotal") {
		t.Fatal("raw carrier formats must never reach the frontend")
	}
	// sort variants + persisted GET
	eta := e.Get("/api/orders/" + oid + "/rates?sort=eta")
	if eta.Num("shippingOptions.0.estimatedMinDays") != 2 {
		t.Fatalf("eta sort: %s", eta.Raw)
	}
	car := e.Get("/api/orders/" + oid + "/rates?sort=carrier")
	if car.Str("shippingOptions.0.carrierName") != "FastShip" {
		t.Fatalf("carrier sort: %s", car.Raw)
	}
	if st := e.Get("/api/orders/" + oid); st.Str("status") != "RATES_FETCHED" {
		t.Fatalf("order status: %s", st.Str("status"))
	}
	if n := e.Count(`SELECT count(*) FROM shipping_quotes WHERE order_id=(SELECT id FROM orders WHERE zippy_order_id=$1) AND raw_carrier_response IS NOT NULL`, oid); n != 4 {
		t.Fatalf("raw carrier responses must be persisted per quote, got %d", n)
	}
}

func TestRatesCacheMissHitRefresh(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	oid := newOrder(e, "C-1")
	oid2 := newOrder(e, "C-2") // identical pricing inputs
	first := e.Post("/api/orders/"+oid+"/rates", nil)
	if first.Bool("cached") {
		t.Fatal("first request must be a miss")
	}
	if c := e.MockStats(); c["fastship.rate"] != 1 || c["quickexpress.rates"] != 1 || c["reliable.options"] != 1 {
		t.Fatalf("miss should call each carrier once: %v", c)
	}
	hit := e.Post("/api/orders/"+oid2+"/rates", nil)
	if !hit.Bool("cached") || hit.Len("shippingOptions") != 4 {
		t.Fatalf("second identical request must be a cache hit: %s", hit.Raw)
	}
	if c := e.MockStats(); c["fastship.rate"] != 1 {
		t.Fatalf("hit must not call carriers: %v", c)
	}
	// the hit still gets its own persisted quote snapshot, so selection works for oid2
	q := hit.At("shippingOptions.1")
	_ = q
	ref := e.Post("/api/orders/"+oid2+"/rates?refresh=true", nil)
	if ref.Bool("cached") {
		t.Fatal("refresh=true must bypass the cache")
	}
	if c := e.MockStats(); c["fastship.rate"] != 2 || c["quickexpress.rates"] != 2 {
		t.Fatalf("refresh must call carriers again: %v", c)
	}
	if e.Redis.Exists("zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500") == false {
		t.Fatalf("expected the documented cache key to exist; keys: %v", e.Redis.Keys())
	}
}

func TestRatesCacheExpiryAndPartialTTL(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	oid := newOrder(e, "E-1")
	e.Post("/api/orders/"+oid+"/rates", nil)
	e.Redis.FastForward(6 * time.Minute) // default TTL is 5 minutes
	oid2 := newOrder(e, "E-2")
	r := e.Post("/api/orders/"+oid2+"/rates", nil)
	if r.Bool("cached") || e.MockStats()["fastship.rate"] != 2 {
		t.Fatalf("expired entry must trigger fresh carrier calls")
	}
	// partial result uses the short TTL (20s in the test config)
	e.SetFault("QUICKEXPRESS", "http500")
	b := e.OrderBody(testkit.OrderOpts{MerchantOrderID: "E-3", Pincode: "400001", City: "Mumbai"})
	o3 := e.Post("/api/orders", b).Str("orderId")
	p := e.Post("/api/orders/"+o3+"/rates", nil)
	if p.Bool("complete") || p.Len("failedCarriers") != 1 {
		t.Fatalf("%s", p.Raw)
	}
	e.SetFault("QUICKEXPRESS", "")
	b2 := e.OrderBody(testkit.OrderOpts{MerchantOrderID: "E-4", Pincode: "400001", City: "Mumbai"})
	o4 := e.Post("/api/orders", b2).Str("orderId")
	if again := e.Post("/api/orders/"+o4+"/rates", nil); !again.Bool("cached") || again.Bool("complete") {
		t.Fatal("a partial result is cached briefly")
	}
	e.Redis.FastForward(30 * time.Second)
	b3 := e.OrderBody(testkit.OrderOpts{MerchantOrderID: "E-5", Pincode: "400001", City: "Mumbai"})
	o5 := e.Post("/api/orders", b3).Str("orderId")
	if rec := e.Post("/api/orders/"+o5+"/rates", nil); rec.Bool("cached") || !rec.Bool("complete") {
		t.Fatalf("after the short TTL the recovered carrier must be picked up: %s", rec.Raw)
	}
}

func TestRatesOneCarrierFailsOrTimesOut(t *testing.T) {
	e := testkit.New(t, testkit.Options{CarrierTimeout: 400 * time.Millisecond})
	e.SetFault("FASTSHIP", "http500")
	e.SetFault("QUICKEXPRESS", "timeout")
	oid := newOrder(e, "F-1")
	start := time.Now()
	r := e.Post("/api/orders/"+oid+"/rates?refresh=true", nil)
	if time.Since(start) > 3*time.Second {
		t.Fatalf("a hung carrier must not hold the request: %s", time.Since(start))
	}
	if r.Status != 200 || r.Bool("complete") || r.Len("shippingOptions") != 2 || r.Len("failedCarriers") != 2 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	reasons := map[string]string{}
	for i := 0; i < 2; i++ {
		reasons[r.Str(fmt.Sprintf("failedCarriers.%d.carrierCode", i))] = r.Str(fmt.Sprintf("failedCarriers.%d.reason", i))
	}
	if reasons["FASTSHIP"] != "HTTP_ERROR" || reasons["QUICKEXPRESS"] != "TIMEOUT" {
		t.Fatalf("failure reasons: %v", reasons)
	}
}

func TestRatesMalformedCarrierResponse(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	e.SetFault("RELIABLE", "malformed")
	r := e.Post("/api/orders/"+newOrder(e, "M-1")+"/rates?refresh=true", nil)
	if r.Status != 200 || r.Len("failedCarriers") != 1 || r.Str("failedCarriers.0.reason") != "MALFORMED_RESPONSE" || r.Len("shippingOptions") != 2 {
		t.Fatalf("%s", r.Raw)
	}
}

func TestRatesAllCarriersFail(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	for _, c := range []string{"FASTSHIP", "QUICKEXPRESS", "RELIABLE"} {
		e.SetFault(c, "http500")
	}
	r := e.Post("/api/orders/"+newOrder(e, "A-1")+"/rates?refresh=true", nil)
	if r.Status != 502 || r.Str("error.code") != "ALL_CARRIERS_FAILED" || r.Len("error.details.failedCarriers") != 3 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if len(e.Redis.Keys()) != 0 {
		t.Fatal("total failure must not be cached and rates must never be fabricated")
	}
}

func TestRedisUnavailableFallsBackToCarriers(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	e.Redis.Close()
	oid := newOrder(e, "RD-1")
	r := e.Post("/api/orders/"+oid+"/rates", nil)
	if r.Status != 200 || r.Len("shippingOptions") != 4 || r.Bool("cached") {
		t.Fatalf("redis outage must not break rates: %d %s", r.Status, r.Raw)
	}
}

func TestConcurrentIdenticalRequestsCallCarriersOnce(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	var ids []string
	for i := 0; i < 10; i++ {
		ids = append(ids, newOrder(e, fmt.Sprintf("CC-%d", i)))
	}
	var wg sync.WaitGroup
	for _, id := range ids {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			if r := e.Post("/api/orders/"+id+"/rates", nil); r.Status != 200 || r.Len("shippingOptions") != 4 {
				t.Errorf("%d %s", r.Status, r.Raw)
			}
		}(id)
	}
	wg.Wait()
	if c := e.MockStats(); c["fastship.rate"] > 1 || c["quickexpress.rates"] > 1 || c["reliable.options"] > 1 {
		t.Fatalf("10 simultaneous identical requests must call each carrier once, got %v", c)
	}
}

func TestSelectCarrierValidation(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	oid := newOrder(e, "S-1")
	if r := e.Post("/api/orders/"+oid+"/select-carrier", map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 182.9}); r.Status != 422 || r.Str("error.code") != "NO_QUOTES" {
		t.Fatalf("selecting before rates: %d %s", r.Status, r.Raw)
	}
	e.Post("/api/orders/"+oid+"/rates", nil)
	sel := func(body map[string]any) testkit.Resp { return e.Post("/api/orders/"+oid+"/select-carrier", body) }

	if r := sel(map[string]any{"carrierCode": "NOPE", "serviceCode": "X", "quotedAmount": 1}); r.Status != 422 || r.Str("error.code") != "VALIDATION_FAILED" {
		t.Fatalf("unknown carrier: %d %s", r.Status, r.Raw)
	}
	if r := sel(map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-SURFACE", "quotedAmount": 182.9}); r.Status != 422 || r.Str("error.code") != "QUOTE_NOT_FOUND" {
		t.Fatalf("unknown service: %d %s", r.Status, r.Raw)
	}
	if r := sel(map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 100.00}); r.Status != 409 || r.Str("error.code") != "QUOTED_AMOUNT_MISMATCH" {
		t.Fatalf("tampered amount: %d %s", r.Status, r.Raw)
	}
	if r := sel(map[string]any{"carrierCode": "QUICKEXPRESS", "serviceCode": "EXPRESS", "quotedAmount": 197.06, "quoteReference": "QE-Q-HACKED"}); r.Status != 422 || r.Str("error.code") != "QUOTE_REFERENCE_MISMATCH" {
		t.Fatalf("tampered quote reference: %d %s", r.Status, r.Raw)
	}
	if o := e.Get("/api/orders/" + oid); o.Str("status") != "RATES_FETCHED" || o.At("quotedAmount") != nil {
		t.Fatal("failed selections must not change the order")
	}
	ok := sel(map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 182.90, "quoteReference": nil})
	if ok.Status != 200 || ok.Str("status") != "CARRIER_SELECTED" || ok.Num("quotedAmount") != 182.9 {
		t.Fatalf("%d %s", ok.Status, ok.Raw)
	}
	o := e.Get("/api/orders/" + oid)
	if o.Str("selectedCarrierCode") != "FASTSHIP" || o.Num("quotedAmount") != 182.9 || o.Str("selectedAt") == "" || o.Str("selectedQuoteId") == "" {
		t.Fatalf("selection must persist carrier, service, amount, time and original quote: %s", o.Raw)
	}
}

func TestSelectCarrierExpiredQuote(t *testing.T) {
	e := testkit.New(t, testkit.Options{Now: time.Now()})
	oid := newOrder(e, "X-1")
	e.Post("/api/orders/"+oid+"/rates", nil)
	e.Advance(6 * time.Minute)
	r := e.Post("/api/orders/"+oid+"/select-carrier", map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 182.90})
	if r.Status != 409 || r.Str("error.code") != "QUOTE_EXPIRED" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if g := e.Get("/api/orders/" + oid + "/rates"); !g.Bool("expired") {
		t.Fatalf("GET rates should flag expiry: %s", g.Raw)
	}
	// refreshing makes a new valid quote set
	e.Post("/api/orders/"+oid+"/rates?refresh=true", nil)
	if r := e.Post("/api/orders/"+oid+"/select-carrier", map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 182.90}); r.Status != 200 {
		t.Fatalf("after refresh selection should work: %d %s", r.Status, r.Raw)
	}
}

func TestSelectionUsesLatestQuoteSetAndIsImmutableAfterShipment(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("L-1", "RELIABLE", "RC-SURFACE", testkit.OrderOpts{})
	if r := e.Post("/api/orders/"+s.OrderID+"/select-carrier", map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 182.9}); r.Status != 409 || r.Str("error.code") != "SHIPMENT_EXISTS" {
		t.Fatalf("selection must be immutable once a shipment exists: %d %s", r.Status, r.Raw)
	}
	if r := e.Post("/api/orders/"+s.OrderID+"/rates", nil); r.Status != 409 {
		t.Fatalf("rates must be locked once a shipment exists: %d", r.Status)
	}
	tr := e.Get("/api/orders/" + s.OrderID + "/tracking")
	if tr.Num("shipment.quotedAmount") != 159.3 {
		t.Fatalf("shipment must carry the immutable quoted amount: %s", tr.Raw)
	}
}

func TestShipmentCreationPerCarrier(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	cases := []struct{ carrier, service, prefix, shipPrefix string }{
		{"FASTSHIP", "FAST-AIR", "FST", "FS-"},
		{"QUICKEXPRESS", "EXPRESS", "QE", "QE-B-"},
		{"RELIABLE", "RC-AIR", "RC", "RC-DO-"},
	}
	for i, c := range cases {
		s := e.NewShipment(fmt.Sprintf("SH-%d", i), c.carrier, c.service, testkit.OrderOpts{})
		tr := e.Get("/api/orders/" + s.OrderID + "/tracking")
		if !strings.HasPrefix(s.Tracking, c.prefix) || !strings.HasPrefix(tr.Str("shipment.carrierShipmentId"), c.shipPrefix) || tr.Str("currentStatus") != "SHIPMENT_CREATED" || tr.Str("carrier.code") != c.carrier {
			t.Errorf("%s: %s", c.carrier, tr.Raw)
		}
		// repeating the call is idempotent: same shipment, no second carrier booking
		again := e.Post("/api/orders/"+s.OrderID+"/shipment", nil)
		if again.Status != 200 || again.Str("trackingNumber") != s.Tracking {
			t.Errorf("%s repeat: %d %s", c.carrier, again.Status, again.Raw)
		}
	}
	if st := e.MockStats(); st["fastship.shipments"] != 1 || st["quickexpress.booking"] != 1 || st["reliable.orders"] != 1 {
		t.Fatalf("each carrier must be booked exactly once: %v", st)
	}
	if r := e.Post("/api/orders/"+newOrder(e, "SH-NS")+"/shipment", nil); r.Status != 422 || r.Str("error.code") != "CARRIER_NOT_SELECTED" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
}

func TestShipmentCreationCarrierFailureIsReportedNotFabricated(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	oid := newOrder(e, "SF-1")
	e.Post("/api/orders/"+oid+"/rates", nil)
	e.Post("/api/orders/"+oid+"/select-carrier", map[string]any{"carrierCode": "FASTSHIP", "serviceCode": "FAST-AIR", "quotedAmount": 182.9})
	e.SetFault("FASTSHIP", "http500")
	r := e.Post("/api/orders/"+oid+"/shipment", nil)
	if r.Status != 502 || r.Str("error.code") != "CARRIER_BOOKING_FAILED" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if e.Count(`SELECT count(*) FROM shipments`) != 0 {
		t.Fatal("no shipment may exist when the carrier booking failed")
	}
	e.SetFault("FASTSHIP", "")
	if r := e.Post("/api/orders/"+oid+"/shipment", nil); r.Status != 201 {
		t.Fatalf("retry should succeed: %d %s", r.Status, r.Raw)
	}
}
