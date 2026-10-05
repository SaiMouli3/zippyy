package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

const orderCols = `id::text, zippy_order_id, merchant_id, merchant_order_id, customer_name, customer_phone, COALESCE(customer_email,''),
 pickup_address_line1, COALESCE(pickup_address_line2,''), pickup_city, pickup_state, pickup_pincode,
 delivery_address_line1, COALESCE(delivery_address_line2,''), delivery_city, delivery_state, delivery_pincode,
 weight_grams, length_cm::float8, width_cm::float8, height_cm::float8, payment_type, cod_amount::float8, COALESCE(language,''), status,
 COALESCE(selected_quote_id::text,''), COALESCE(selected_carrier_code,''), COALESCE(selected_service_code,''), quoted_amount::float8, selected_at, rates_fetched_at, created_at, updated_at`

type scanner interface{ Scan(dest ...any) error }

func scanOrder(r scanner) (*domain.Order, error) {
	var o domain.Order
	var pt string
	err := r.Scan(&o.ID, &o.OrderID, &o.MerchantID, &o.MerchantOrderID, &o.Customer.Name, &o.Customer.Phone, &o.Customer.Email,
		&o.PickupAddress.AddressLine1, &o.PickupAddress.AddressLine2, &o.PickupAddress.City, &o.PickupAddress.State, &o.PickupAddress.Pincode,
		&o.DeliveryAddress.AddressLine1, &o.DeliveryAddress.AddressLine2, &o.DeliveryAddress.City, &o.DeliveryAddress.State, &o.DeliveryAddress.Pincode,
		&o.Package.WeightGrams, &o.Package.LengthCm, &o.Package.WidthCm, &o.Package.HeightCm, &pt, &o.CODAmount, &o.Language, &o.Status,
		&o.SelectedQuoteID, &o.SelectedCarrierCode, &o.SelectedServiceCode, &o.QuotedAmount, &o.SelectedAt, &o.RatesFetchedAt, &o.CreatedAt, &o.UpdatedAt)
	o.PaymentType = domain.PaymentType(pt)
	return &o, err
}

// CreateOrder inserts an order, returning ErrDuplicateOrder (with the existing id) on a merchant/order repeat.
func (r *Repo) CreateOrder(ctx context.Context, in domain.CreateOrderInput) (*domain.Order, error) {
	row := r.q.QueryRow(ctx, `
INSERT INTO orders (zippy_order_id, merchant_id, merchant_order_id, customer_name, customer_phone, customer_email,
  pickup_address_line1, pickup_address_line2, pickup_city, pickup_state, pickup_pincode,
  delivery_address_line1, delivery_address_line2, delivery_city, delivery_state, delivery_pincode,
  weight_grams, length_cm, width_cm, height_cm, payment_type, cod_amount, language)
VALUES ('ZPY-ORD-'||nextval('order_seq'), $1,$2,$3,$4,NULLIF($5,''), $6,NULLIF($7,''),$8,$9,$10, $11,NULLIF($12,''),$13,$14,$15, $16,$17,$18,$19,$20,$21,NULLIF($22,''))
RETURNING `+orderCols,
		in.MerchantID, in.MerchantOrderID, in.Customer.Name, in.Customer.Phone, in.Customer.Email,
		in.PickupAddress.AddressLine1, in.PickupAddress.AddressLine2, in.PickupAddress.City, in.PickupAddress.State, in.PickupAddress.Pincode,
		in.DeliveryAddress.AddressLine1, in.DeliveryAddress.AddressLine2, in.DeliveryAddress.City, in.DeliveryAddress.State, in.DeliveryAddress.Pincode,
		in.Package.WeightGrams, in.Package.LengthCm, in.Package.WidthCm, in.Package.HeightCm, string(in.PaymentType), in.CODAmount, in.Language)
	return scanOrder(row)
}

func (r *Repo) FindOrderByMerchantRef(ctx context.Context, merchantID, merchantOrderID string) (*domain.Order, error) {
	o, err := scanOrder(r.q.QueryRow(ctx, `SELECT `+orderCols+` FROM orders WHERE merchant_id=$1 AND merchant_order_id=$2`, merchantID, merchantOrderID))
	return o, notFound(err)
}

// GetOrder resolves either the human id (ZPY-ORD-10001) or the internal UUID.
func (r *Repo) GetOrder(ctx context.Context, ref string, forUpdate bool) (*domain.Order, error) {
	q := `SELECT ` + orderCols + ` FROM orders WHERE zippy_order_id=$1`
	if _, err := uuid.Parse(ref); err == nil {
		q = `SELECT ` + orderCols + ` FROM orders WHERE id=$1::uuid`
	}
	if forUpdate {
		q += ` FOR UPDATE`
	}
	o, err := scanOrder(r.q.QueryRow(ctx, q, ref))
	return o, notFound(err)
}

