package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

type Shipment struct {
	ID                string                `json:"id"`
	OrderID           string                `json:"orderId"` // internal uuid
	ZippyOrderID      string                `json:"zippyOrderId,omitempty"`
	CarrierCode       string                `json:"carrierCode"`
	CarrierShipmentID string                `json:"carrierShipmentId"`
	TrackingNumber    string                `json:"trackingNumber"`
	ServiceCode       string                `json:"serviceCode"`
	QuotedAmount      float64               `json:"quotedAmount"`
	CurrentStatus     domain.ShipmentStatus `json:"currentStatus"`
	LabelURL          string                `json:"labelUrl,omitempty"`
	CreatedAt         time.Time             `json:"createdAt"`
	UpdatedAt         time.Time             `json:"updatedAt"`
}

const shipCols = `s.id::text, s.order_id::text, o.zippy_order_id, s.carrier_code, s.carrier_shipment_id, s.tracking_number, s.selected_service_code,
 s.quoted_amount::float8, s.current_status, COALESCE(s.label_url,''), s.created_at, s.updated_at`

func scanShipment(r scanner) (*Shipment, error) {
	var s Shipment
	var st string
	err := r.Scan(&s.ID, &s.OrderID, &s.ZippyOrderID, &s.CarrierCode, &s.CarrierShipmentID, &s.TrackingNumber, &s.ServiceCode, &s.QuotedAmount, &st, &s.LabelURL, &s.CreatedAt, &s.UpdatedAt)
	s.CurrentStatus = domain.ShipmentStatus(st)
	return &s, err
}

const shipFrom = ` FROM shipments s JOIN orders o ON o.id=s.order_id `

func (r *Repo) GetShipmentByOrder(ctx context.Context, orderID string) (*Shipment, error) {
	s, err := scanShipment(r.q.QueryRow(ctx, `SELECT `+shipCols+shipFrom+`WHERE s.order_id=$1::uuid`, orderID))
	return s, notFound(err)
}

func (r *Repo) GetShipment(ctx context.Context, id string) (*Shipment, error) {
	s, err := scanShipment(r.q.QueryRow(ctx, `SELECT `+shipCols+shipFrom+`WHERE s.id=$1::uuid`, id))
	return s, notFound(err)
}

// LockShipmentByTracking locks the shipment row so concurrent webhooks for one shipment serialise.
func (r *Repo) LockShipmentByTracking(ctx context.Context, carrierCode, tracking, carrierShipmentID string) (*Shipment, error) {
	s, err := scanShipment(r.q.QueryRow(ctx, `SELECT `+shipCols+shipFrom+`WHERE s.carrier_code=$1 AND (s.tracking_number=$2 OR ($2='' AND s.carrier_shipment_id=$3)) FOR UPDATE OF s`, carrierCode, tracking, carrierShipmentID))
	return s, notFound(err)
}

