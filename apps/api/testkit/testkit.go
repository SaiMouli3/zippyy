// Package testkit boots the full application (real Postgres, miniredis, in-process mock carriers, real HTTP
// listeners for both the API and the carriers) so integration and end-to-end tests exercise real wiring,
// including real carrier -> Zippy webhook delivery.
package testkit

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/saimouli3/zippyy/apps/api/internal/app"
	"github.com/saimouli3/zippyy/apps/api/internal/config"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/mock-carriers/mockcarriers"
)

type Env struct {
	T       *testing.T
	App     *app.App
	Redis   *miniredis.Miniredis
	APIURL  string
	MockURL string
	Secrets map[string]string
	mu      sync.Mutex
	now     time.Time
}

type Options struct {
	CarrierTimeout time.Duration
	CacheTTL       time.Duration
	// Now is the starting simulated time (IST wall clock matters for cutoff rules). Zero = real time.
	Now time.Time
}

// Clock returns the simulated "now".
func (e *Env) Clock() time.Time {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.now.IsZero() {
		return time.Now()
	}
	return e.now
}

func (e *Env) Advance(d time.Duration) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.now.IsZero() {
		e.now = time.Now()
	}
	e.now = e.now.Add(d)
}

// New starts the stack. It skips the test when no database is reachable.
func New(t *testing.T, opt Options) *Env {
	t.Helper()
	dbURL := os.Getenv("TEST_DATABASE_URL")
	if dbURL == "" {
		dbURL = "postgres://zippy:zippy@localhost:5432/zippy_test?sslmode=disable"
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dbURL)
	if err == nil {
		err = pool.Ping(ctx)
	}
	if err != nil {
		t.Skipf("PostgreSQL not available for integration tests (set TEST_DATABASE_URL): %v", err)
	}
	pool.Close()

	if opt.CarrierTimeout == 0 {
		opt.CarrierTimeout = 1500 * time.Millisecond
	}
	if opt.CacheTTL == 0 {
		opt.CacheTTL = 5 * time.Minute
	}
	env := &Env{T: t, now: opt.Now, Secrets: map[string]string{"FASTSHIP": "test-fs", "QUICKEXPRESS": "test-qe", "RELIABLE": "test-rc"}}
	env.Redis = miniredis.RunT(t)

	apiLn, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	mockLn, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	env.APIURL = "http://" + apiLn.Addr().String()
	env.MockURL = "http://" + mockLn.Addr().String()

	log := platform.NewLogger(io.Discard, "error")
	mock := mockcarriers.New(mockcarriers.Config{ZippyWebhookBase: env.APIURL, Secrets: env.Secrets}, log)
	mockApp := mock.App()
	go func() { _ = mockApp.Listener(mockLn) }()
	t.Cleanup(func() { _ = mockApp.ShutdownWithTimeout(200 * time.Millisecond) })

	cfg := config.Config{
		DatabaseURL: dbURL, RedisURL: "redis://" + env.Redis.Addr(), LogLevel: "error",
		FastShipBaseURL: env.MockURL, QuickExpressBaseURL: env.MockURL, ReliableBaseURL: env.MockURL, ZippyPublicURL: env.APIURL,
		CacheTTL: opt.CacheTTL, PartialCacheTTL: 20 * time.Second, CarrierTimeout: opt.CarrierTimeout,
		WebhookSecrets: env.Secrets, WebhookSignatureRequired: true, LLMProvider: "mock", IntentConfidenceMin: 0.75, AllowedOrigins: "*",
	}
	a, err := app.Build(ctx, app.Options{Config: cfg, Log: log, Now: env.Clock, NDRRetryBackoff: 5 * time.Millisecond})
	if err != nil {
		t.Fatalf("build app: %v", err)
	}
	env.App = a
	env.reset()
	apiApp := a.HTTP.App()
	go func() { _ = apiApp.Listener(apiLn) }()
	t.Cleanup(func() { _ = apiApp.ShutdownWithTimeout(500 * time.Millisecond); a.Close() })
	return env
}

