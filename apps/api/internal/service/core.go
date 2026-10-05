// Package service holds the application layer: use-cases that orchestrate repositories, carrier adapters,
// the rate aggregator and the NDR module. HTTP handlers call these; they never touch SQL or carrier formats.
package service

import (
	"context"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rates"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

// NDRHooks is how the logistics core hands NDR-relevant shipment events to the NDR module without
// importing it (the dependency points one way: ndr -> service types are not needed here).
type NDRHooks interface {
	// OnDeliveryFailed runs inside the webhook transaction and opens (or supersedes into) a case.
	OnDeliveryFailed(ctx context.Context, r *store.Repo, sh *store.Shipment, eventID string, ev carriers.NormalizedEvent) (caseID string, err error)
	// OnShipmentStatus keeps open cases in sync with later carrier events (reattempt started, delivered, RTO).
	OnShipmentStatus(ctx context.Context, r *store.Repo, sh *store.Shipment, status domain.ShipmentStatus) error
	// AfterCommit runs after the webhook transaction commits (e.g. auto-contacting the buyer).
	AfterCommit(ctx context.Context, caseID string)
}

type Services struct {
	Store    *store.Store
	Registry *carriers.Registry
	Rates    *rates.Aggregator
	Metrics  *platform.Metrics
	Verifier WebhookVerifier
	NDR      NDRHooks
	Control  *MockControl
	Now      func() time.Time
	ZippyURL string
}

// audit writes an audit row using request/actor context.
func (s *Services) audit(ctx context.Context, r *store.Repo, e store.AuditEntry) {
	e.RequestID = platform.RequestID(ctx)
	if e.Actor == "" {
		a := platform.ActorFrom(ctx)
		e.Actor = a.Name
		if e.ActorType == "" {
			e.ActorType = actorTypeFromRole(a.Role)
		}
	}
	if e.Actor == "" {
		e.Actor, e.ActorType = "system", domain.ActorSystem
	}
	if e.ActorType == "" {
		e.ActorType = domain.ActorSystem
	}
	if err := r.InsertAudit(ctx, e); err != nil {
		platform.L(ctx).Error("audit write failed", "error", err.Error(), "action", e.Action)
	}
}

func actorTypeFromRole(role string) string {
	switch role {
	case domain.RoleSeller:
		return domain.ActorSeller
	case domain.RoleOps:
		return domain.ActorOps
	}
	return domain.ActorSystem
}
