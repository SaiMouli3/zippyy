// Package rates fans out to carriers concurrently, normalizes results, and caches them.
package rates

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"

	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
)

type Config struct {
	TTL            time.Duration // complete results
	PartialTTL     time.Duration // some carriers failed: cache briefly so recovery is fast
	CarrierTimeout time.Duration
}

type Aggregator struct {
	reg     *carriers.Registry
	cache   Cache
	cfg     Config
	metrics *platform.Metrics
	now     func() time.Time
	sf      singleflight.Group
}

func New(reg *carriers.Registry, cache Cache, cfg Config, m *platform.Metrics) *Aggregator {
	if cfg.TTL <= 0 {
		cfg.TTL = 5 * time.Minute
	}
	if cfg.PartialTTL <= 0 {
		cfg.PartialTTL = 30 * time.Second
	}
	if cfg.CarrierTimeout <= 0 {
		cfg.CarrierTimeout = 3 * time.Second
	}
	return &Aggregator{reg: reg, cache: cache, cfg: cfg, metrics: m, now: time.Now}
}

// Result bundles quotes with the raw carrier payloads so they can be persisted per order.
type Result struct {
	domain.RateResult
	CacheKey string
	Raws     [][]byte // parallel to Options
}

// SetClock overrides the time source (tests).
func (a *Aggregator) SetClock(now func() time.Time) { a.now = now }

// GetRates returns normalized, price-sorted quotes. refresh=true bypasses the cache read but still
// repopulates it. Identical concurrent misses are coalesced into a single carrier fan-out.
func (a *Aggregator) GetRates(ctx context.Context, order domain.Order, refresh bool) (Result, error) {
	key := domain.RateCacheKey(order)
	log := platform.L(ctx)

	if !refresh {
		res, raws, err := a.cache.Get(ctx, key)
		switch {
		case err != nil:
			a.metrics.Inc("rate_cache_errors_total")
			log.Warn("rate cache unavailable, falling back to carriers", "event", "RATE_CACHE_ERROR", "error", err.Error())
		case res != nil && res.ExpiresAt.After(a.now()):
			a.metrics.Inc("rate_cache_hits_total")
			log.Info("rate cache hit", "event", "RATE_CACHE_HIT", "key", key)
			return Result{RateResult: *res, CacheKey: key, Raws: raws}, nil
		}
		a.metrics.Inc("rate_cache_misses_total")
	} else {
		a.metrics.Inc("rate_cache_bypass_total")
	}

	sfKey := key
	if refresh {
		sfKey = "refresh:" + key
	}
	v, err, shared := a.sf.Do(sfKey, func() (any, error) {
		// The shared flight must not die because the first caller's request was cancelled.
		fctx := context.WithoutCancel(ctx)
		return a.fetch(fctx, order, key)
	})
	if err != nil {
		return Result{}, err
	}
	if shared {
		a.metrics.Inc("rate_singleflight_shared_total")
	}
	return v.(Result), nil
}

type carrierOutcome struct {
	quotes []domain.Quote
	fail   *domain.FailedCarrier
}

func (a *Aggregator) fetch(ctx context.Context, order domain.Order, key string) (Result, error) {
	log := platform.L(ctx)
	adapters := a.reg.All()
	outcomes := make([]carrierOutcome, len(adapters))
	var wg sync.WaitGroup
	for i, ad := range adapters {
		wg.Add(1)
		go func(i int, ad carriers.Adapter) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					outcomes[i].fail = &domain.FailedCarrier{CarrierCode: ad.Code(), Kind: domain.FailUnavailable, Message: fmt.Sprintf("adapter panic: %v", r)}
				}
			}()
			cctx, cancel := context.WithTimeout(ctx, a.cfg.CarrierTimeout)
			defer cancel()
			start := time.Now()
			qs, err := ad.GetRates(cctx, order)
			a.metrics.Observe("carrier_rate_latency", time.Since(start), "carrier", ad.Code())
			if err != nil {
				outcomes[i].fail = classify(ad.Code(), err)
				a.metrics.Inc("carrier_rate_calls_total", "carrier", ad.Code(), "outcome", string(outcomes[i].fail.Kind))
				log.Warn("carrier rate call failed", "event", "CARRIER_RATE_FAILED", "carrier", ad.Code(), "kind", outcomes[i].fail.Kind, "error", err.Error())
				return
			}
			a.metrics.Inc("carrier_rate_calls_total", "carrier", ad.Code(), "outcome", "OK")
			outcomes[i].quotes = qs
		}(i, ad)
	}
	wg.Wait()

	var quotes []domain.Quote
	failed := []domain.FailedCarrier{}
	for _, o := range outcomes {
		quotes = append(quotes, o.quotes...)
		if o.fail != nil {
			failed = append(failed, *o.fail)
		}
	}
	if len(quotes) == 0 {
		a.metrics.Inc("rate_all_carriers_failed_total")
		return Result{}, domain.NewError(http.StatusBadGateway, "ALL_CARRIERS_FAILED", "no carrier could provide a rate").With("failedCarriers", failed)
	}
	domain.SortQuotes(quotes, domain.SortPrice)

	complete := len(failed) == 0
	ttl := a.cfg.TTL
	if !complete {
		ttl = a.cfg.PartialTTL
	}
	now := a.now()
	res := Result{CacheKey: key}
	res.Options, res.FailedCarriers, res.Complete = quotes, failed, complete
	res.FetchedAt, res.ExpiresAt = now, now.Add(ttl)
	for _, q := range quotes {
		res.Raws = append(res.Raws, q.Raw)
	}
	if err := a.cache.Set(ctx, key, res.RateResult, res.Raws, ttl); err != nil {
		a.metrics.Inc("rate_cache_errors_total")
		log.Warn("rate cache write failed", "event", "RATE_CACHE_ERROR", "error", err.Error())
	}
	return res, nil
}

func classify(code string, err error) *domain.FailedCarrier {
	var ce *carriers.CarrierError
	if errors.As(err, &ce) {
		return &domain.FailedCarrier{CarrierCode: code, Kind: ce.Kind, Message: ce.Message}
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return &domain.FailedCarrier{CarrierCode: code, Kind: domain.FailTimeout, Message: "carrier did not respond in time"}
	}
	return &domain.FailedCarrier{CarrierCode: code, Kind: domain.FailUnavailable, Message: err.Error()}
}