func (e *Env) reset() {
	ctx := context.Background()
	_, err := e.App.Store.Pool().Exec(ctx, `TRUNCATE audit_logs, approvals, carrier_actions, conversation_messages, communication_attempts, ndr_events, ndr_cases, buyer_profiles,
	  shipment_events, webhook_inbox, idempotency_records, shipments, shipping_quotes, orders RESTART IDENTITY CASCADE`)
	if err != nil {
		e.T.Fatalf("reset: %v", err)
	}
	_, err = e.App.Store.Pool().Exec(ctx, `
	  DELETE FROM seller_rules WHERE merchant_id <> 'MRC-100';
	  UPDATE seller_rules SET max_attempts=3, auto_rto_attempt=3, cod_limit=10000, allowed_channels='{WHATSAPP,IVR,SMS}', enforce_comm_hours=FALSE, prepaid_conversion_allowed=TRUE,
	    allow_address_changes=TRUE, early_rto_policy='APPROVAL', allowed_actions='{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,UPDATE_ADDRESS,CONVERT_TO_PREPAID,INITIATE_RTO}', default_on_silence='RTO' WHERE merchant_id='MRC-100';
	  UPDATE carrier_rules SET max_attempts=3, instruction_cutoff='23:59', hold_window_days=7, supported_actions='{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,UPDATE_ADDRESS,CONVERT_TO_PREPAID,INITIATE_RTO}',
	    supports_time_slot=TRUE, can_change_payment_mode=TRUE, can_change_address=TRUE, can_change_phone=TRUE WHERE carrier_code='FASTSHIP';
	  UPDATE carrier_rules SET max_attempts=3, instruction_cutoff='22:00', hold_window_days=5, supported_actions='{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,UPDATE_ADDRESS,INITIATE_RTO}',
	    supports_time_slot=TRUE, can_change_payment_mode=FALSE, can_change_address=TRUE, can_change_phone=TRUE WHERE carrier_code='QUICKEXPRESS';
	  UPDATE carrier_rules SET max_attempts=2, instruction_cutoff='20:00', hold_window_days=4, supported_actions='{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,CONVERT_TO_PREPAID,INITIATE_RTO}',
	    supports_time_slot=FALSE, can_change_payment_mode=TRUE, can_change_address=FALSE, can_change_phone=TRUE WHERE carrier_code='RELIABLE';`)
	if err != nil {
		e.T.Fatalf("reset rules: %v", err)
	}
}

// ---- HTTP helpers ----

type Resp struct {
	Status int
	Body   map[string]any
	Raw    []byte
}

type Hdr map[string]string

