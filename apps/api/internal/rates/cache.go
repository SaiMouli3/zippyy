package rates

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// Cache stores aggregated normalized rate results. Implementations must treat a miss as (nil, nil).
type Cache interface {
	Get(ctx context.Context, key string) (*domain.RateResult, [][]byte, error)
	Set(ctx context.Context, key string, res domain.RateResult, raws [][]byte, ttl time.Duration) error
}

type entry struct {
	Options   []entryQuote           `json:"options"`
	Failed    []domain.FailedCarrier `json:"failed"`
	Complete  bool                   `json:"complete"`
	FetchedAt time.Time              `json:"fetchedAt"`
	ExpiresAt time.Time              `json:"expiresAt"`
}

type entryQuote struct {
	Quote domain.Quote    `json:"quote"`
	Raw   json.RawMessage `json:"raw,omitempty"`
}

// RedisCache is the production cache. Every operation is bounded by opTimeout so a hung Redis
// degrades to direct carrier calls instead of stalling requests.
type RedisCache struct {
	rdb       *redis.Client
	opTimeout time.Duration
}

func NewRedisCache(rdb *redis.Client) *RedisCache {
	return &RedisCache{rdb: rdb, opTimeout: 300 * time.Millisecond}
}

func (c *RedisCache) Get(ctx context.Context, key string) (*domain.RateResult, [][]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, c.opTimeout)
	defer cancel()
	b, err := c.rdb.Get(ctx, key).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	var e entry
	if err := json.Unmarshal(b, &e); err != nil {
		return nil, nil, err // corrupt entry: caller treats as miss and overwrites
	}
	res := &domain.RateResult{FailedCarriers: e.Failed, Complete: e.Complete, FetchedAt: e.FetchedAt, ExpiresAt: e.ExpiresAt, Cached: true}
	raws := make([][]byte, 0, len(e.Options))
	for _, o := range e.Options {
		res.Options = append(res.Options, o.Quote)
		raws = append(raws, o.Raw)
	}
	return res, raws, nil
}

func (c *RedisCache) Set(ctx context.Context, key string, res domain.RateResult, raws [][]byte, ttl time.Duration) error {
	e := entry{Failed: res.FailedCarriers, Complete: res.Complete, FetchedAt: res.FetchedAt, ExpiresAt: res.ExpiresAt}
	for i, q := range res.Options {
		var raw json.RawMessage
		if i < len(raws) {
			raw = raws[i]
		}
		e.Options = append(e.Options, entryQuote{Quote: q, Raw: raw})
	}
	b, err := json.Marshal(e)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, c.opTimeout)
	defer cancel()
	return c.rdb.Set(ctx, key, b, ttl).Err()
}

// NoopCache disables caching (used when Redis is not configured).
type NoopCache struct{}

func (NoopCache) Get(context.Context, string) (*domain.RateResult, [][]byte, error) {
	return nil, nil, nil
}
func (NoopCache) Set(context.Context, string, domain.RateResult, [][]byte, time.Duration) error {
	return nil
}
