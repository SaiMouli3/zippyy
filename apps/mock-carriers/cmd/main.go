package main

import (
	"log/slog"
	"os"

	"github.com/saimouli3/zippyy/apps/mock-carriers/mockcarriers"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service", "mock-carriers")
	srv := mockcarriers.New(mockcarriers.Config{
		ZippyWebhookBase: env("ZIPPY_WEBHOOK_BASE", "http://localhost:8080"),
		Secrets: map[string]string{
			"FASTSHIP":     os.Getenv("FASTSHIP_WEBHOOK_SECRET"),
			"QUICKEXPRESS": os.Getenv("QUICKEXPRESS_WEBHOOK_SECRET"),
			"RELIABLE":     os.Getenv("RELIABLE_WEBHOOK_SECRET"),
		},
	}, log)
	addr := ":" + env("PORT", "9000")
	log.Info("mock carriers listening", "addr", addr)
	if err := srv.App().Listen(addr); err != nil {
		log.Error("server stopped", "error", err.Error())
		os.Exit(1)
	}
}
