package domain

import (
	"strings"
	"testing"
)

func TestTransitionTable(t *testing.T) {
	all := []ShipmentStatus{StatusShipmentCreated, StatusPickedUp, StatusInTransit, StatusOutForDelivery, StatusDelivered, StatusDeliveryFailed, StatusRTO}
	// the happy path
	for _, p := range [][2]ShipmentStatus{{StatusShipmentCreated, StatusPickedUp}, {StatusPickedUp, StatusInTransit}, {StatusInTransit, StatusOutForDelivery}, {StatusOutForDelivery, StatusDelivered},
		{StatusOutForDelivery, StatusDeliveryFailed}, {StatusDeliveryFailed, StatusOutForDelivery}, {StatusDeliveryFailed, StatusRTO}, {StatusShipmentCreated, StatusOutForDelivery}} {
		if CheckTransition(p[0], p[1]) != TransitionApply {
			t.Errorf("%s -> %s should apply", p[0], p[1])
		}
	}
	// regressions are rejected
	for _, p := range [][2]ShipmentStatus{{StatusDelivered, StatusInTransit}, {StatusDelivered, StatusPickedUp}, {StatusInTransit, StatusPickedUp}, {StatusOutForDelivery, StatusShipmentCreated},
		{StatusOutForDelivery, StatusInTransit}, {StatusRTO, StatusDelivered}, {StatusDelivered, StatusRTO}, {StatusPickedUp, StatusShipmentCreated}} {
		if CheckTransition(p[0], p[1]) != TransitionReject {
			t.Errorf("%s -> %s must be rejected", p[0], p[1])
		}
	}
	// terminal states reject everything, including themselves
	for _, to := range all {
		for _, from := range []ShipmentStatus{StatusDelivered, StatusRTO} {
			if CheckTransition(from, to) != TransitionReject {
				t.Errorf("terminal %s -> %s must be rejected", from, to)
			}
		}
	}
	if CheckTransition(StatusInTransit, StatusInTransit) != TransitionSame {
		t.Error("repeat of a non-terminal state is recorded without a state change")
	}
}

func TestCaseStateMachine(t *testing.T) {
	ok := [][2]CaseState{{CaseOpened, CaseBuyerContactPending}, {CaseBuyerContactPending, CaseBuyerResponded}, {CaseBuyerResponded, CaseIntentExtracted}, {CaseIntentExtracted, CaseActionPending},
		{CaseActionPending, CaseActionSubmitted}, {CaseActionSubmitted, CaseCarrierAccepted}, {CaseCarrierAccepted, CaseReattemptScheduled}, {CaseReattemptScheduled, CaseResolved}, {CaseResolved, CaseClosed},
		{CaseIntentExtracted, CaseAwaitingApproval}, {CaseAwaitingApproval, CaseActionPending}}
	for _, p := range ok {
		if !CanTransition(p[0], p[1]) {
			t.Errorf("%s -> %s should be allowed", p[0], p[1])
		}
	}
	bad := [][2]CaseState{{CaseOpened, CaseCarrierAccepted}, {CaseBuyerContactPending, CaseReattemptScheduled}, {CaseClosed, CaseOpened}, {CaseAwaitingApproval, CaseCarrierAccepted},
		{CaseIntentExtracted, CaseCarrierAccepted}, {CaseActionPending, CaseCarrierAccepted}, {CaseOpened, CaseResolved}}
	for _, p := range bad {
		if CanTransition(p[0], p[1]) {
			t.Errorf("%s -> %s must NOT be allowed (no skipping approval/submission/acceptance)", p[0], p[1])
		}
	}
}

func TestOrderValidation(t *testing.T) {
	good := CreateOrderInput{MerchantOrderID: "M-1", MerchantID: "MRC-100", Customer: Customer{Name: "R", Phone: "9876543210"},
		PickupAddress:   Address{AddressLine1: "a", City: "c", State: "s", Pincode: "560001"},
		DeliveryAddress: Address{AddressLine1: "a", City: "c", State: "s", Pincode: "110001"},
		Package:         Package{WeightGrams: 1, LengthCm: 1, WidthCm: 1, HeightCm: 1}, PaymentType: "cod", CODAmount: 10}
	if err := good.Validate(); err != nil {
		t.Fatal(err)
	}
	if good.PaymentType != PaymentCOD {
		t.Fatal("payment type should be normalised")
	}
	bad := good
	bad.CODAmount = 0
	if err := bad.Validate(); err == nil || err.Details["fields"].(map[string]string)["codAmount"] == "" {
		t.Fatal("COD amount must be > 0")
	}
	for _, p := range []string{"1234567890", "98765", "abcdefghij", ""} {
		bad = good
		bad.Customer.Phone = p
		if bad.Validate() == nil {
			t.Errorf("phone %q should be invalid", p)
		}
	}
	for _, p := range []string{"012345", "12345", "1234567", "abcdef"} {
		bad = good
		bad.DeliveryAddress.Pincode = p
		if bad.Validate() == nil {
			t.Errorf("pincode %q should be invalid", p)
		}
	}
}

func TestMoneyIsCompared_ToThePaisa(t *testing.T) {
	if !SameAmount(182.90, 182.9000001) || SameAmount(182.90, 182.91) {
		t.Fatal("amounts compare to the paisa")
	}
	if Round2(27.899999) != 27.9 {
		t.Fatal("round2")
	}
}

func TestSortQuotes(t *testing.T) {
	qs := []Quote{{CarrierCode: "B", CarrierName: "B", ServiceCode: "S", TotalCharge: 200, EstimatedMinDays: 2, EstimatedMaxDays: 3},
		{CarrierCode: "A", CarrierName: "A", ServiceCode: "S", TotalCharge: 150, EstimatedMinDays: 5, EstimatedMaxDays: 6},
		{CarrierCode: "C", CarrierName: "C", ServiceCode: "S", TotalCharge: 160, EstimatedMinDays: 2, EstimatedMaxDays: 2}}
	SortQuotes(qs, SortPrice)
	if qs[0].CarrierCode != "A" || qs[2].CarrierCode != "B" {
		t.Fatalf("price: %+v", qs)
	}
	SortQuotes(qs, SortETA)
	if qs[0].CarrierCode != "C" || qs[1].CarrierCode != "B" {
		t.Fatalf("eta: %+v", qs)
	}
	SortQuotes(qs, SortCarrier)
	if qs[0].CarrierCode != "A" || qs[1].CarrierCode != "B" || qs[2].CarrierCode != "C" {
		t.Fatalf("carrier: %+v", qs)
	}
}

func TestRateCacheKeyFormat(t *testing.T) {
	o := Order{MerchantID: "MRC-100", PickupAddress: Address{Pincode: "560001"}, DeliveryAddress: Address{Pincode: "110001"},
		Package: Package{WeightGrams: 1500, LengthCm: 20, WidthCm: 15, HeightCm: 10}, PaymentType: PaymentCOD, CODAmount: 2500}
	if got := RateCacheKey(o); got != "zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500" {
		t.Fatal(got)
	}
	o.CODAmount = 2500.5
	if !strings.HasSuffix(RateCacheKey(o), ":COD:2500.5") {
		t.Fatal(RateCacheKey(o))
	}
}
