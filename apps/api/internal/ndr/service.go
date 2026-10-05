// Package ndr orchestrates the NDR (non-delivery report) workflow:
//
//	carrier NDR webhook -> case -> buyer conversation -> intent extraction (AI) -> rules engine (deterministic)
//	-> approval (if required) -> carrier action -> carrier acceptance -> buyer confirmation -> delivery/RTO.
//
// Orchestration lives here; decisions live in internal/rules; language lives in internal/agent.
package ndr

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/agent"
	"github.com/saimouli3/zippyy/apps/api/internal/carriers"
	"github.com/saimouli3/zippyy/apps/api/internal/comms"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type Config struct {
	ConfidenceMin       float64
	AutoContact         bool
	PaymentBaseURL      string
	ActionRetries       int
	RetryBackoff        time.Duration
	DefaultBuyerTimeout time.Duration
}

type Service struct {
	Store    *store.Store
	Registry *carriers.Registry
	LLM      agent.LLMProvider
	Comms    *comms.Dispatcher
	Metrics  *platform.Metrics
	Cfg      Config
	Now      func() time.Time

	locks sync.Map // case id -> *sync.Mutex (serialises mutations of one case within this process)
}

func New(st *store.Store, reg *carriers.Registry, llm agent.LLMProvider, c *comms.Dispatcher, m *platform.Metrics, cfg Config) *Service {
	if cfg.ConfidenceMin <= 0 {
		cfg.ConfidenceMin = 0.75
	}
	if cfg.ActionRetries <= 0 {
		cfg.ActionRetries = 3
	}
	if cfg.RetryBackoff <= 0 {
		cfg.RetryBackoff = 150 * time.Millisecond
	}
	if cfg.PaymentBaseURL == "" {
		cfg.PaymentBaseURL = "https://pay.zippyy.example/p"
	}
	if cfg.DefaultBuyerTimeout <= 0 {
		cfg.DefaultBuyerTimeout = 4 * time.Hour
	}
	return &Service{Store: st, Registry: reg, LLM: llm, Comms: c, Metrics: m, Cfg: cfg, Now: time.Now}
}

func (s *Service) lock(id string) func() {
	v, _ := s.locks.LoadOrStore(id, &sync.Mutex{})
	mu := v.(*sync.Mutex)
	mu.Lock()
	return mu.Unlock
}

// withCase resolves a case by uuid or case number, serialises mutation, and passes a fresh copy to fn.
func (s *Service) withCase(ctx context.Context, ref string, fn func(ctx context.Context, c *store.NDRCase) error) error {
	r := s.Store.R()
	c, err := r.GetCase(ctx, ref, false)
	if err == store.ErrNotFound {
		c, err = r.GetCaseByNumber(ctx, ref)
	}
	if err == store.ErrNotFound || (err != nil && isBadUUID(err)) {
		c, err = r.GetCaseByNumber(ctx, ref)
	}
	if err == store.ErrNotFound {
		return domain.NotFound("NDR case")
	} else if err != nil {
		return err
	}
	unlock := s.lock(c.ID)
	defer unlock()
	fresh, err := r.GetCase(ctx, c.ID, false)
	if err != nil {
		return err
	}
	ctx = platform.With(ctx, "ndrCaseId", fresh.ID, "orderId", fresh.ZippyOrderID, "shipmentId", fresh.ShipmentID, "carrier", fresh.CarrierCode)
	return fn(ctx, fresh)
}

