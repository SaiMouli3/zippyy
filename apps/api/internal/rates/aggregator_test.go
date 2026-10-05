package rates

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
)

type fakeCarrier struct {
	code  string
	total float64
	err   error
	delay time.Duration
	calls atomic.Int32
}

func (f *fakeCarrier) Code() string        { return f.code }
func (f *fakeCarrier) Name() string        { return f.code }
func (f *fakeCarrier) WebhookPath() string { return f.code }
func (f *fakeCarrier) GetRates(ctx context.Context, o domain.Order) ([]domain.Quote, error) {
	f.calls.Add(1)
	select {
	case <-time.After(f.delay):
	case <-ctx.Done():
		return nil, &carriers.CarrierError{Kind: domain.FailTimeout, Message: "timed out"}
	}
	if f.err != nil {
		return nil, f.err
	}
	return []domain.Quote{{CarrierCode: f.code, CarrierName: f.code, ServiceCode: "S", ServiceName: "S", TotalCharge: f.total, EstimatedMinDays: 2, EstimatedMaxDays: 3, Raw: []byte(`{"raw":true}`)}}, nil
}
func (f *fakeCarrier) CreateShipment(context.Context, domain.Order, domain.Quote) (carriers.ShipmentBooking, error) {
	return carriers.ShipmentBooking{}, nil
}
func (f *fakeCarrier) NormalizeWebhook([]byte) (carriers.NormalizedEvent, error) {
	return carriers.NormalizedEvent{}, nil
}
func (f *fakeCarrier) SubmitAction(context.Context, carriers.ActionRequest) (domain.CarrierActionResult, error) {
	return domain.CarrierActionResult{}, nil
}

func (f *fakeCarrier) n() int { return int(f.calls.Load()) }

func order() domain.Order {
	return domain.Order{MerchantID: "MRC-100", PickupAddress: domain.Address{Pincode: "560001"}, DeliveryAddress: domain.Address{Pincode: "110001"},
		Package: domain.Package{WeightGrams: 1500, LengthCm: 20, WidthCm: 15, HeightCm: 10}, PaymentType: domain.PaymentCOD, CODAmount: 2500}
}

type rig struct {
	agg     *Aggregator
	a, b, c *fakeCarrier
	mr      *miniredis.Miniredis
	m       *platform.Metrics
	now     *time.Time
}

func newRig(t *testing.T, cfg Config) *rig {
	t.Helper()
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr(), MaxRetries: -1, DialTimeout: 100 * time.Millisecond})
	r := &rig{a: &fakeCarrier{code: "A", total: 180}, b: &fakeCarrier{code: "B", total: 200}, c: &fakeCarrier{code: "C", total: 160}, mr: mr, m: platform.NewMetrics()}
	r.agg = New(carriers.NewRegistry(r.a, r.b, r.c), NewRedisCache(rdb), cfg, r.m)
	now := time.Now()
	r.now = &now
	r.agg.now = func() time.Time { return *r.now }
	return r
}

func TestCacheMissThenHit(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	res, err := r.agg.GetRates(context.Background(), order(), false)
	if err != nil || res.Cached || !res.Complete || len(res.Options) != 3 {
		t.Fatalf("miss: %+v %v", res, err)
	}
	if r.a.n() != 1 || r.b.n() != 1 || r.c.n() != 1 {
		t.Fatal("first request must call every carrier once")
	}
	res2, err := r.agg.GetRates(context.Background(), order(), false)
	if err != nil || !res2.Cached || len(res2.Options) != 3 {
		t.Fatalf("hit: %+v %v", res2, err)
	}
	if r.a.n() != 1 || r.b.n() != 1 || r.c.n() != 1 {
		t.Fatal("cache hit must not call carriers")
	}
	if string(res2.Raws[0]) != `{"raw":true}` {
		t.Fatal("raw carrier payload must survive the cache for per-order persistence")
	}
	if r.m.Get("rate_cache_hits_total") != 1 || r.m.Get("rate_cache_misses_total") != 1 {
		t.Fatal("metrics not recorded")
	}
}

func TestSortedByPriceAscending(t *testing.T) {
	r := newRig(t, Config{})
	res, _ := r.agg.GetRates(context.Background(), order(), false)
	if res.Options[0].CarrierCode != "C" || res.Options[1].CarrierCode != "A" || res.Options[2].CarrierCode != "B" {
		t.Fatalf("not sorted by price: %+v", res.Options)
	}
}

func TestRefreshBypassesCache(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	_, _ = r.agg.GetRates(context.Background(), order(), false)
	res, err := r.agg.GetRates(context.Background(), order(), true)
	if err != nil || res.Cached || r.a.n() != 2 {
		t.Fatalf("refresh must call carriers again: calls=%d res=%+v", r.a.n(), res)
	}
}

func TestChangedPricingInputsUseDifferentKey(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	o := order()
	_, _ = r.agg.GetRates(context.Background(), o, false)
	variants := []func(*domain.Order){
		func(o *domain.Order) { o.Package.WeightGrams = 2000 },
		func(o *domain.Order) { o.DeliveryAddress.Pincode = "400001" },
		func(o *domain.Order) { o.PickupAddress.Pincode = "560002" },
		func(o *domain.Order) { o.Package.LengthCm = 21 },
		func(o *domain.Order) { o.PaymentType = domain.PaymentPrepaid; o.CODAmount = 0 },
		func(o *domain.Order) { o.CODAmount = 2600 },
		func(o *domain.Order) { o.MerchantID = "MRC-200" },
	}
	seen := map[string]bool{domain.RateCacheKey(o): true}
	for i, v := range variants {
		o2 := o
		v(&o2)
		k := domain.RateCacheKey(o2)
		if seen[k] {
			t.Fatalf("variant %d reused a key", i)
		}
		seen[k] = true
		res, _ := r.agg.GetRates(context.Background(), o2, false)
		if res.Cached {
			t.Fatalf("variant %d must not hit the cache", i)
		}
	}
	if got := domain.RateCacheKey(o); got != "zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500" {
		t.Fatalf("cache key format drifted: %s", got)
	}
}

