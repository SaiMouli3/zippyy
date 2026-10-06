// Package platform holds cross-cutting infrastructure: structured logging, request ids, metrics, masking.
package platform

import (
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
)

type ctxKey int

const (
	loggerKey ctxKey = iota
	requestIDKey
	actorKey
)

// NewLogger builds the JSON logger used across the app.
func NewLogger(w io.Writer, level string) *slog.Logger {
	if w == nil {
		w = os.Stdout
	}
	lvl := slog.LevelInfo
	switch strings.ToLower(level) {
	case "debug":
		lvl = slog.LevelDebug
	case "warn":
		lvl = slog.LevelWarn
	case "error":
		lvl = slog.LevelError
	}
	return slog.New(slog.NewJSONHandler(w, &slog.HandlerOptions{Level: lvl})).With("service", "zippy-api")
}

func WithLogger(ctx context.Context, l *slog.Logger) context.Context {
	return context.WithValue(ctx, loggerKey, l)
}

// L returns the request-scoped logger, falling back to the default logger.
func L(ctx context.Context) *slog.Logger {
	if l, ok := ctx.Value(loggerKey).(*slog.Logger); ok && l != nil {
		return l
	}
	return slog.Default()
}

// With adds fields (orderId, shipmentId, ndrCaseId, carrier, ...) to the context logger so every
// downstream log line is traceable.
func With(ctx context.Context, args ...any) context.Context {
	return WithLogger(ctx, L(ctx).With(args...))
}

func WithRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, requestIDKey, id)
}

func RequestID(ctx context.Context) string {
	s, _ := ctx.Value(requestIDKey).(string)
	return s
}

// Actor is the authenticated-ish caller identity attached to a request (MVP: header based).
type Actor struct {
	Name string
	Role string // SELLER | OPS | SYSTEM
}

func WithActor(ctx context.Context, a Actor) context.Context {
	return context.WithValue(ctx, actorKey, a)
}

func ActorFrom(ctx context.Context) Actor {
	a, _ := ctx.Value(actorKey).(Actor)
	return a
}

// MaskPhone keeps the last 4 digits: 98XXXXXX10 style masking for logs and audit payloads.
func MaskPhone(p string) string {
	if len(p) <= 4 {
		return strings.Repeat("X", len(p))
	}
	return strings.Repeat("X", len(p)-4) + p[len(p)-4:]
}
