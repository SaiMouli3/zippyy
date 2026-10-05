package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// ---- rules ----

func (r *Repo) GetSellerRules(ctx context.Context, merchantID string) (*domain.SellerRules, error) {
	var s domain.SellerRules
	err := r.q.QueryRow(ctx, `SELECT merchant_id, max_attempts, auto_rto_attempt, cod_limit::float8, allowed_channels, comm_hours_start, comm_hours_end, enforce_comm_hours,
	  prepaid_conversion_allowed, allow_address_changes, early_rto_policy, allowed_actions, default_on_silence, buyer_response_timeout_minutes, seller_response_timeout_minutes, updated_at
	  FROM seller_rules WHERE merchant_id=$1`, merchantID).Scan(&s.MerchantID, &s.MaxAttempts, &s.AutoRTOAttempt, &s.CODLimit, &s.AllowedChannels, &s.CommHoursStart, &s.CommHoursEnd,
		&s.EnforceCommHours, &s.PrepaidConversionAllowed, &s.AllowAddressChanges, &s.EarlyRTOPolicy, &s.AllowedActions, &s.DefaultOnSilence, &s.BuyerResponseTimeoutMinutes, &s.SellerResponseTimeoutMinutes, &s.UpdatedAt)
	return &s, notFound(err)
}

// GetOrCreateSellerRules returns merchant rules, inserting platform defaults for new merchants.
func (r *Repo) GetOrCreateSellerRules(ctx context.Context, merchantID string) (*domain.SellerRules, error) {
	if _, err := r.q.Exec(ctx, `INSERT INTO seller_rules (merchant_id) VALUES ($1) ON CONFLICT DO NOTHING`, merchantID); err != nil {
		return nil, err
	}
	return r.GetSellerRules(ctx, merchantID)
}

func (r *Repo) ListSellerRules(ctx context.Context) ([]domain.SellerRules, error) {
	rows, err := r.q.Query(ctx, `SELECT merchant_id FROM seller_rules ORDER BY merchant_id`)
	if err != nil {
		return nil, err
	}
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		ids = append(ids, id)
	}
	rows.Close()
	var out []domain.SellerRules
	for _, id := range ids {
		s, err := r.GetSellerRules(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, *s)
	}
	return out, nil
}

func (r *Repo) UpsertSellerRules(ctx context.Context, s domain.SellerRules) error {
	_, err := r.q.Exec(ctx, `INSERT INTO seller_rules (merchant_id, max_attempts, auto_rto_attempt, cod_limit, allowed_channels, comm_hours_start, comm_hours_end, enforce_comm_hours,
	  prepaid_conversion_allowed, allow_address_changes, early_rto_policy, allowed_actions, default_on_silence, buyer_response_timeout_minutes, seller_response_timeout_minutes)
	  VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
	  ON CONFLICT (merchant_id) DO UPDATE SET max_attempts=$2, auto_rto_attempt=$3, cod_limit=$4, allowed_channels=$5, comm_hours_start=$6, comm_hours_end=$7, enforce_comm_hours=$8,
	  prepaid_conversion_allowed=$9, allow_address_changes=$10, early_rto_policy=$11, allowed_actions=$12, default_on_silence=$13, buyer_response_timeout_minutes=$14, seller_response_timeout_minutes=$15, updated_at=now()`,
		s.MerchantID, s.MaxAttempts, s.AutoRTOAttempt, s.CODLimit, s.AllowedChannels, s.CommHoursStart, s.CommHoursEnd, s.EnforceCommHours, s.PrepaidConversionAllowed,
		s.AllowAddressChanges, s.EarlyRTOPolicy, s.AllowedActions, s.DefaultOnSilence, s.BuyerResponseTimeoutMinutes, s.SellerResponseTimeoutMinutes)
	return err
}

