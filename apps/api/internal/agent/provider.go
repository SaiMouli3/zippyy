// Package agent is the ONLY place natural-language understanding and generation live.
//
// AI boundary (see docs/architecture.md): the LLMProvider may
//  1. converse (ComposeMessage),
//  2. extract structured intent from buyer text (ExtractIntent),
//  3. interpret messy carrier remarks (InterpretRemark).
//
// It must never decide state transitions, permissions, cutoffs, attempt counts, RTO, idempotency or quote
// validity — those live in internal/rules and internal/domain, which never import this package.
package agent

import (
	"context"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

type IntentContext struct {
	Now             time.Time
	CaseLanguage    string
	Reason          domain.NDRReason
	DeliveryPincode string
	DeliveryCity    string
}

type LLMProvider interface {
	Name() string
	// ExtractIntent returns structured intent for one buyer message. The original text is never altered.
	ExtractIntent(ctx context.Context, text string, ic IntentContext) (domain.ExtractedIntent, error)
	// InterpretRemark maps a free-text carrier remark to the normalized taxonomy with a confidence.
	InterpretRemark(ctx context.Context, remark string) (domain.NDRReason, float64, error)
	// ComposeMessage renders a buyer-facing message for a semantic key in the given language.
	ComposeMessage(ctx context.Context, key, lang string, params map[string]string) (string, error)
}