func (e *Env) Do(method, path string, body any, h Hdr) Resp {
	e.T.Helper()
	var rd io.Reader
	if body != nil {
		switch b := body.(type) {
		case string:
			rd = strings.NewReader(b)
		case []byte:
			rd = bytes.NewReader(b)
		default:
			j, _ := json.Marshal(body)
			rd = bytes.NewReader(j)
		}
	}
	req, _ := http.NewRequest(method, e.APIURL+path, rd)
	req.Header.Set("Content-Type", "application/json")
	for k, v := range h {
		req.Header.Set(k, v)
	}
	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		e.T.Fatalf("%s %s: %v", method, path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	out := Resp{Status: resp.StatusCode, Raw: raw}
	_ = json.Unmarshal(raw, &out.Body)
	return out
}

func (e *Env) Post(path string, body any, h ...Hdr) Resp {
	var hh Hdr
	if len(h) > 0 {
		hh = h[0]
	}
	return e.Do("POST", path, body, hh)
}
func (e *Env) Get(path string, h ...Hdr) Resp {
	var hh Hdr
	if len(h) > 0 {
		hh = h[0]
	}
	return e.Do("GET", path, nil, hh)
}

var (
	Seller = Hdr{"X-Zippy-Role": "SELLER", "X-Zippy-Actor": "seller-1"}
	Ops    = Hdr{"X-Zippy-Role": "OPS", "X-Zippy-Actor": "ops-1"}
)

// At extracts a nested value via dotted path; array indexes are numeric segments.
func (r Resp) At(path string) any {
	var cur any = r.Body
	for _, seg := range strings.Split(path, ".") {
		switch t := cur.(type) {
		case map[string]any:
			cur = t[seg]
		case []any:
			var i int
			fmt.Sscanf(seg, "%d", &i)
			if i < 0 || i >= len(t) {
				return nil
			}
			cur = t[i]
		default:
			return nil
		}
	}
	return cur
}

func (r Resp) Str(path string) string {
	if v, ok := r.At(path).(string); ok {
		return v
	}
	if v := r.At(path); v != nil {
		return fmt.Sprint(v)
	}
	return ""
}

func (r Resp) Num(path string) float64 {
	v, _ := r.At(path).(float64)
	return v
}

func (r Resp) Bool(path string) bool {
	v, _ := r.At(path).(bool)
	return v
}

func (r Resp) Len(path string) int {
	v, _ := r.At(path).([]any)
	return len(v)
}

// ---- domain helpers ----

type OrderOpts struct {
	MerchantOrderID string
	Phone           string
	Language        string
	Pincode         string
	City            string
	Payment         string
	COD             float64
}

func (e *Env) OrderBody(o OrderOpts) map[string]any {
	if o.Phone == "" {
		o.Phone = "9876543210"
	}
	if o.Pincode == "" {
		o.Pincode = "110001"
	}
	if o.City == "" {
		o.City = "New Delhi"
	}
	if o.Payment == "" {
		o.Payment = "COD"
		if o.COD == 0 {
			o.COD = 2500
		}
	}
	b := map[string]any{
		"merchantOrderId": o.MerchantOrderID, "merchantId": "MRC-100",
		"customer":        map[string]any{"name": "Rahul Sharma", "phone": o.Phone, "email": "rahul@example.com"},
		"pickupAddress":   map[string]any{"addressLine1": "15 MG Road", "city": "Bengaluru", "state": "Karnataka", "pincode": "560001"},
		"deliveryAddress": map[string]any{"addressLine1": "22 Connaught Place", "city": o.City, "state": "Delhi", "pincode": o.Pincode},
		"package":         map[string]any{"weightGrams": 1500, "lengthCm": 20, "widthCm": 15, "heightCm": 10},
		"paymentType":     o.Payment, "codAmount": o.COD,
	}
	if o.Language != "" {
		b["language"] = o.Language
	}
	return b
}

// Shipment creates order -> rates -> select -> shipment for the carrier/service and returns ids.
type Shipment struct {
	OrderID, ShipmentID, Tracking, Carrier string
}

func (e *Env) NewShipment(mid, carrier, service string, o OrderOpts) Shipment {
	e.T.Helper()
	o.MerchantOrderID = mid
	r := e.Post("/api/orders", e.OrderBody(o))
	if r.Status != 201 {
		e.T.Fatalf("create order: %d %s", r.Status, r.Raw)
	}
	oid := r.Str("orderId")
	rr := e.Post("/api/orders/"+oid+"/rates?refresh=true", nil)
	if rr.Status != 200 {
		e.T.Fatalf("rates: %d %s", rr.Status, rr.Raw)
	}
	var amount float64
	var ref any
	for i := 0; i < rr.Len("shippingOptions"); i++ {
		p := fmt.Sprintf("shippingOptions.%d.", i)
		if rr.Str(p+"carrierCode") == carrier && rr.Str(p+"serviceCode") == service {
			amount, ref = rr.Num(p+"totalCharge"), rr.At(p+"quoteReference")
		}
	}
	if amount == 0 {
		e.T.Fatalf("quote for %s/%s not found: %s", carrier, service, rr.Raw)
	}
	sel := e.Post("/api/orders/"+oid+"/select-carrier", map[string]any{"carrierCode": carrier, "serviceCode": service, "quotedAmount": amount, "quoteReference": ref})
	if sel.Status != 200 {
		e.T.Fatalf("select: %d %s", sel.Status, sel.Raw)
	}
	sh := e.Post("/api/orders/"+oid+"/shipment", nil)
	if sh.Status != 201 {
		e.T.Fatalf("shipment: %d %s", sh.Status, sh.Raw)
	}
	return Shipment{OrderID: oid, ShipmentID: sh.Str("id"), Tracking: sh.Str("trackingNumber"), Carrier: carrier}
}

// Trigger makes the mock carrier emit a real webhook.
func (e *Env) Trigger(s Shipment, event, ndrReason string) Resp {
	e.T.Helper()
	return e.Post("/api/mock-carriers/"+s.Carrier+"/shipments/"+s.ShipmentID+"/trigger", map[string]any{"event": event, "ndrReason": ndrReason})
}

func (e *Env) MustTrigger(s Shipment, event, ndrReason string) {
	e.T.Helper()
	r := e.Trigger(s, event, ndrReason)
	if r.Status != 200 || r.Str("deliveries.0.status") != "200" {
		e.T.Fatalf("trigger %s: %d %s", event, r.Status, r.Raw)
	}
	time.Sleep(3 * time.Millisecond)
}

func (e *Env) ToOFD(s Shipment) {
	for _, ev := range []string{"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"} {
		e.MustTrigger(s, ev, "")
	}
}

// OpenNDR drives a shipment to OFD then NDR and returns the case id.
func (e *Env) OpenNDR(s Shipment, reason string) string {
	e.T.Helper()
	e.ToOFD(s)
	e.MustTrigger(s, "NDR", reason)
	r := e.Get("/api/ndr/cases?orderId=" + s.OrderID + "&open=true")
	if r.Len("cases") != 1 {
		e.T.Fatalf("expected one open case: %s", r.Raw)
	}
	return r.Str("cases.0.id")
}

func (e *Env) Case(id string) Resp { return e.Get("/api/ndr/cases/" + id) }

func (e *Env) MockStats() map[string]float64 {
	r := e.Get("/api/mock-carriers/FASTSHIP/stats")
	out := map[string]float64{}
	if m, ok := r.At("calls").(map[string]any); ok {
		for k, v := range m {
			out[k], _ = v.(float64)
		}
	}
	return out
}

func (e *Env) SetFault(carrier, fault string) {
	e.T.Helper()
	r := e.Post("/api/mock-carriers/"+carrier+"/faults", map[string]any{"fault": fault})
	if r.Status != 200 {
		e.T.Fatalf("set fault: %d %s", r.Status, r.Raw)
	}
}

func (e *Env) RejectActions(v bool) {
	e.T.Helper()
	e.Post("/api/mock-carriers/FASTSHIP/faults", map[string]any{"rejectActions": v})
}

// Count runs a scalar SQL count.
func (e *Env) Count(sql string, args ...any) int {
	var n int
	if err := e.App.Store.Pool().QueryRow(context.Background(), sql, args...).Scan(&n); err != nil {
		e.T.Fatalf("count %q: %v", sql, err)
	}
	return n
}

// Sign computes the HMAC the mock carriers use for webhook authentication.
func (e *Env) Sign(carrier string, body []byte) string {
	m := hmac.New(sha256.New, []byte(e.Secrets[carrier]))
	m.Write(body)
	return hex.EncodeToString(m.Sum(nil))
}

// Webhook posts a correctly signed carrier webhook directly (bypassing the mock), e.g. to replay duplicates.
func (e *Env) Webhook(path, carrierCode, body string) Resp {
	return e.Do("POST", "/api/webhooks/"+path, body, Hdr{"X-Carrier-Signature": e.Sign(carrierCode, []byte(body))})
}