func (r *Repo) GetCarrierRules(ctx context.Context, code string) (*domain.CarrierRules, error) {
	var c domain.CarrierRules
	err := r.q.QueryRow(ctx, `SELECT carrier_code, max_attempts, instruction_cutoff, hold_window_days, supported_actions, supports_time_slot, can_change_payment_mode, can_change_address, can_change_phone, updated_at
	  FROM carrier_rules WHERE carrier_code=$1`, code).Scan(&c.CarrierCode, &c.MaxAttempts, &c.InstructionCutoff, &c.HoldWindowDays, &c.SupportedActions, &c.SupportsTimeSlot, &c.CanChangePaymentMode, &c.CanChangeAddress, &c.CanChangePhone, &c.UpdatedAt)
	return &c, notFound(err)
}

func (r *Repo) ListCarrierRules(ctx context.Context) ([]domain.CarrierRules, error) {
	rows, err := r.q.Query(ctx, `SELECT carrier_code, max_attempts, instruction_cutoff, hold_window_days, supported_actions, supports_time_slot, can_change_payment_mode, can_change_address, can_change_phone, updated_at FROM carrier_rules ORDER BY carrier_code`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []domain.CarrierRules
	for rows.Next() {
		var c domain.CarrierRules
		if err := rows.Scan(&c.CarrierCode, &c.MaxAttempts, &c.InstructionCutoff, &c.HoldWindowDays, &c.SupportedActions, &c.SupportsTimeSlot, &c.CanChangePaymentMode, &c.CanChangeAddress, &c.CanChangePhone, &c.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func (r *Repo) UpsertCarrierRules(ctx context.Context, c domain.CarrierRules) error {
	_, err := r.q.Exec(ctx, `INSERT INTO carrier_rules (carrier_code, max_attempts, instruction_cutoff, hold_window_days, supported_actions, supports_time_slot, can_change_payment_mode, can_change_address, can_change_phone)
	  VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
	  ON CONFLICT (carrier_code) DO UPDATE SET max_attempts=$2, instruction_cutoff=$3, hold_window_days=$4, supported_actions=$5, supports_time_slot=$6, can_change_payment_mode=$7, can_change_address=$8, can_change_phone=$9, updated_at=now()`,
		c.CarrierCode, c.MaxAttempts, c.InstructionCutoff, c.HoldWindowDays, c.SupportedActions, c.SupportsTimeSlot, c.CanChangePaymentMode, c.CanChangeAddress, c.CanChangePhone)
	return err
}

// ---- buyer profiles ----

type BuyerProfile struct {
	Phone             string `json:"phone"`
	PreferredLanguage string `json:"preferredLanguage"`
	AlternatePhone    string `json:"alternatePhone"`
}

func (r *Repo) GetBuyerProfile(ctx context.Context, phone string) (*BuyerProfile, error) {
	var b BuyerProfile
	err := r.q.QueryRow(ctx, `SELECT phone, COALESCE(preferred_language,''), COALESCE(alternate_phone,'') FROM buyer_profiles WHERE phone=$1`, phone).Scan(&b.Phone, &b.PreferredLanguage, &b.AlternatePhone)
	return &b, notFound(err)
}

func (r *Repo) UpsertBuyerLanguage(ctx context.Context, phone, name, lang string) error {
	_, err := r.q.Exec(ctx, `INSERT INTO buyer_profiles (phone, name, preferred_language) VALUES ($1,$2,$3)
	  ON CONFLICT (phone) DO UPDATE SET preferred_language=$3, updated_at=now()`, phone, name, lang)
	return err
}

func (r *Repo) SetBuyerAlternatePhone(ctx context.Context, phone, alt string) error {
	_, err := r.q.Exec(ctx, `INSERT INTO buyer_profiles (phone, alternate_phone) VALUES ($1,$2) ON CONFLICT (phone) DO UPDATE SET alternate_phone=$2, updated_at=now()`, phone, alt)
	return err
}

// ---- audit ----

type AuditEntry struct {
	Actor, ActorType, Action                  string
	OrderID, ShipmentID, NDRCaseID            string
	PreviousState, NewState                   string
	Evidence, RequestPayload, ResponsePayload any
	RequestID                                 string
}

type AuditRecord struct {
	ID              int64           `json:"id"`
	Actor           string          `json:"actor"`
	ActorType       string          `json:"actorType"`
	Action          string          `json:"action"`
	OrderID         string          `json:"orderId,omitempty"`
	ShipmentID      string          `json:"shipmentId,omitempty"`
	NDRCaseID       string          `json:"ndrCaseId,omitempty"`
	CaseNumber      string          `json:"caseNumber,omitempty"`
	PreviousState   string          `json:"previousState,omitempty"`
	NewState        string          `json:"newState,omitempty"`
	Evidence        json.RawMessage `json:"evidence,omitempty"`
	RequestPayload  json.RawMessage `json:"requestPayload,omitempty"`
	ResponsePayload json.RawMessage `json:"responsePayload,omitempty"`
	RequestID       string          `json:"requestId,omitempty"`
	CreatedAt       time.Time       `json:"createdAt"`
}

func toJSON(v any) any {
	if v == nil {
		return nil
	}
	switch t := v.(type) {
	case []byte:
		if len(t) == 0 {
			return nil
		}
		return t
	case json.RawMessage:
		if len(t) == 0 {
			return nil
		}
		return []byte(t)
	}
	b, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	return b
}

func (r *Repo) InsertAudit(ctx context.Context, a AuditEntry) error {
	_, err := r.q.Exec(ctx, `INSERT INTO audit_logs (actor, actor_type, action, order_id, shipment_id, ndr_case_id, evidence, previous_state, new_state, request_payload, response_payload, request_id)
	  VALUES ($1,$2,$3,NULLIF($4,'')::uuid,NULLIF($5,'')::uuid,NULLIF($6,'')::uuid,$7,NULLIF($8,''),NULLIF($9,''),$10,$11,NULLIF($12,''))`,
		a.Actor, a.ActorType, a.Action, a.OrderID, a.ShipmentID, a.NDRCaseID, toJSON(a.Evidence), a.PreviousState, a.NewState, toJSON(a.RequestPayload), toJSON(a.ResponsePayload), a.RequestID)
	return err
}

type AuditFilter struct {
	OrderID, CaseID, ActorType, Action string
	Limit                              int
}

func (r *Repo) ListAudit(ctx context.Context, f AuditFilter) ([]AuditRecord, error) {
	if f.Limit <= 0 || f.Limit > 1000 {
		f.Limit = 200
	}
	rows, err := r.q.Query(ctx, `SELECT a.id, a.actor, a.actor_type, a.action, COALESCE(a.order_id::text,''), COALESCE(a.shipment_id::text,''), COALESCE(a.ndr_case_id::text,''), COALESCE(c.case_number,''),
	  COALESCE(a.previous_state,''), COALESCE(a.new_state,''), a.evidence, a.request_payload, a.response_payload, COALESCE(a.request_id,''), a.created_at
	  FROM audit_logs a LEFT JOIN ndr_cases c ON c.id=a.ndr_case_id
	  WHERE ($1='' OR a.order_id=NULLIF($1,'')::uuid) AND ($2='' OR a.ndr_case_id=NULLIF($2,'')::uuid) AND ($3='' OR a.actor_type=$3) AND ($4='' OR a.action=$4)
	  ORDER BY a.created_at DESC, a.id DESC LIMIT $5`, f.OrderID, f.CaseID, f.ActorType, f.Action, f.Limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AuditRecord
	for rows.Next() {
		var a AuditRecord
		if err := rows.Scan(&a.ID, &a.Actor, &a.ActorType, &a.Action, &a.OrderID, &a.ShipmentID, &a.NDRCaseID, &a.CaseNumber, &a.PreviousState, &a.NewState, &a.Evidence, &a.RequestPayload, &a.ResponsePayload, &a.RequestID, &a.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