func (r *Repo) ListShipments(ctx context.Context, limit int) ([]Shipment, error) {
	rows, err := r.q.Query(ctx, `SELECT `+shipCols+shipFrom+`ORDER BY s.created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Shipment
	for rows.Next() {
		s, err := scanShipment(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *s)
	}
	return out, rows.Err()
}

func (r *Repo) InsertShipment(ctx context.Context, orderID, carrier, carrierShipmentID, tracking, service string, quoted float64, labelURL string, raw []byte) (*Shipment, error) {
	var id string
	err := r.q.QueryRow(ctx, `INSERT INTO shipments (order_id, carrier_code, carrier_shipment_id, tracking_number, selected_service_code, quoted_amount, current_status, label_url, carrier_response)
	  VALUES ($1::uuid,$2,$3,$4,$5,$6,'SHIPMENT_CREATED',NULLIF($7,''),$8) RETURNING id::text`,
		orderID, carrier, carrierShipmentID, tracking, service, quoted, labelURL, jsonOrNil(raw)).Scan(&id)
	if err != nil {
		return nil, err
	}
	return r.GetShipment(ctx, id)
}

func (r *Repo) SetShipmentStatus(ctx context.Context, shipmentID string, status domain.ShipmentStatus) error {
	_, err := r.q.Exec(ctx, `UPDATE shipments SET current_status=$2, updated_at=now() WHERE id=$1::uuid`, shipmentID, string(status))
	return err
}

// ---- events ----

type ShipmentEvent struct {
	ID               string                `json:"id"`
	ShipmentID       string                `json:"shipmentId"`
	IdempotencyKey   string                `json:"idempotencyKey"`
	CarrierCode      string                `json:"carrierCode"`
	CarrierStatus    string                `json:"carrierStatus"`
	NormalizedStatus domain.ShipmentStatus `json:"status"`
	Description      string                `json:"description"`
	Location         string                `json:"location"`
	EventTime        time.Time             `json:"eventTime"`
	NDRReasonCode    string                `json:"ndrReasonCode,omitempty"`
	NDRRemark        string                `json:"ndrRemark,omitempty"`
	Disposition      string                `json:"disposition"`
	ReceivedAt       time.Time             `json:"receivedAt"`
}

type NewShipmentEvent struct {
	ShipmentID, IdempotencyKey, CarrierCode, CarrierEventID, CarrierStatus string
	Status                                                                 domain.ShipmentStatus
	Description, Location                                                  string
	EventTime                                                              time.Time
	NDRReasonCode, NDRRemark                                               string
	Disposition                                                            string
	Raw                                                                    []byte
}

// InsertShipmentEvent returns (id, inserted). inserted=false means the idempotency key already existed.
func (r *Repo) InsertShipmentEvent(ctx context.Context, e NewShipmentEvent) (string, bool, error) {
	if e.Disposition == "" {
		e.Disposition = "APPLIED"
	}
	var id string
	err := r.q.QueryRow(ctx, `INSERT INTO shipment_events (shipment_id, idempotency_key, carrier_code, carrier_event_id, carrier_status, normalized_status, description, location,
	  event_time, ndr_reason_code, ndr_remark, disposition, raw_event_payload)
	  VALUES ($1::uuid,$2,$3,NULLIF($4,''),$5,$6,$7,$8,$9,NULLIF($10,''),NULLIF($11,''),$12,$13)
	  ON CONFLICT (idempotency_key) DO NOTHING RETURNING id::text`,
		e.ShipmentID, e.IdempotencyKey, e.CarrierCode, e.CarrierEventID, e.CarrierStatus, string(e.Status), e.Description, e.Location, e.EventTime, e.NDRReasonCode, e.NDRRemark, e.Disposition, jsonOrNil(e.Raw)).Scan(&id)
	if err != nil {
		if notFound(err) == ErrNotFound {
			return "", false, nil
		}
		return "", false, err
	}
	return id, true, nil
}

func (r *Repo) ListShipmentEvents(ctx context.Context, shipmentID string, includeRejected bool) ([]ShipmentEvent, error) {
	q := `SELECT id::text, shipment_id::text, idempotency_key, carrier_code, carrier_status, normalized_status, COALESCE(description,''), COALESCE(location,''), event_time,
	  COALESCE(ndr_reason_code,''), COALESCE(ndr_remark,''), disposition, received_at FROM shipment_events WHERE shipment_id=$1::uuid`
	if !includeRejected {
		q += ` AND disposition='APPLIED'`
	}
	q += ` ORDER BY received_at, event_time`
	rows, err := r.q.Query(ctx, q, shipmentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ShipmentEvent
	for rows.Next() {
		var e ShipmentEvent
		var st string
		if err := rows.Scan(&e.ID, &e.ShipmentID, &e.IdempotencyKey, &e.CarrierCode, &e.CarrierStatus, &st, &e.Description, &e.Location, &e.EventTime, &e.NDRReasonCode, &e.NDRRemark, &e.Disposition, &e.ReceivedAt); err != nil {
			return nil, err
		}
		e.NormalizedStatus = domain.ShipmentStatus(st)
		out = append(out, e)
	}
	return out, rows.Err()
}

func (r *Repo) GetShipmentEvent(ctx context.Context, id string) (*ShipmentEvent, error) {
	var e ShipmentEvent
	var st string
	err := r.q.QueryRow(ctx, `SELECT id::text, shipment_id::text, idempotency_key, carrier_code, carrier_status, normalized_status, COALESCE(description,''), COALESCE(location,''), event_time,
	  COALESCE(ndr_reason_code,''), COALESCE(ndr_remark,''), disposition, received_at FROM shipment_events WHERE id=$1::uuid`, id).
		Scan(&e.ID, &e.ShipmentID, &e.IdempotencyKey, &e.CarrierCode, &e.CarrierStatus, &st, &e.Description, &e.Location, &e.EventTime, &e.NDRReasonCode, &e.NDRRemark, &e.Disposition, &e.ReceivedAt)
	e.NormalizedStatus = domain.ShipmentStatus(st)
	return &e, notFound(err)
}

func (r *Repo) InsertWebhookInbox(ctx context.Context, carrier string, body []byte, outcome, detail, requestID string) error {
	var raw any
	if json.Valid(body) {
		raw = body
	}
	_, err := r.q.Exec(ctx, `INSERT INTO webhook_inbox (carrier_code, raw_payload, raw_body, outcome, detail, request_id) VALUES ($1,$2,$3,$4,$5,$6)`,
		carrier, raw, string(body), outcome, detail, requestID)
	return err
}

type InboxEntry struct {
	ID         string    `json:"id"`
	Carrier    string    `json:"carrierCode"`
	Outcome    string    `json:"outcome"`
	Detail     string    `json:"detail"`
	RawBody    string    `json:"rawBody"`
	ReceivedAt time.Time `json:"receivedAt"`
}

func (r *Repo) ListWebhookInbox(ctx context.Context, limit int) ([]InboxEntry, error) {
	rows, err := r.q.Query(ctx, `SELECT id::text, carrier_code, outcome, COALESCE(detail,''), COALESCE(raw_body,''), received_at FROM webhook_inbox ORDER BY received_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []InboxEntry
	for rows.Next() {
		var e InboxEntry
		if err := rows.Scan(&e.ID, &e.Carrier, &e.Outcome, &e.Detail, &e.RawBody, &e.ReceivedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func jsonOrNil(b []byte) any {
	if len(b) == 0 || !json.Valid(b) {
		return nil
	}
	return b
}

// ---- idempotency records ----

type IdempotencyRecord struct {
	RequestHash string
	StatusCode  int
	Response    []byte
}

func (r *Repo) GetIdempotency(ctx context.Context, scope, key string) (*IdempotencyRecord, error) {
	var rec IdempotencyRecord
	err := r.q.QueryRow(ctx, `SELECT request_hash, status_code, response FROM idempotency_records WHERE scope=$1 AND key=$2`, scope, key).Scan(&rec.RequestHash, &rec.StatusCode, &rec.Response)
	return &rec, notFound(err)
}

func (r *Repo) PutIdempotency(ctx context.Context, scope, key, hash string, status int, resp []byte) error {
	_, err := r.q.Exec(ctx, `INSERT INTO idempotency_records (scope, key, request_hash, status_code, response) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, scope, key, hash, status, resp)
	return err
}

// LockShipmentByTrackingNoLock is a read-only lookup by tracking number across the carrier.
func (r *Repo) LockShipmentByTrackingNoLock(ctx context.Context, carrierCode, tracking string) (*Shipment, error) {
	s, err := scanShipment(r.q.QueryRow(ctx, `SELECT `+shipCols+shipFrom+`WHERE s.carrier_code=$1 AND s.tracking_number=$2`, carrierCode, tracking))
	return s, notFound(err)
}
