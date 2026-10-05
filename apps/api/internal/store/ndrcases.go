package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

type NDRCase struct {
	ID                 string           `json:"id"`
	CaseNumber         string           `json:"caseNumber"`
	ShipmentID         string           `json:"shipmentId"`
	OrderID            string           `json:"orderUuid"`
	ZippyOrderID       string           `json:"orderId"`
	MerchantID         string           `json:"merchantId"`
	TrackingNumber     string           `json:"trackingNumber"`
	ShipmentEventID    string           `json:"shipmentEventId"`
	AttemptNumber      int              `json:"attemptNumber"`
	CarrierCode        string           `json:"carrierCode"`
	CarrierReasonCode  string           `json:"carrierReasonCode"`
	CarrierRemark      string           `json:"carrierRemark"`
	NormalizedReason   domain.NDRReason `json:"normalizedReason"`
	ReasonSource       string           `json:"reasonSource"`
	Language           string           `json:"language"`
	LanguageSource     string           `json:"languageSource"`
	BuyerIntent        json.RawMessage  `json:"buyerIntent"`
	RecommendedAction  string           `json:"recommendedAction"`
	ActualAction       string           `json:"actualAction"`
	State              domain.CaseState `json:"state"`
	Outcome            string           `json:"outcome"`
	Pending            json.RawMessage  `json:"pending"`
	Plan               json.RawMessage  `json:"plan"`
	ContactAttempts    int              `json:"contactAttempts"`
	ContactExhausted   bool             `json:"contactExhausted"`
	SellerRules        json.RawMessage  `json:"sellerRules"`
	CarrierConstraints json.RawMessage  `json:"carrierConstraints"`
	LastContactedAt    *time.Time       `json:"lastContactedAt"`
	OpenedAt           time.Time        `json:"openedAt"`
	UpdatedAt          time.Time        `json:"updatedAt"`
	ClosedAt           *time.Time       `json:"closedAt"`
	// joined for list/detail convenience
	CustomerName  string `json:"customerName"`
	CustomerPhone string `json:"-"`
}

const caseCols = `c.id::text, c.case_number, c.shipment_id::text, c.order_id::text, o.zippy_order_id, o.merchant_id, s.tracking_number, c.shipment_event_id::text, c.attempt_number, c.carrier_code,
 COALESCE(c.carrier_reason_code,''), COALESCE(c.carrier_remark,''), c.normalized_reason, c.reason_source, c.language, c.language_source, c.buyer_intent,
 COALESCE(c.recommended_action,''), COALESCE(c.actual_action,''), c.state, COALESCE(c.outcome,''), c.pending, c.plan, c.contact_attempts, c.contact_exhausted,
 c.seller_rules_snapshot, c.carrier_constraints_snapshot, c.last_contacted_at, c.opened_at, c.updated_at, c.closed_at, o.customer_name, o.customer_phone`

const caseFrom = ` FROM ndr_cases c JOIN orders o ON o.id=c.order_id JOIN shipments s ON s.id=c.shipment_id `

func scanCase(r scanner) (*NDRCase, error) {
	var c NDRCase
	var reason, state string
	err := r.Scan(&c.ID, &c.CaseNumber, &c.ShipmentID, &c.OrderID, &c.ZippyOrderID, &c.MerchantID, &c.TrackingNumber, &c.ShipmentEventID, &c.AttemptNumber, &c.CarrierCode,
		&c.CarrierReasonCode, &c.CarrierRemark, &reason, &c.ReasonSource, &c.Language, &c.LanguageSource, &c.BuyerIntent, &c.RecommendedAction, &c.ActualAction, &state, &c.Outcome,
		&c.Pending, &c.Plan, &c.ContactAttempts, &c.ContactExhausted, &c.SellerRules, &c.CarrierConstraints, &c.LastContactedAt, &c.OpenedAt, &c.UpdatedAt, &c.ClosedAt, &c.CustomerName, &c.CustomerPhone)
	c.NormalizedReason, c.State = domain.NDRReason(reason), domain.CaseState(state)
	return &c, err
}