func isBadUUID(err error) bool {
	return err != nil && (contains(err.Error(), "invalid input syntax for type uuid") || contains(err.Error(), "SQLSTATE 22P02"))
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

// ---- state machine plumbing -------------------------------------------------------------------

type who struct {
	Actor string
	Type  string
}

var (
	agentActor  = who{"zippy-agent", domain.ActorAgent}
	systemActor = who{"zippy-system", domain.ActorSystem}
	buyerActor  = who{"buyer", domain.ActorBuyer}
)

func carrierActor(code string) who { return who{code, domain.ActorCarrier} }

func actorFromCtx(ctx context.Context) who {
	a := platform.ActorFrom(ctx)
	switch a.Role {
	case domain.RoleSeller:
		return who{a.Name, domain.ActorSeller}
	case domain.RoleOps:
		return who{a.Name, domain.ActorOps}
	}
	return systemActor
}

// moveR changes state through the case state machine. It is the ONLY way case.State changes.
func (s *Service) moveR(ctx context.Context, r *store.Repo, c *store.NDRCase, to domain.CaseState, w who, eventType, desc string, data any) error {
	if c.State != to && !domain.CanTransition(c.State, to) {
		return domain.Conflict("INVALID_CASE_TRANSITION", fmt.Sprintf("case cannot move from %s to %s", c.State, to)).With("from", c.State).With("to", to)
	}
	prev := c.State
	c.State = to
	if err := r.SaveCase(ctx, c); err != nil {
		return err
	}
	if err := r.InsertNDREvent(ctx, c.ID, eventType, w.Actor, w.Type, desc, data); err != nil {
		return err
	}
	return r.InsertAudit(ctx, store.AuditEntry{Actor: w.Actor, ActorType: w.Type, Action: eventType, OrderID: c.OrderID, ShipmentID: c.ShipmentID, NDRCaseID: c.ID,
		PreviousState: string(prev), NewState: string(to), Evidence: data, RequestID: platform.RequestID(ctx)})
}

func (s *Service) move(ctx context.Context, c *store.NDRCase, to domain.CaseState, w who, eventType, desc string, data any) error {
	return s.Store.InTx(ctx, func(r *store.Repo) error { return s.moveR(ctx, r, c, to, w, eventType, desc, data) })
}

// noteR records a timeline event + audit row without changing state.
func (s *Service) noteR(ctx context.Context, r *store.Repo, c *store.NDRCase, w who, eventType, desc string, data any) error {
	if err := r.InsertNDREvent(ctx, c.ID, eventType, w.Actor, w.Type, desc, data); err != nil {
		return err
	}
	return r.InsertAudit(ctx, store.AuditEntry{Actor: w.Actor, ActorType: w.Type, Action: eventType, OrderID: c.OrderID, ShipmentID: c.ShipmentID, NDRCaseID: c.ID,
		PreviousState: string(c.State), NewState: string(c.State), Evidence: data, RequestID: platform.RequestID(ctx)})
}

func (s *Service) note(ctx context.Context, c *store.NDRCase, w who, eventType, desc string, data any) error {
	return s.Store.InTx(ctx, func(r *store.Repo) error { return s.noteR(ctx, r, c, w, eventType, desc, data) })
}

// closeR finishes a case from any open state, passing through RESOLVED when the machine allows it.
func (s *Service) closeR(ctx context.Context, r *store.Repo, c *store.NDRCase, outcome string, w who, desc string) error {
	if c.State == domain.CaseClosed {
		return nil
	}
	if domain.CanTransition(c.State, domain.CaseResolved) {
		c.Outcome = outcome
		if err := s.moveR(ctx, r, c, domain.CaseResolved, w, "CASE_RESOLVED", desc, map[string]any{"outcome": outcome}); err != nil {
			return err
		}
	}
	c.Outcome = outcome
	c.Plan, c.Pending = nil, nil
	now := s.Now()
	c.ClosedAt = &now
	return s.moveR(ctx, r, c, domain.CaseClosed, w, "CASE_CLOSED", desc, map[string]any{"outcome": outcome})
}

// ---- logistics hooks (called from the webhook transaction) ------------------------------------

func (s *Service) OnDeliveryFailed(ctx context.Context, r *store.Repo, sh *store.Shipment, eventID string, ev carriers.NormalizedEvent) (string, error) {
	order, err := r.GetOrder(ctx, sh.OrderID, false)
	if err != nil {
		return "", err
	}
	if active, err := r.ActiveCaseForShipment(ctx, sh.ID); err == nil {
		if err := s.closeR(ctx, r, active, domain.OutcomeSuperseded, carrierActor(sh.CarrierCode), "A new delivery failure superseded this case"); err != nil {
			return "", err
		}
	} else if err != store.ErrNotFound {
		return "", err
	}
	n, err := r.CountCasesForShipment(ctx, sh.ID)
	if err != nil {
		return "", err
	}
	attempt := n + 1

	reason, source := ev.NDRReason, "MAPPING"
	var interp map[string]any
	if reason == "" { // generic/unknown carrier code: let the language layer interpret the remark; rules never depend on this guess for permissions
		rr, conf, _ := s.LLM.InterpretRemark(ctx, ev.NDRRemark+" "+ev.Description)
		reason, source = rr, "LLM_REMARK"
		interp = map[string]any{"remark": ev.NDRRemark, "interpretedAs": rr, "confidence": conf}
		if conf < 0.5 {
			source = "LLM_REMARK_LOW_CONFIDENCE"
		}
	}
	seller, err := r.GetOrCreateSellerRules(ctx, order.MerchantID)
	if err != nil {
		return "", err
	}
	carrier, err := r.GetCarrierRules(ctx, sh.CarrierCode)
	if err == store.ErrNotFound {
		carrier = &domain.CarrierRules{CarrierCode: sh.CarrierCode, MaxAttempts: 3, InstructionCutoff: "20:00", HoldWindowDays: 3}
	} else if err != nil {
		return "", err
	}
	lang, langSource := s.resolveLanguage(ctx, r, order)
	c, err := r.InsertCase(ctx, store.NewCase{ShipmentID: sh.ID, OrderID: sh.OrderID, ShipmentEventID: eventID, CarrierCode: sh.CarrierCode, CarrierReasonCode: ev.NDRReasonCode, CarrierRemark: ev.NDRRemark,
		AttemptNumber: attempt, Reason: reason, ReasonSource: source, Language: lang, LanguageSource: langSource, RecommendedAction: rules.RecommendedAction(reason),
		SellerRules: seller, CarrierConstraints: carrier, State: domain.CaseOpened})
	if err != nil {
		return "", err
	}
	data := map[string]any{"carrierReasonCode": ev.NDRReasonCode, "carrierRemark": ev.NDRRemark, "normalizedReason": reason, "reasonSource": source, "attempt": attempt, "language": lang, "languageSource": langSource, "interpretation": interp}
	if err := r.InsertNDREvent(ctx, c.ID, "CARRIER_NDR", sh.CarrierCode, domain.ActorCarrier, fmt.Sprintf("Carrier reported a failed delivery attempt #%d (%s → %s)", attempt, ev.NDRReasonCode, reason), data); err != nil {
		return "", err
	}
	if err := r.InsertAudit(ctx, store.AuditEntry{Actor: sh.CarrierCode, ActorType: domain.ActorCarrier, Action: "NDR_CASE_OPENED", OrderID: sh.OrderID, ShipmentID: sh.ID, NDRCaseID: c.ID,
		NewState: string(domain.CaseOpened), Evidence: data, RequestID: platform.RequestID(ctx)}); err != nil {
		return "", err
	}
	s.Metrics.Inc("ndr_cases_opened_total", "reason", string(reason), "carrier", sh.CarrierCode)
	if reason == domain.ReasonOutOfArea {
		if err := s.moveR(ctx, r, c, domain.CaseEscalated, agentActor, "ESCALATED_TO_OPS", "Address is outside the carrier's delivery area: escalated to carrier/ops, no buyer action possible", map[string]any{"playbook": "ESCALATE_TO_CARRIER_OPS"}); err != nil {
			return "", err
		}
	}
	return c.ID, nil
}

func (s *Service) OnShipmentStatus(ctx context.Context, r *store.Repo, sh *store.Shipment, status domain.ShipmentStatus) error {
	c, err := r.ActiveCaseForShipment(ctx, sh.ID)
	if err == store.ErrNotFound {
		return nil
	} else if err != nil {
		return err
	}
	ctx = platform.With(ctx, "ndrCaseId", c.ID)
	w := carrierActor(sh.CarrierCode)
	switch status {
	case domain.StatusOutForDelivery:
		return s.noteR(ctx, r, c, w, "REATTEMPT_STARTED", "Carrier is out for delivery again (reattempt in progress)", map[string]any{"caseState": c.State})
	case domain.StatusDelivered:
		return s.closeR(ctx, r, c, domain.OutcomeDelivered, w, "Shipment delivered; NDR case closed")
	case domain.StatusRTO:
		return s.closeR(ctx, r, c, domain.OutcomeRTO, w, "Shipment returned to origin (RTO); NDR case closed")
	}
	return nil
}

func (s *Service) AfterCommit(ctx context.Context, caseID string) {
	if !s.Cfg.AutoContact {
		return
	}
	if _, err := s.Contact(ctx, caseID, ContactOptions{}); err != nil {
		platform.L(ctx).Warn("auto-contact failed", "event", "NDR_AUTO_CONTACT_FAILED", "ndrCaseId", caseID, "error", err.Error())
	}
}

// resolveLanguage applies priority: stored buyer preference > seller order language > pincode default > English.
// (The buyer's live reply, the highest priority, is applied when the reply arrives.)
func (s *Service) resolveLanguage(ctx context.Context, r *store.Repo, o *domain.Order) (string, string) {
	if p, err := r.GetBuyerProfile(ctx, o.Customer.Phone); err == nil && domain.SupportedLanguage(p.PreferredLanguage) {
		return p.PreferredLanguage, "stored"
	}
	if domain.SupportedLanguage(o.Language) {
		return o.Language, "seller"
	}
	return agent.PincodeLanguage(o.DeliveryAddress.Pincode), "pincode"
}

// ---- read models ------------------------------------------------------------------------------

type CaseDetail struct {
	Case         store.NDRCase         `json:"case"`
	Order        *domain.Order         `json:"order"`
	Shipment     *store.Shipment       `json:"shipment"`
	Messages     []store.Message       `json:"messages"`
	Events       []store.NDREvent      `json:"events"`
	CommAttempts []store.CommAttempt   `json:"communicationAttempts"`
	Actions      []store.CarrierAction `json:"carrierActions"`
	Approvals    []store.Approval      `json:"approvals"`
	SellerRules  *domain.SellerRules   `json:"sellerRules"`
	CarrierRules *domain.CarrierRules  `json:"carrierRules"`
	NextSteps    []string              `json:"nextSteps"`
}

func (s *Service) ListCases(ctx context.Context, f store.CaseFilter) ([]store.NDRCase, error) {
	return s.Store.R().ListCases(ctx, f)
}

func (s *Service) caseByRef(ctx context.Context, r *store.Repo, ref string) (*store.NDRCase, error) {
	c, err := r.GetCase(ctx, ref, false)
	if err == store.ErrNotFound || isBadUUID(err) {
		c, err = r.GetCaseByNumber(ctx, ref)
	}
	if err == store.ErrNotFound {
		return nil, domain.NotFound("NDR case")
	}
	return c, err
}

func (s *Service) GetCase(ctx context.Context, ref string) (*CaseDetail, error) {
	r := s.Store.R()
	c, err := s.caseByRef(ctx, r, ref)
	if err != nil {
		return nil, err
	}
	d := &CaseDetail{Case: *c}
	if d.Order, err = r.GetOrder(ctx, c.OrderID, false); err != nil {
		return nil, err
	}
	if d.Shipment, err = r.GetShipment(ctx, c.ShipmentID); err != nil {
		return nil, err
	}
	if d.Messages, err = r.ListMessages(ctx, c.ID); err != nil {
		return nil, err
	}
	if d.Events, err = r.ListNDREvents(ctx, c.ID); err != nil {
		return nil, err
	}
	if d.CommAttempts, err = r.ListCommAttempts(ctx, c.ID); err != nil {
		return nil, err
	}
	if d.Actions, err = r.ListActions(ctx, c.ID); err != nil {
		return nil, err
	}
	if d.Approvals, err = r.ListApprovals(ctx, "", c.ID, 100); err != nil {
		return nil, err
	}
	d.SellerRules, _ = r.GetSellerRules(ctx, d.Order.MerchantID)
	d.CarrierRules, _ = r.GetCarrierRules(ctx, c.CarrierCode)
	d.NextSteps = nextSteps(c, d.Approvals)
	return d, nil
}

// nextSteps tells the UI which operator actions make sense; the backend still enforces everything.
func nextSteps(c *store.NDRCase, approvals []store.Approval) []string {
	var out []string
	switch c.State {
	case domain.CaseOpened:
		out = append(out, "CONTACT_BUYER")
	case domain.CaseBuyerContactPending:
		out = append(out, "BUYER_REPLY", "SIMULATE_NO_RESPONSE", "CONTACT_BUYER")
	case domain.CaseAwaitingApproval:
		for _, a := range approvals {
			if a.Status == "PENDING" && a.Blocking {
				out = append(out, "DECIDE_APPROVAL")
				break
			}
		}
		out = append(out, "SIMULATE_SELLER_NO_RESPONSE")
	case domain.CaseEscalated:
		out = append(out, "MANUAL_ACTION", "CONTACT_BUYER", "RETRY_ACTION")
	case domain.CaseActionPending:
		out = append(out, "RETRY_ACTION")
	case domain.CaseReattemptScheduled, domain.CaseRTOInitiated, domain.CaseCarrierAccepted:
		out = append(out, "WAIT_FOR_CARRIER_EVENT")
	}
	return out
}

func (s *Service) Timeline(ctx context.Context, ref string) ([]store.NDREvent, error) {
	r := s.Store.R()
	c, err := s.caseByRef(ctx, r, ref)
	if err != nil {
		return nil, err
	}
	return r.ListNDREvents(ctx, c.ID)
}

func jsonRaw(v any) json.RawMessage {
	b, _ := json.Marshal(v)
	return b
}

var _ = http.StatusOK

func jsonUnmarshal(b json.RawMessage, v any) error {
	if len(b) == 0 {
		return fmt.Errorf("empty")
	}
	return json.Unmarshal(b, v)
}