func (r *Repo) ListOrders(ctx context.Context, limit int) ([]domain.Order, error) {
	rows, err := r.q.Query(ctx, `SELECT `+orderCols+` FROM orders ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []domain.Order
	for rows.Next() {
		o, err := scanOrder(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *o)
	}
	return out, rows.Err()
}

func (r *Repo) SetOrderStatus(ctx context.Context, orderID string, status string) error {
	_, err := r.q.Exec(ctx, `UPDATE orders SET status=$2, updated_at=now() WHERE id=$1::uuid`, orderID, status)
	return err
}

func (r *Repo) SetOrderDeliveryAddress(ctx context.Context, orderID string, a domain.Address) error {
	_, err := r.q.Exec(ctx, `UPDATE orders SET delivery_address_line1=$2, delivery_address_line2=NULLIF($3,''), delivery_city=$4, delivery_state=$5, delivery_pincode=$6, updated_at=now() WHERE id=$1::uuid`,
		orderID, a.AddressLine1, a.AddressLine2, a.City, a.State, a.Pincode)
	return err
}

func (r *Repo) SetOrderPhone(ctx context.Context, orderID, phone string) error {
	_, err := r.q.Exec(ctx, `UPDATE orders SET customer_phone=$2, updated_at=now() WHERE id=$1::uuid`, orderID, phone)
	return err
}

func (r *Repo) SetOrderPaymentPrepaid(ctx context.Context, orderID string) error {
	_, err := r.q.Exec(ctx, `UPDATE orders SET payment_type='PREPAID', cod_amount=0, updated_at=now() WHERE id=$1::uuid`, orderID)
	return err
}

// ---- quotes ----

type StoredQuote struct {
	domain.Quote
	OrderID      string
	QuoteGroupID string
	CreatedAt    time.Time
}

// InsertQuoteGroup persists a full set of quotes for an order atomically with one group id.
func (r *Repo) InsertQuoteGroup(ctx context.Context, orderID, cacheKey string, quotes []domain.Quote, raws [][]byte, expiresAt time.Time) (string, error) {
	group := uuid.NewString()
	for i, q := range quotes {
		var raw []byte
		if i < len(raws) && len(raws[i]) > 0 {
			raw = raws[i]
		}
		if _, err := r.q.Exec(ctx, `
INSERT INTO shipping_quotes (order_id, quote_group_id, cache_key, carrier_code, carrier_name, service_code, service_name, base_charge, cod_charge,
  additional_charges, tax, total_charge, estimated_min_days, estimated_max_days, quote_reference, raw_carrier_response, expires_at)
VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)`,
			orderID, group, cacheKey, q.CarrierCode, q.CarrierName, q.ServiceCode, q.ServiceName, q.BaseCharge, q.CODCharge, q.AdditionalCharges,
			q.Tax, q.TotalCharge, q.EstimatedMinDays, q.EstimatedMaxDays, q.QuoteReference, raw, expiresAt); err != nil {
			return "", err
		}
	}
	_, err := r.q.Exec(ctx, `UPDATE orders SET rates_fetched_at=now(), updated_at=now(),
	   status = CASE WHEN status='ORDER_CREATED' THEN 'RATES_FETCHED' ELSE status END WHERE id=$1::uuid`, orderID)
	return group, err
}

const quoteCols = `id::text, order_id::text, quote_group_id::text, carrier_code, carrier_name, service_code, service_name, base_charge::float8, cod_charge::float8,
 additional_charges::float8, tax::float8, total_charge::float8, estimated_min_days, estimated_max_days, quote_reference, expires_at, created_at`

func scanQuote(r scanner) (StoredQuote, error) {
	var q StoredQuote
	var exp time.Time
	err := r.Scan(&q.ID, &q.OrderID, &q.QuoteGroupID, &q.CarrierCode, &q.CarrierName, &q.ServiceCode, &q.ServiceName, &q.BaseCharge, &q.CODCharge,
		&q.AdditionalCharges, &q.Tax, &q.TotalCharge, &q.EstimatedMinDays, &q.EstimatedMaxDays, &q.QuoteReference, &exp, &q.CreatedAt)
	q.ExpiresAt = &exp
	return q, err
}

// LatestQuotes returns the most recent quote group for an order, price-sorted.
func (r *Repo) LatestQuotes(ctx context.Context, orderID string) ([]StoredQuote, error) {
	rows, err := r.q.Query(ctx, `SELECT `+quoteCols+` FROM shipping_quotes
	  WHERE order_id=$1::uuid AND quote_group_id = (SELECT quote_group_id FROM shipping_quotes WHERE order_id=$1::uuid ORDER BY created_at DESC, id LIMIT 1)
	  ORDER BY total_charge ASC, carrier_code, service_code`, orderID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []StoredQuote
	for rows.Next() {
		q, err := scanQuote(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, q)
	}
	return out, rows.Err()
}

func (r *Repo) GetQuote(ctx context.Context, id string) (*StoredQuote, error) {
	q, err := scanQuote(r.q.QueryRow(ctx, `SELECT `+quoteCols+` FROM shipping_quotes WHERE id=$1::uuid`, id))
	return &q, notFound(err)
}

// SelectQuote records the accepted quote. The amount copied here is the stored one, never the client's.
func (r *Repo) SelectQuote(ctx context.Context, orderID string, q StoredQuote) error {
	_, err := r.q.Exec(ctx, `UPDATE orders SET selected_quote_id=$2::uuid, selected_carrier_code=$3, selected_service_code=$4, quoted_amount=$5,
	   selected_at=now(), status='CARRIER_SELECTED', updated_at=now() WHERE id=$1::uuid`, orderID, q.ID, q.CarrierCode, q.ServiceCode, q.TotalCharge)
	return err
}
