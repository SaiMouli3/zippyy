package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type CreateOrderResult struct {
	ID              string    `json:"id"`
	OrderID         string    `json:"orderId"`
	MerchantOrderID string    `json:"merchantOrderId"`
	Status          string    `json:"status"`
	CreatedAt       time.Time `json:"createdAt"`
}

// CreateOrder validates and persists an order. A repeated (merchant, merchantOrderId) never creates a second
// order: it returns 409 DUPLICATE_ORDER pointing at the original. A repeated Idempotency-Key replays the
// original response byte-for-byte.
func (s *Services) CreateOrder(ctx context.Context, in domain.CreateOrderInput, idemKey string) (CreateOrderResult, int, error) {
	if ve := in.Validate(); ve != nil {
		return CreateOrderResult{}, 0, ve
	}
	hash := ""
	if idemKey != "" {
		b, _ := json.Marshal(in)
		sum := sha256.Sum256(b)
		hash = hex.EncodeToString(sum[:])
		rec, err := s.Store.R().GetIdempotency(ctx, "orders.create", idemKey)
		if err == nil {
			if rec.RequestHash != hash {
				return CreateOrderResult{}, 0, domain.NewError(http.StatusUnprocessableEntity, "IDEMPOTENCY_KEY_REUSED", "this Idempotency-Key was used with a different request body")
			}
			var res CreateOrderResult
			_ = json.Unmarshal(rec.Response, &res)
			return res, rec.StatusCode, nil
		} else if err != store.ErrNotFound {
			return CreateOrderResult{}, 0, err
		}
	}

	var order *domain.Order
	err := s.Store.InTx(ctx, func(r *store.Repo) error {
		o, err := r.CreateOrder(ctx, in)
		if err != nil {
			return err
		}
		order = o
		s.audit(ctx, r, store.AuditEntry{Action: "ORDER_CREATED", OrderID: o.ID, NewState: o.Status,
			RequestPayload: map[string]any{"merchantId": o.MerchantID, "merchantOrderId": o.MerchantOrderID, "customerPhone": platform.MaskPhone(o.Customer.Phone)}})
		return nil
	})
	if err != nil {
		if store.IsUniqueViolation(err, "orders_merchant_order_unique") {
			existing, ferr := s.Store.R().FindOrderByMerchantRef(ctx, in.MerchantID, in.MerchantOrderID)
			e := domain.Conflict("DUPLICATE_ORDER", "an order with this merchantOrderId already exists for the merchant")
			if ferr == nil {
				e = e.With("orderId", existing.OrderID)
			}
			return CreateOrderResult{}, 0, e
		}
		return CreateOrderResult{}, 0, err
	}
	res := CreateOrderResult{ID: order.ID, OrderID: order.OrderID, MerchantOrderID: order.MerchantOrderID, Status: order.Status, CreatedAt: order.CreatedAt}
	if idemKey != "" {
		b, _ := json.Marshal(res)
		_ = s.Store.R().PutIdempotency(ctx, "orders.create", idemKey, hash, http.StatusCreated, b)
	}
	platform.L(ctx).Info("order created", "event", "ORDER_CREATED", "orderId", order.OrderID, "merchantId", order.MerchantID)
	return res, http.StatusCreated, nil
}

func (s *Services) GetOrder(ctx context.Context, ref string) (*domain.Order, error) {
	o, err := s.Store.R().GetOrder(ctx, ref, false)
	if err == store.ErrNotFound {
		return nil, domain.NotFound("order")
	}
	return o, err
}

func (s *Services) ListOrders(ctx context.Context) ([]domain.Order, error) {
	return s.Store.R().ListOrders(ctx, 200)
}