type NewCase struct {
	ShipmentID, OrderID, ShipmentEventID, CarrierCode, CarrierReasonCode, CarrierRemark string
	AttemptNumber                                                                       int
	Reason                                                                              domain.NDRReason
	ReasonSource, Language, LanguageSource, RecommendedAction                           string
	SellerRules, CarrierConstraints                                                     any
	State                                                                               domain.CaseState
}

func (r *Repo) InsertCase(ctx context.Context, n NewCase) (*NDRCase, error) {
	var id string
	err := r.q.QueryRow(ctx, `INSERT INTO ndr_cases (case_number, shipment_id, order_id, shipment_event_id, attempt_number, carrier_code, carrier_reason_code, carrier_remark, normalized_reason, reason_source,
	  language, language_source, recommended_action, state, seller_rules_snapshot, carrier_constraints_snapshot)
	  VALUES ('NDR-'||nextval('ndr_case_seq'), $1::uuid,$2::uuid,$3::uuid,$4,$5,NULLIF($6,''),NULLIF($7,''),$8,$9,$10,$11,$12,$13,$14,$15) RETURNING id::text`,
		n.ShipmentID, n.OrderID, n.ShipmentEventID, n.AttemptNumber, n.CarrierCode, n.CarrierReasonCode, n.CarrierRemark, string(n.Reason), n.ReasonSource,
		n.Language, n.LanguageSource, n.RecommendedAction, string(n.State), toJSON(n.SellerRules), toJSON(n.CarrierConstraints)).Scan(&id)
	if err != nil {
		return nil, err
	}
	return r.GetCase(ctx, id, false)
}

func (r *Repo) GetCase(ctx context.Context, id string, forUpdate bool) (*NDRCase, error) {
	q := `SELECT ` + caseCols + caseFrom + `WHERE c.id=$1::uuid`
	if forUpdate {
		q += ` FOR UPDATE OF c`
	}
	c, err := scanCase(r.q.QueryRow(ctx, q, id))
	return c, notFound(err)
}

func (r *Repo) GetCaseByNumber(ctx context.Context, num string) (*NDRCase, error) {
	c, err := scanCase(r.q.QueryRow(ctx, `SELECT `+caseCols+caseFrom+`WHERE c.case_number=$1`, num))
	return c, notFound(err)
}

func (r *Repo) ActiveCaseForShipment(ctx context.Context, shipmentID string) (*NDRCase, error) {
	c, err := scanCase(r.q.QueryRow(ctx, `SELECT `+caseCols+caseFrom+`WHERE c.shipment_id=$1::uuid AND c.state<>'CLOSED'`, shipmentID))
	return c, notFound(err)
}

func (r *Repo) CountCasesForShipment(ctx context.Context, shipmentID string) (int, error) {
	var n int
	err := r.q.QueryRow(ctx, `SELECT count(*) FROM ndr_cases WHERE shipment_id=$1::uuid`, shipmentID).Scan(&n)
	return n, err
}

type CaseFilter struct {
	State, Reason, Carrier, OrderID string
	OpenOnly                        bool
	Limit                           int
}

