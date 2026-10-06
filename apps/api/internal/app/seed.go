package app

import (
	"context"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/service"
)

type seedOrder struct {
	merchantOrderID string
	name, phone     string
	delivery        domain.Address
	carrier         string
	service         string
	events          []string
}

// SeedDemo creates demo data through the real flow (order -> rates -> select -> shipment -> carrier events),
// so the seeded shipments are genuine rows with genuine carrier-side records. It is idempotent: a repeated
// merchantOrderId is simply skipped. MERCHANT-10001 is deliberately NOT seeded; it is the evaluator's order.
func (a *App) SeedDemo(ctx context.Context) error {
	s := a.Services
	orders := []seedOrder{
		{"MERCHANT-09001", "Rahul Sharma", "9876543210", domain.Address{AddressLine1: "22 Connaught Place", City: "New Delhi", State: "Delhi", Pincode: "110001"}, "FASTSHIP", "FAST-AIR", []string{"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"}},
		{"MERCHANT-09002", "Ananya Iyer", "9845012345", domain.Address{AddressLine1: "14 Brigade Road", City: "Bengaluru", State: "Karnataka", Pincode: "560025"}, "QUICKEXPRESS", "EXPRESS", []string{"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"}},
		{"MERCHANT-09003", "Vikram Reddy", "9912345678", domain.Address{AddressLine1: "8 Banjara Hills Road", City: "Hyderabad", State: "Telangana", Pincode: "500034"}, "RELIABLE", "RC-SURFACE", []string{"PICKED_UP", "IN_TRANSIT"}},
	}
	for _, so := range orders {
		in := domain.CreateOrderInput{MerchantOrderID: so.merchantOrderID, MerchantID: "MRC-100",
			Customer:        domain.Customer{Name: so.name, Phone: so.phone, Email: "demo@example.com"},
			PickupAddress:   domain.Address{AddressLine1: "15 MG Road", City: "Bengaluru", State: "Karnataka", Pincode: "560001"},
			DeliveryAddress: so.delivery, Package: domain.Package{WeightGrams: 1500, LengthCm: 20, WidthCm: 15, HeightCm: 10},
			PaymentType: domain.PaymentCOD, CODAmount: 2500}
		res, _, err := s.CreateOrder(ctx, in, "")
		if err != nil {
			if ae, ok := domain.AsAppError(err); ok && ae.Code == "DUPLICATE_ORDER" {
				continue
			}
			return err
		}
		rr, err := s.FetchRates(ctx, res.OrderID, false, domain.SortPrice)
		if err != nil {
			return err
		}
		var pick *domain.Quote
		for i := range rr.ShippingOptions {
			q := rr.ShippingOptions[i]
			if q.CarrierCode == so.carrier && q.ServiceCode == so.service {
				pick = &q
			}
		}
		if pick == nil {
			continue
		}
		if _, err := s.SelectCarrier(ctx, res.OrderID, service.SelectCarrierInput{CarrierCode: pick.CarrierCode, ServiceCode: pick.ServiceCode, QuotedAmount: pick.TotalCharge, QuoteReference: pick.QuoteReference}); err != nil {
			return err
		}
		sh, _, err := s.CreateShipment(ctx, res.OrderID)
		if err != nil {
			return err
		}
		for _, ev := range so.events {
			if _, err := s.TriggerEvent(ctx, so.carrier, sh.ID, service.TriggerInput{Event: ev}); err != nil {
				return err
			}
			time.Sleep(15 * time.Millisecond) // distinct event timestamps keep history ordering stable
		}
	}
	return nil
}

// SeedWithRetry waits for mock carriers to come up (compose start order is not guaranteed).
func (a *App) SeedWithRetry(ctx context.Context) {
	for i := 0; i < 30; i++ {
		if err := a.SeedDemo(ctx); err == nil {
			a.Log.Info("demo data seeded", "event", "SEED_DONE")
			return
		} else {
			a.Log.Warn("seed attempt failed; will retry", "attempt", i+1, "error", err.Error())
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(2 * time.Second):
		}
	}
}
