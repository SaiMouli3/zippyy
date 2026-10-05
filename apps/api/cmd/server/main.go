package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/app"
	"github.com/saimouli3/zippyy/apps/api/internal/config"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
)

func main() {
	cfg := config.Load()
	log := platform.NewLogger(nil, cfg.LogLevel)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// wait for Postgres (compose healthchecks help, but a retry loop makes boot order irrelevant)
	var a *app.App
	var err error
	for i := 0; i < 30; i++ {
		a, err = app.Build(ctx, app.Options{Config: cfg, Log: log})
		if err == nil {
			break
		}
		log.Warn("waiting for dependencies", "attempt", i+1, "error", err.Error())
		select {
		case <-ctx.Done():
			return
		case <-time.After(2 * time.Second):
		}
	}
	if err != nil {
		log.Error("startup failed", "error", err.Error())
		os.Exit(1)
	}
	defer a.Close()

	go a.RunTimeoutSweeper(ctx)
	if cfg.SeedDemo {
		go a.SeedWithRetry(ctx)
	}
	srv := a.HTTP.App()
	go func() {
		<-ctx.Done()
		_ = srv.ShutdownWithContext(context.Background())
	}()
	log.Info("zippy api listening", "port", cfg.Port, "llm", cfg.LLMProvider)
	if err := srv.Listen(":" + cfg.Port); err != nil {
		log.Error("server stopped", "error", err.Error())
		os.Exit(1)
	}
}