func (r *Repo) ListCases(ctx context.Context, f CaseFilter) ([]NDRCase, error) {
	if f.Limit <= 0 || f.Limit > 500 {
		f.Limit = 200
	}
	rows, err := r.q.Query(ctx, `SELECT `+caseCols+caseFrom+`WHERE ($1='' OR c.state=$1) AND ($2='' OR c.normalized_reason=$2) AND ($3='' OR c.carrier_code=$3)
	  AND ($4='' OR o.zippy_order_id=$4) AND (NOT $5 OR c.state<>'CLOSED') ORDER BY c.opened_at DESC LIMIT $6`, f.State, f.Reason, f.Carrier, f.OrderID, f.OpenOnly, f.Limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []NDRCase{}
	for rows.Next() {
		c, err := scanCase(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *c)
	}
	return out, rows.Err()
}

// SaveCase persists every mutable field of the case.
func (r *Repo) SaveCase(ctx context.Context, c *NDRCase) error {
	var closed any
	if c.State == domain.CaseClosed {
		closed = time.Now()
		if c.ClosedAt != nil {
			closed = *c.ClosedAt
		}
	}
	_, err := r.q.Exec(ctx, `UPDATE ndr_cases SET normalized_reason=$2, reason_source=$3, language=$4, language_source=$5, buyer_intent=$6, recommended_action=NULLIF($7,''), actual_action=NULLIF($8,''),
	  state=$9, outcome=NULLIF($10,''), pending=$11, plan=$12, contact_attempts=$13, contact_exhausted=$14, last_contacted_at=$15, closed_at=$16, updated_at=now() WHERE id=$1::uuid`,
		c.ID, string(c.NormalizedReason), c.ReasonSource, c.Language, c.LanguageSource, toJSON(c.BuyerIntent), c.RecommendedAction, c.ActualAction,
		string(c.State), c.Outcome, toJSON(c.Pending), toJSON(c.Plan), c.ContactAttempts, c.ContactExhausted, c.LastContactedAt, closed)
	return err
}

// ---- case events (timeline) ----

type NDREvent struct {
	ID          string          `json:"id"`
	CaseID      string          `json:"caseId"`
	EventType   string          `json:"eventType"`
	Actor       string          `json:"actor"`
	ActorType   string          `json:"actorType"`
	Description string          `json:"description"`
	Data        json.RawMessage `json:"data,omitempty"`
	CreatedAt   time.Time       `json:"createdAt"`
}

func (r *Repo) InsertNDREvent(ctx context.Context, caseID, eventType, actor, actorType, desc string, data any) error {
	_, err := r.q.Exec(ctx, `INSERT INTO ndr_events (ndr_case_id, event_type, actor, actor_type, description, data) VALUES ($1::uuid,$2,$3,$4,$5,$6)`,
		caseID, eventType, actor, actorType, desc, toJSON(data))
	return err
}

func (r *Repo) ListNDREvents(ctx context.Context, caseID string) ([]NDREvent, error) {
	rows, err := r.q.Query(ctx, `SELECT id::text, ndr_case_id::text, event_type, actor, actor_type, description, data, created_at FROM ndr_events WHERE ndr_case_id=$1::uuid ORDER BY created_at, id`, caseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []NDREvent{}
	for rows.Next() {
		var e NDREvent
		if err := rows.Scan(&e.ID, &e.CaseID, &e.EventType, &e.Actor, &e.ActorType, &e.Description, &e.Data, &e.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// ---- messages ----

type Message struct {
	ID             string          `json:"id"`
	CaseID         string          `json:"caseId"`
	Direction      string          `json:"direction"`
	SenderType     string          `json:"senderType"`
	Channel        string          `json:"channel"`
	Language       string          `json:"language"`
	OriginalText   string          `json:"originalText"`
	InternalText   string          `json:"internalText,omitempty"`
	Interpretation json.RawMessage `json:"interpretation,omitempty"`
	DeliveryStatus string          `json:"deliveryStatus"`
	Processed      bool            `json:"processed"`
	CreatedAt      time.Time       `json:"createdAt"`
}

func (r *Repo) InsertMessage(ctx context.Context, m Message) (string, error) {
	var id string
	err := r.q.QueryRow(ctx, `INSERT INTO conversation_messages (ndr_case_id, direction, sender_type, channel, language, original_text, internal_text, interpretation, delivery_status, processed)
	  VALUES ($1::uuid,$2,$3,$4,$5,$6,NULLIF($7,''),$8,$9,$10) RETURNING id::text`,
		m.CaseID, m.Direction, m.SenderType, m.Channel, m.Language, m.OriginalText, m.InternalText, toJSON(m.Interpretation), m.DeliveryStatus, m.Processed).Scan(&id)
	return id, err
}

func (r *Repo) ListMessages(ctx context.Context, caseID string) ([]Message, error) {
	rows, err := r.q.Query(ctx, `SELECT id::text, ndr_case_id::text, direction, sender_type, channel, language, original_text, COALESCE(internal_text,''), interpretation, delivery_status, processed, created_at
	  FROM conversation_messages WHERE ndr_case_id=$1::uuid ORDER BY created_at, id`, caseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Message{}
	for rows.Next() {
		var m Message
		if err := rows.Scan(&m.ID, &m.CaseID, &m.Direction, &m.SenderType, &m.Channel, &m.Language, &m.OriginalText, &m.InternalText, &m.Interpretation, &m.DeliveryStatus, &m.Processed, &m.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func (r *Repo) UpdateMessageProcessed(ctx context.Context, id string, interpretation any, internalText string) error {
	_, err := r.q.Exec(ctx, `UPDATE conversation_messages SET processed=TRUE, interpretation=$2, internal_text=NULLIF($3,'') WHERE id=$1::uuid`, id, toJSON(interpretation), internalText)
	return err
}

// ---- communication attempts ----

type CommAttempt struct {
	ID          string    `json:"id"`
	CaseID      string    `json:"caseId"`
	Channel     string    `json:"channel"`
	Status      string    `json:"status"`
	Error       string    `json:"error,omitempty"`
	ProviderRef string    `json:"providerRef,omitempty"`
	CreatedAt   time.Time `json:"createdAt"`
}

func (r *Repo) InsertCommAttempt(ctx context.Context, caseID, channel, status, errMsg, ref string) error {
	_, err := r.q.Exec(ctx, `INSERT INTO communication_attempts (ndr_case_id, channel, status, error, provider_ref) VALUES ($1::uuid,$2,$3,NULLIF($4,''),NULLIF($5,''))`, caseID, channel, status, errMsg, ref)
	return err
}

func (r *Repo) ListCommAttempts(ctx context.Context, caseID string) ([]CommAttempt, error) {
	rows, err := r.q.Query(ctx, `SELECT id::text, ndr_case_id::text, channel, status, COALESCE(error,''), COALESCE(provider_ref,''), created_at FROM communication_attempts WHERE ndr_case_id=$1::uuid ORDER BY created_at, id`, caseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []CommAttempt{}
	for rows.Next() {
		var a CommAttempt
		if err := rows.Scan(&a.ID, &a.CaseID, &a.Channel, &a.Status, &a.Error, &a.ProviderRef, &a.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// ---- carrier actions ----

type CarrierAction struct {
	ID               string          `json:"id"`
	CaseID           string          `json:"caseId"`
	ShipmentID       string          `json:"shipmentId"`
	CarrierCode      string          `json:"carrierCode"`
	ActionType       string          `json:"actionType"`
	Payload          json.RawMessage `json:"payload"`
	IdempotencyKey   string          `json:"idempotencyKey"`
	Status           string          `json:"status"`
	RequestPayload   json.RawMessage `json:"requestPayload,omitempty"`
	ResponsePayload  json.RawMessage `json:"responsePayload,omitempty"`
	CarrierReference string          `json:"carrierReference,omitempty"`
	Reason           string          `json:"reason,omitempty"`
	CreatedAt        time.Time       `json:"createdAt"`
	SubmittedAt      *time.Time      `json:"submittedAt,omitempty"`
	RespondedAt      *time.Time      `json:"respondedAt,omitempty"`
}

const actionCols = `id::text, ndr_case_id::text, shipment_id::text, carrier_code, action_type, payload, idempotency_key, status, request_payload, response_payload, COALESCE(carrier_reference,''), COALESCE(reason,''), created_at, submitted_at, responded_at`

func scanAction(r scanner) (*CarrierAction, error) {
	var a CarrierAction
	err := r.Scan(&a.ID, &a.CaseID, &a.ShipmentID, &a.CarrierCode, &a.ActionType, &a.Payload, &a.IdempotencyKey, &a.Status, &a.RequestPayload, &a.ResponsePayload, &a.CarrierReference, &a.Reason, &a.CreatedAt, &a.SubmittedAt, &a.RespondedAt)
	return &a, err
}

// GetOrCreateAction is idempotent on the key: a retry of the same logical action returns the same row.
func (r *Repo) GetOrCreateAction(ctx context.Context, caseID, shipmentID, carrier string, action domain.PlannedAction, key string) (*CarrierAction, bool, error) {
	_, err := r.q.Exec(ctx, `INSERT INTO carrier_actions (ndr_case_id, shipment_id, carrier_code, action_type, payload, idempotency_key, status)
	  VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,'PENDING') ON CONFLICT (idempotency_key) DO NOTHING`, caseID, shipmentID, carrier, string(action.Type), toJSON(action), key)
	if err != nil {
		return nil, false, err
	}
	a, err := scanAction(r.q.QueryRow(ctx, `SELECT `+actionCols+` FROM carrier_actions WHERE idempotency_key=$1`, key))
	return a, a.Status == "PENDING", err
}

func (r *Repo) FinishAction(ctx context.Context, id, status string, req, resp []byte, ref, reason string) error {
	_, err := r.q.Exec(ctx, `UPDATE carrier_actions SET status=$2, request_payload=$3, response_payload=$4, carrier_reference=NULLIF($5,''), reason=NULLIF($6,''),
	  submitted_at=COALESCE(submitted_at, now()), responded_at=now() WHERE id=$1::uuid`, id, status, jsonOrNil(req), jsonOrNil(resp), ref, reason)
	return err
}

func (r *Repo) ListActions(ctx context.Context, caseID string) ([]CarrierAction, error) {
	rows, err := r.q.Query(ctx, `SELECT `+actionCols+` FROM carrier_actions WHERE ndr_case_id=$1::uuid ORDER BY created_at, id`, caseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []CarrierAction{}
	for rows.Next() {
		a, err := scanAction(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *a)
	}
	return out, rows.Err()
}

// ---- approvals ----

type Approval struct {
	ID             string          `json:"id"`
	CaseID         string          `json:"caseId"`
	CaseNumber     string          `json:"caseNumber"`
	OrderID        string          `json:"orderId"`
	TrackingNumber string          `json:"trackingNumber"`
	CarrierCode    string          `json:"carrierCode"`
	Kind           string          `json:"kind"`
	ProposedAction json.RawMessage `json:"proposedAction"`
	BuyerRequest   string          `json:"buyerRequest"`
	Reason         string          `json:"reason"`
	Evidence       json.RawMessage `json:"evidence"`
	RequiredRoles  []string        `json:"requiredRoles"`
	GrantedRoles   []string        `json:"grantedRoles"`
	Blocking       bool            `json:"blocking"`
	Status         string          `json:"status"`
	DecidedBy      string          `json:"decidedBy,omitempty"`
	DecisionNote   string          `json:"decisionNote,omitempty"`
	CreatedAt      time.Time       `json:"createdAt"`
	DecidedAt      *time.Time      `json:"decidedAt,omitempty"`
}

const approvalCols = `a.id::text, a.ndr_case_id::text, c.case_number, o.zippy_order_id, s.tracking_number, c.carrier_code, a.kind, a.proposed_action, COALESCE(a.buyer_request,''), a.reason, a.evidence,
 a.required_roles, a.granted_roles, a.blocking, a.status, COALESCE(a.decided_by,''), COALESCE(a.decision_note,''), a.created_at, a.decided_at`
const approvalFrom = ` FROM approvals a JOIN ndr_cases c ON c.id=a.ndr_case_id JOIN orders o ON o.id=a.order_id JOIN shipments s ON s.id=a.shipment_id `

func scanApproval(r scanner) (*Approval, error) {
	var a Approval
	err := r.Scan(&a.ID, &a.CaseID, &a.CaseNumber, &a.OrderID, &a.TrackingNumber, &a.CarrierCode, &a.Kind, &a.ProposedAction, &a.BuyerRequest, &a.Reason, &a.Evidence, &a.RequiredRoles, &a.GrantedRoles, &a.Blocking, &a.Status, &a.DecidedBy, &a.DecisionNote, &a.CreatedAt, &a.DecidedAt)
	return &a, err
}

type NewApproval struct {
	CaseID, OrderID, ShipmentID, Kind, BuyerRequest, Reason string
	Proposed, Evidence                                      any
	RequiredRoles, GrantedRoles                             []string
	Blocking                                                bool
}

func (r *Repo) InsertApproval(ctx context.Context, n NewApproval) (*Approval, error) {
	if n.GrantedRoles == nil {
		n.GrantedRoles = []string{}
	}
	var id string
	err := r.q.QueryRow(ctx, `INSERT INTO approvals (ndr_case_id, order_id, shipment_id, kind, proposed_action, buyer_request, reason, evidence, required_roles, granted_roles, blocking)
	  VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5,NULLIF($6,''),$7,$8,$9,$10,$11) RETURNING id::text`,
		n.CaseID, n.OrderID, n.ShipmentID, n.Kind, toJSON(n.Proposed), n.BuyerRequest, n.Reason, toJSON(n.Evidence), n.RequiredRoles, n.GrantedRoles, n.Blocking).Scan(&id)
	if err != nil {
		return nil, err
	}
	return r.GetApproval(ctx, id, false)
}

func (r *Repo) GetApproval(ctx context.Context, id string, forUpdate bool) (*Approval, error) {
	q := `SELECT ` + approvalCols + approvalFrom + `WHERE a.id=$1::uuid`
	if forUpdate {
		q += ` FOR UPDATE OF a`
	}
	a, err := scanApproval(r.q.QueryRow(ctx, q, id))
	return a, notFound(err)
}

func (r *Repo) ListApprovals(ctx context.Context, status, caseID string, limit int) ([]Approval, error) {
	if limit <= 0 || limit > 500 {
		limit = 200
	}
	rows, err := r.q.Query(ctx, `SELECT `+approvalCols+approvalFrom+`WHERE ($1='' OR a.status=$1) AND ($2='' OR a.ndr_case_id=NULLIF($2,'')::uuid) ORDER BY a.created_at DESC LIMIT $3`, status, caseID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Approval{}
	for rows.Next() {
		a, err := scanApproval(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *a)
	}
	return out, rows.Err()
}

func (r *Repo) UpdateApproval(ctx context.Context, a *Approval) error {
	_, err := r.q.Exec(ctx, `UPDATE approvals SET granted_roles=$2, status=$3, decided_by=NULLIF($4,''), decision_note=NULLIF($5,''), decided_at=$6 WHERE id=$1::uuid`,
		a.ID, a.GrantedRoles, a.Status, a.DecidedBy, a.DecisionNote, a.DecidedAt)
	return err
}

// ---- dashboard aggregates ----

type Dashboard struct {
	Orders           int          `json:"orders"`
	Shipments        int          `json:"shipments"`
	Delivered        int          `json:"delivered"`
	InTransit        int          `json:"inTransit"`
	NDR              int          `json:"ndr"`
	RTO              int          `json:"rto"`
	OpenNDRCases     int          `json:"openNdrCases"`
	OpenApprovals    int          `json:"openApprovals"`
	TotalNDRCases    int          `json:"totalNdrCases"`
	RecoveredCases   int          `json:"recoveredCases"`
	RecoveryRate     float64      `json:"recoveryRate"`
	NDRByReason      []Bucket     `json:"ndrByReason"`
	NDRByCarrier     []Bucket     `json:"ndrByCarrier"`
	NDRRecovery      []Bucket     `json:"ndrRecovery"`
	RTOTrend         []TrendPoint `json:"rtoTrend"`
	LanguageResponse []LangRate   `json:"languageResponse"`
}

type Bucket struct {
	Key   string `json:"key"`
	Count int    `json:"count"`
}
type TrendPoint struct {
	Day string `json:"day"`
	RTO int    `json:"rto"`
	NDR int    `json:"ndr"`
}
type LangRate struct {
	Language  string  `json:"language"`
	Contacted int     `json:"contacted"`
	Responded int     `json:"responded"`
	Rate      float64 `json:"rate"`
}

func (r *Repo) Dashboard(ctx context.Context) (*Dashboard, error) {
	d := &Dashboard{NDRByReason: []Bucket{}, NDRByCarrier: []Bucket{}, NDRRecovery: []Bucket{}, RTOTrend: []TrendPoint{}, LanguageResponse: []LangRate{}}
	err := r.q.QueryRow(ctx, `SELECT
	  (SELECT count(*) FROM orders), (SELECT count(*) FROM shipments),
	  (SELECT count(*) FROM shipments WHERE current_status='DELIVERED'),
	  (SELECT count(*) FROM shipments WHERE current_status IN ('PICKED_UP','IN_TRANSIT','OUT_FOR_DELIVERY','SHIPMENT_CREATED')),
	  (SELECT count(*) FROM shipments WHERE current_status='DELIVERY_FAILED'),
	  (SELECT count(*) FROM shipments WHERE current_status='RTO'),
	  (SELECT count(*) FROM ndr_cases WHERE state<>'CLOSED'),
	  (SELECT count(*) FROM approvals WHERE status='PENDING' AND blocking),
	  (SELECT count(*) FROM ndr_cases),
	  (SELECT count(*) FROM ndr_cases WHERE outcome='DELIVERED')`).
		Scan(&d.Orders, &d.Shipments, &d.Delivered, &d.InTransit, &d.NDR, &d.RTO, &d.OpenNDRCases, &d.OpenApprovals, &d.TotalNDRCases, &d.RecoveredCases)
	if err != nil {
		return nil, err
	}
	closedTotal := 0
	_ = r.q.QueryRow(ctx, `SELECT count(*) FROM ndr_cases WHERE state='CLOSED'`).Scan(&closedTotal)
	if closedTotal > 0 {
		d.RecoveryRate = float64(d.RecoveredCases) / float64(closedTotal)
	}
	bucket := func(q string) []Bucket {
		rows, err := r.q.Query(ctx, q)
		if err != nil {
			return []Bucket{}
		}
		defer rows.Close()
		out := []Bucket{}
		for rows.Next() {
			var b Bucket
			if rows.Scan(&b.Key, &b.Count) == nil {
				out = append(out, b)
			}
		}
		return out
	}
	d.NDRByReason = bucket(`SELECT normalized_reason, count(*)::int FROM ndr_cases GROUP BY 1 ORDER BY 2 DESC`)
	d.NDRByCarrier = bucket(`SELECT carrier_code, count(*)::int FROM ndr_cases GROUP BY 1 ORDER BY 2 DESC`)
	d.NDRRecovery = bucket(`SELECT COALESCE(NULLIF(outcome,''),'IN_PROGRESS'), count(*)::int FROM ndr_cases GROUP BY 1 ORDER BY 2 DESC`)
	if rows, err := r.q.Query(ctx, `SELECT to_char(day,'YYYY-MM-DD'), COALESCE(rto,0), COALESCE(ndr,0) FROM (
	    SELECT generate_series(current_date-6, current_date, '1 day')::date AS day) d
	  LEFT JOIN (SELECT received_at::date AS ed, count(*) FILTER (WHERE normalized_status='RTO') AS rto, count(*) FILTER (WHERE normalized_status='DELIVERY_FAILED') AS ndr
	    FROM shipment_events WHERE disposition='APPLIED' GROUP BY 1) e ON e.ed=d.day ORDER BY day`); err == nil {
		for rows.Next() {
			var t TrendPoint
			if rows.Scan(&t.Day, &t.RTO, &t.NDR) == nil {
				d.RTOTrend = append(d.RTOTrend, t)
			}
		}
		rows.Close()
	}
	if rows, err := r.q.Query(ctx, `SELECT c.language, count(*)::int, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM conversation_messages m WHERE m.ndr_case_id=c.id AND m.direction='INBOUND'))::int
	    FROM ndr_cases c WHERE c.contact_attempts>0 GROUP BY 1 ORDER BY 2 DESC`); err == nil {
		for rows.Next() {
			var l LangRate
			if rows.Scan(&l.Language, &l.Contacted, &l.Responded) == nil {
				if l.Contacted > 0 {
					l.Rate = float64(l.Responded) / float64(l.Contacted)
				}
				d.LanguageResponse = append(d.LanguageResponse, l)
			}
		}
		rows.Close()
	}
	return d, nil
}
