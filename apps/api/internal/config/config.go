// Package config loads runtime configuration from environment variables (12-factor).
package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Port        string
	DatabaseURL string
	RedisURL    string
	LogLevel    string

	FastShipBaseURL     string
	QuickExpressBaseURL string
	ReliableBaseURL     string
	ZippyPublicURL      string // how carriers reach this API for webhooks / callbacks

	CacheTTL        time.Duration
	PartialCacheTTL time.Duration
	CarrierTimeout  time.Duration

	WebhookSecrets           map[string]string // carrier code -> HMAC secret
	WebhookSignatureRequired bool

	LLMProvider         string
	IntentConfidenceMin float64
	NDRContactTimeout   time.Duration // buyer response timeout fallback
	NDRAutoContact      bool
	NDRSweepInterval    time.Duration
	SeedDemo            bool
	AllowedOrigins      string
}

func Load() Config {
	return Config{
		Port:        env("PORT", "8080"),
		DatabaseURL: env("DATABASE_URL", "postgres://zippy:zippy@localhost:5432/zippy?sslmode=disable"),
		RedisURL:    env("REDIS_URL", "redis://localhost:6379/0"),
		LogLevel:    env("LOG_LEVEL", "info"),

		FastShipBaseURL:     env("FASTSHIP_BASE_URL", "http://localhost:9000"),
		QuickExpressBaseURL: env("QUICKEXPRESS_BASE_URL", "http://localhost:9000"),
		ReliableBaseURL:     env("RELIABLECOURIER_BASE_URL", "http://localhost:9000"),
		ZippyPublicURL:      env("ZIPPY_PUBLIC_URL", "http://localhost:8080"),

		CacheTTL:        seconds("CACHE_TTL_SECONDS", 300),
		PartialCacheTTL: seconds("CACHE_PARTIAL_TTL_SECONDS", 30),
		CarrierTimeout:  millis("CARRIER_TIMEOUT_MS", 3000),

		WebhookSecrets: map[string]string{
			"FASTSHIP":     os.Getenv("FASTSHIP_WEBHOOK_SECRET"),
			"QUICKEXPRESS": os.Getenv("QUICKEXPRESS_WEBHOOK_SECRET"),
			"RELIABLE":     os.Getenv("RELIABLE_WEBHOOK_SECRET"),
		},
		WebhookSignatureRequired: boolEnv("WEBHOOK_SIGNATURE_REQUIRED", false),

		LLMProvider:         env("LLM_PROVIDER", "mock"),
		IntentConfidenceMin: floatEnv("INTENT_CONFIDENCE_MIN", 0.75),
		NDRContactTimeout:   seconds("NDR_CONTACT_TIMEOUT", 4*3600),
		NDRAutoContact:      boolEnv("NDR_AUTO_CONTACT", false),
		NDRSweepInterval:    seconds("NDR_SWEEP_INTERVAL_SECONDS", 60),
		SeedDemo:            boolEnv("SEED_DEMO", false),
		AllowedOrigins:      env("CORS_ALLOWED_ORIGINS", "*"),
	}
}

func env(k, d string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return d
}

func seconds(k string, d int) time.Duration {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return time.Duration(n) * time.Second
		}
	}
	return time.Duration(d) * time.Second
}

func millis(k string, d int) time.Duration {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return time.Duration(n) * time.Millisecond
		}
	}
	return time.Duration(d) * time.Millisecond
}

func boolEnv(k string, d bool) bool {
	if v := os.Getenv(k); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return d
}

func floatEnv(k string, d float64) float64 {
	if v := os.Getenv(k); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return d
}