func TestExpiredEntryCausesFreshCalls(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	_, _ = r.agg.GetRates(context.Background(), order(), false)
	r.mr.FastForward(2 * time.Minute) // Redis TTL expiry
	res, _ := r.agg.GetRates(context.Background(), order(), false)
	if res.Cached || r.a.n() != 2 {
		t.Fatalf("expired entry must refetch: calls=%d", r.a.n())
	}
}

func TestExpiresAtGuardsAgainstStaleEntries(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	_, _ = r.agg.GetRates(context.Background(), order(), false)
	*r.now = r.now.Add(2 * time.Minute) // clock moved but Redis TTL did not
	res, _ := r.agg.GetRates(context.Background(), order(), false)
	if res.Cached {
		t.Fatal("entry past ExpiresAt must not be served")
	}
}

func TestOneCarrierFailureReturnsOthers(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	r.b.err = &carriers.CarrierError{Kind: domain.FailHTTPError, Message: "HTTP 500"}
	res, err := r.agg.GetRates(context.Background(), order(), false)
	if err != nil || res.Complete || len(res.Options) != 2 || len(res.FailedCarriers) != 1 || res.FailedCarriers[0].CarrierCode != "B" || res.FailedCarriers[0].Kind != domain.FailHTTPError {
		t.Fatalf("partial: %+v %v", res, err)
	}
}

func TestPartialResultsUseShortTTL(t *testing.T) {
	r := newRig(t, Config{TTL: 5 * time.Minute, PartialTTL: 20 * time.Second})
	r.b.err = errors.New("down")
	res, _ := r.agg.GetRates(context.Background(), order(), false)
	if d := res.ExpiresAt.Sub(res.FetchedAt); d != 20*time.Second {
		t.Fatalf("partial ttl = %s", d)
	}
	r.mr.FastForward(30 * time.Second)
	r.b.err = nil
	res, _ = r.agg.GetRates(context.Background(), order(), false)
	if res.Cached || !res.Complete {
		t.Fatal("recovered carrier must be picked up after the short TTL")
	}
}

func TestAllCarriersFailNotCachedNoFabrication(t *testing.T) {
	r := newRig(t, Config{})
	for _, c := range []*fakeCarrier{r.a, r.b, r.c} {
		c.err = errors.New("down")
	}
	_, err := r.agg.GetRates(context.Background(), order(), false)
	ae, ok := domain.AsAppError(err)
	if !ok || ae.Code != "ALL_CARRIERS_FAILED" || ae.Status != 502 {
		t.Fatalf("want ALL_CARRIERS_FAILED, got %v", err)
	}
	if len(r.mr.Keys()) != 0 {
		t.Fatal("total failure must not be cached")
	}
}

func TestCarrierTimeoutDoesNotBlock(t *testing.T) {
	r := newRig(t, Config{CarrierTimeout: 80 * time.Millisecond})
	r.a.delay = 2 * time.Second
	start := time.Now()
	res, err := r.agg.GetRates(context.Background(), order(), false)
	if err != nil || time.Since(start) > time.Second || len(res.Options) != 2 || res.FailedCarriers[0].Kind != domain.FailTimeout {
		t.Fatalf("timeout handling: %v %+v after %s", err, res, time.Since(start))
	}
}

func TestCarriersCalledConcurrently(t *testing.T) {
	r := newRig(t, Config{CarrierTimeout: 2 * time.Second})
	r.a.delay, r.b.delay, r.c.delay = 200*time.Millisecond, 200*time.Millisecond, 200*time.Millisecond
	start := time.Now()
	_, _ = r.agg.GetRates(context.Background(), order(), false)
	if el := time.Since(start); el > 450*time.Millisecond {
		t.Fatalf("calls look sequential: %s", el)
	}
}

func TestRedisUnavailableFallsBackToCarriers(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	r.mr.Close() // Redis goes away
	res, err := r.agg.GetRates(context.Background(), order(), false)
	if err != nil || res.Cached || len(res.Options) != 3 {
		t.Fatalf("fallback: %+v %v", res, err)
	}
	if r.m.Get("rate_cache_errors_total") == 0 {
		t.Fatal("cache errors should be counted")
	}
}

func TestConcurrentCacheMissesAreCoalesced(t *testing.T) {
	r := newRig(t, Config{TTL: time.Minute})
	r.a.delay, r.b.delay, r.c.delay = 150*time.Millisecond, 150*time.Millisecond, 150*time.Millisecond
	var wg sync.WaitGroup
	results := make([]Result, 10)
	for i := range results {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			res, err := r.agg.GetRates(context.Background(), order(), false)
			if err != nil {
				t.Error(err)
			}
			results[i] = res
		}(i)
	}
	wg.Wait()
	if r.a.n() != 1 || r.b.n() != 1 || r.c.n() != 1 {
		t.Fatalf("10 identical misses must trigger one fan-out, got %d/%d/%d", r.a.n(), r.b.n(), r.c.n())
	}
	for _, res := range results {
		if len(res.Options) != 3 {
			t.Fatal("every waiter must receive the shared result")
		}
	}
}
