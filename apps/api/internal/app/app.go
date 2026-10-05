// Package app wires configuration, infrastructure and services together. cmd/server and the end-to-end
// tests both build the application through here so tests exercise the real wiring.
package app

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/saimouli3/zippyy/apps/api/internal/agent"
	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/comms"
	"github.com/saimouli3/zippyy/apps/api/internal/config"
	"github.com/saimouli3/zippyy/apps/api/internal/httpapi"
	"github.com/saimouli3/zippyy/apps/api/internal/ndr"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rates"
	"github.com/saimouli3/zippyy/apps/api/internal/service"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type App struct {
	Cfg      config.Config
	Log      *slog.Logger
	Store    *store.Store
	Redis    *redis.Client
	Services *service.Services
	NDR      *ndr.Service
	HTTP     *httpapi.API
	Metrics  *platform.Metrics
	Rates    *rates.Aggregator
}

type Options struct {
	Config config.Config
	Log    *slog.Logger
	Now    func() time.Time
	LLM    agent.LLMProvider
	Comms  *comms.Dispatcher
	// NDRRetryBackoff lets tests shrink carrier-action retry sleeps.
	NDRRetryBackoff time.Duration
}

func Build(ctx context.Context, o Options) (*App, error) {
	cfg, log := o.Config, o.Log
	if log == nil {
		log = platform.NewLogger(nil, cfg.LogLevel)
	}
	now := o.Now
	if now == nil {
		now = time.Now
	}
	st, err := store.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("postgres: %w", err)
	}
	if err := st.Migrate(ctx); err != nil {
		return nil, fmt.Errorf("migrate: %w", err)
	}
	metrics := platform.NewMetrics()

	// Redis is an optimisation: failure to connect degrades to direct carrier calls, never to an outage.
	var cache rates.Cache = rates.NoopCache{}
	var rdb *redis.Client
	if cfg.RedisURL != "" {
		if opt, err := redis.ParseURL(cfg.RedisURL); err == nil {
			opt.DialTimeout, opt.ReadTimeout, opt.WriteTimeout, opt.MaxRetries = 300*time.Millisecond, 300*time.Millisecond, 300*time.Millisecond, 1
			rdb = redis.NewClient(opt)
			cache = rates.NewRedisCache(rdb)
			if err := rdb.Ping(ctx).Err(); err != nil {
				log.Warn("redis not reachable at boot; rate caching will retry per request", "error", err.Error())
			}
		} else {
			log.Warn("invalid REDIS_URL; rate caching disabled", "error", err.Error())
		}
	}

	cc := func(base string) carriers.Config {
		return carriers.Config{BaseURL: base, Timeout: cfg.CarrierTimeout, ZippyPublicURL: cfg.ZippyPublicURL}
	}
	registry := carriers.NewRegistry(carriers.NewFastShip(cc(cfg.FastShipBaseURL)), carriers.NewQuickExpress(cc(cfg.QuickExpressBaseURL)), carriers.NewReliable(cc(cfg.ReliableBaseURL)))
	agg := rates.New(registry, cache, rates.Config{TTL: cfg.CacheTTL, PartialTTL: cfg.PartialCacheTTL, CarrierTimeout: cfg.CarrierTimeout}, metrics)

	agg.SetClock(now)

	llm := o.LLM
	if llm == nil {
		llm = agent.NewMock() // LLM_PROVIDER=mock; a real provider plugs in here behind agent.LLMProvider
		if cfg.LLMProvider != "mock" && cfg.LLMProvider != "" {
			log.Warn("unknown LLM_PROVIDER, falling back to mock", "provider", cfg.LLMProvider)
		}
	}
	dispatcher := o.Comms
	if dispatcher == nil {
		dispatcher = comms.NewMockDispatcher()
	}
	ndrSvc := ndr.New(st, registry, llm, dispatcher, metrics, ndr.Config{ConfidenceMin: cfg.IntentConfidenceMin, AutoContact: cfg.NDRAutoContact, DefaultBuyerTimeout: cfg.NDRContactTimeout, RetryBackoff: o.NDRRetryBackoff})
	ndrSvc.Now = now

	svc := &service.Services{
		Store: st, Registry: registry, Rates: agg, Metrics: metrics, Now: now, ZippyURL: cfg.ZippyPublicURL, NDR: ndrSvc,
		Verifier: service.HMACVerifier{Secrets: cfg.WebhookSecrets, Required: cfg.WebhookSignatureRequired},
		Control:  service.NewMockControl(map[string]string{carriers.FastShip: cfg.FastShipBaseURL, carriers.QuickExpress: cfg.QuickExpressBaseURL, carriers.Reliable: cfg.ReliableBaseURL}, cfg.ZippyPublicURL),
	}
	api := &httpapi.API{Svc: svc, NDR: ndrSvc, Store: st, Log: log, Metrics: metrics, Origins: cfg.AllowedOrigins,
		Ready: func(ctx context.Context) error { return st.Ping(ctx) }}
	return &App{Cfg: cfg, Log: log, Store: st, Redis: rdb, Services: svc, NDR: ndrSvc, HTTP: api, Metrics: metrics, Rates: agg}, nil
}

func (a *App) Close() {
	if a.Redis != nil {
		_ = a.Redis.Close()
	}
	a.Store.Close()
}

// RunTimeoutSweeper periodically fires buyer/seller no-response triggers until ctx is cancelled.
func (a *App) RunTimeoutSweeper(ctx context.Context) {
	t := time.NewTicker(a.Cfg.NDRSweepInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			a.NDR.SweepTimeouts(platform.WithLogger(ctx, a.Log))
		}
	}
}
