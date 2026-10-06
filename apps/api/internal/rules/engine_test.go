package rules

import (
	"testing"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

var allActions = []string{"REQUEST_REATTEMPT", "RESCHEDULE", "UPDATE_PHONE", "UPDATE_ADDRESS", "CONVERT_TO_PREPAID", "INITIATE_RTO"}

func seller() domain.SellerRules {
	return domain.SellerRules{MerchantID: "MRC-100", MaxAttempts: 3, AutoRTOAttempt: 3, CODLimit: 10000, AllowedChannels: []string{"WHATSAPP", "IVR", "SMS"},
		PrepaidConversionAllowed: true, AllowAddressChanges: true, EarlyRTOPolicy: "APPROVAL", AllowedActions: allActions, DefaultOnSilence: "RTO",
		CommHoursStart: "08:00", CommHoursEnd: "21:00"}
}

func fast() domain.CarrierRules {
	return domain.CarrierRules{CarrierCode: "FASTSHIP", MaxAttempts: 3, InstructionCutoff: "23:00", HoldWindowDays: 7, SupportedActions: allActions,
		SupportsTimeSlot: true, CanChangePaymentMode: true, CanChangeAddress: true, CanChangePhone: true}
}

func reliable() domain.CarrierRules {
	c := fast()
	c.CarrierCode, c.MaxAttempts, c.HoldWindowDays, c.SupportsTimeSlot, c.CanChangeAddress = "RELIABLE", 2, 4, false, false
	c.SupportedActions = []string{"REQUEST_REATTEMPT", "RESCHEDULE", "UPDATE_PHONE", "CONVERT_TO_PREPAID", "INITIATE_RTO"}
	return c
}

// 2026-10-05 12:00 IST
var now = time.Date(2026, 10, 5, 12, 0, 0, 0, IST)

func sp(s string) *string { return &s }

func base(intent domain.ExtractedIntent) Input {
	return Input{Reason: domain.ReasonCustUnavailable, Attempt: 1, Seller: seller(), Carrier: fast(), Now: now, ConfidenceMin: 0.75, Intent: intent,
		Order: OrderFacts{PaymentType: domain.PaymentCOD, CODAmount: 2500, DeliveryAddress: domain.Address{AddressLine1: "22 Connaught Place", City: "New Delhi", State: "Delhi", Pincode: "110001"}}}
}

func resched(date string) domain.ExtractedIntent {
	return domain.ExtractedIntent{Intent: domain.IntentRescheduleDelivery, PreferredDate: sp(date), PreferredTimeStart: sp("18:00"), SpecialInstruction: sp("Inform the security guard"), Confidence: 0.96}
}

func TestUC1RescheduleInsideHoldWindowIsAgentAllowed(t *testing.T) {
	d := Evaluate(base(resched("2026-10-06")))
	if d.Outcome != AgentAllowed || len(d.Plan) != 1 || d.Plan[0].Type != domain.ActionReattempt || d.Plan[0].Date != "2026-10-06" || d.Plan[0].TimeStart != "18:00" {
		t.Fatalf("%+v", d)
	}
	if d.Plan[0].Remark == "" || !contains(d.Plan[0].Remark, "security guard") || !contains(d.Plan[0].Remark, "after 18:00") {
		t.Fatalf("remark must be structured English: %q", d.Plan[0].Remark)
	}
	needChecks(t, d, "seller.allowed_action.REQUEST_REATTEMPT", "carrier.supported_action.REQUEST_REATTEMPT", "carrier.hold_window", "carrier.max_attempts")
}

func TestPriorAcceptedReattemptBecomesReschedule(t *testing.T) {
	in := base(resched("2026-10-06"))
	in.PriorReattemptAccepted = true
	if d := Evaluate(in); d.Plan[0].Type != domain.ActionReschedule {
		t.Fatalf("%+v", d.Plan)
	}
}

func TestUC7BeyondHoldWindowOffersNearestValidDate(t *testing.T) {
	d := Evaluate(base(resched("2026-10-25")))
	if d.Outcome != OfferAlternative || d.BuyerParams["date"] != "2026-10-12" || d.Pending == nil || d.Pending.Type != "DATE_OFFER" || len(d.Plan) != 0 {
		t.Fatalf("%+v", d)
	}
	// buyer says yes -> deterministic re-evaluation succeeds on the offered date
	in := base(domain.ExtractedIntent{Intent: domain.IntentConfirmYes, Confidence: 0.95})
	in.Pending = d.Pending
	d2 := Evaluate(in)
	if d2.Outcome != AgentAllowed || d2.Plan[0].Date != "2026-10-12" {
		t.Fatalf("%+v", d2)
	}
}

func TestInstructionCutoffMovesEarliestDate(t *testing.T) {
	in := base(resched("2026-10-06"))
	in.Now = time.Date(2026, 10, 5, 23, 30, 0, 0, IST) // after FastShip's 23:00 cutoff
	d := Evaluate(in)
	if d.Outcome != OfferAlternative || d.BuyerParams["date"] != "2026-10-07" || d.BuyerKey != "offer.date_cutoff" {
		t.Fatalf("%+v", d)
	}
}

func TestLowConfidenceNeverActs(t *testing.T) {
	i := resched("2026-10-06")
	i.Confidence = 0.5
	i.InternalSummary = "reschedule to tomorrow"
	d := Evaluate(base(i))
	if d.Outcome != NeedsConfirmation || len(d.Plan) != 0 || d.Pending == nil || d.Pending.Type != "LOW_CONFIDENCE" {
		t.Fatalf("%+v", d)
	}
	in := base(domain.ExtractedIntent{Intent: domain.IntentConfirmYes, Confidence: 0.9})
	in.Pending = d.Pending
	if d2 := Evaluate(in); d2.Outcome != AgentAllowed || d2.Plan[0].Date != "2026-10-06" {
		t.Fatalf("confirmation should execute the confirmed intent: %+v", d2)
	}
	in.Intent = domain.ExtractedIntent{Intent: domain.IntentConfirmNo, Confidence: 0.9}
	if d3 := Evaluate(in); d3.Outcome != Clarify || len(d3.Plan) != 0 {
		t.Fatalf("%+v", d3)
	}
}

func TestUnknownIntentClarifies(t *testing.T) {
	d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentUnknown, Confidence: 0.1}))
	if d.Outcome != Clarify || len(d.Plan) != 0 {
		t.Fatalf("%+v", d)
	}
}

func TestAddressCorrectionScopes(t *testing.T) {
	// same pincode: agent allowed, address update + reattempt
	i := domain.ExtractedIntent{Intent: domain.IntentAddressCorrection, Landmark: sp("Opposite Metro pillar 12"), NewPincode: sp("110001"), Confidence: 0.9}
	d := Evaluate(base(i))
	if d.Outcome != AgentAllowed || len(d.Plan) != 2 || d.Plan[0].Type != domain.ActionUpdateAddress || d.Plan[1].Type != domain.ActionReattempt || d.Plan[0].Address.AddressLine2 != "Opposite Metro pillar 12" {
		t.Fatalf("same-pincode: %+v", d)
	}
	// new pincode: seller approval
	i.NewPincode = sp("110002")
	d = Evaluate(base(i))
	if d.Outcome != SellerApproval || len(d.Approvals) != 1 || d.Approvals[0].Kind != "ADDRESS_NEW_PINCODE" || !d.Approvals[0].Blocking {
		t.Fatalf("new pincode: %+v", d)
	}
	// new city: seller + ops
	i.NewPincode, i.NewCity = sp("400001"), sp("Mumbai")
	d = Evaluate(base(i))
	if d.Outcome != SellerOpsApproval || len(d.Approvals[0].Roles) != 2 {
		t.Fatalf("new city: %+v", d)
	}
	// "Delhi" vs "New Delhi" is not a city change
	i.NewPincode, i.NewCity = sp("110001"), sp("Delhi")
	if d = Evaluate(base(i)); d.Outcome != AgentAllowed {
		t.Fatalf("delhi alias: %+v", d)
	}
}

func TestAddressChangeNotSupportedByCarrierEscalates(t *testing.T) {
	in := base(domain.ExtractedIntent{Intent: domain.IntentAddressCorrection, Landmark: sp("near temple"), Confidence: 0.9})
	in.Carrier = reliable()
	d := Evaluate(in)
	if d.Outcome != Escalate || len(d.Plan) != 0 {
		t.Fatalf("%+v", d)
	}
}

func TestAddressChangesDisallowedBySeller(t *testing.T) {
	in := base(domain.ExtractedIntent{Intent: domain.IntentAddressCorrection, Landmark: sp("near temple"), Confidence: 0.9})
	in.Seller.AllowAddressChanges = false
	if d := Evaluate(in); d.Outcome != SellerApproval {
		t.Fatalf("%+v", d)
	}
}

func TestPhoneUpdateAgentAllowedAndValidation(t *testing.T) {
	d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentAlternateContact, NewPhone: sp("9123456780"), Confidence: 0.9}))
	if d.Outcome != AgentAllowed || len(d.Plan) != 2 || d.Plan[0].Type != domain.ActionUpdatePhone || d.Plan[0].Phone != "9123456780" || d.Plan[1].Type != domain.ActionReattempt {
		t.Fatalf("%+v", d)
	}
	if d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentPhoneUpdate, NewPhone: sp("12345"), Confidence: 0.9})); d.Outcome != Clarify {
		t.Fatalf("invalid phone must clarify: %+v", d)
	}
}

func TestCancelEarlyRTOPolicies(t *testing.T) {
	cancel := domain.ExtractedIntent{Intent: domain.IntentCancelOrder, Confidence: 0.93}
	in := base(cancel)
	if d := Evaluate(in); d.Outcome != SellerApproval || d.Approvals[0].Kind != "EARLY_RTO" || d.Plan[0].Type != domain.ActionInitiateRTO {
		t.Fatalf("approval policy: %+v", d)
	}
	in.Seller.EarlyRTOPolicy = "AUTO"
	if d := Evaluate(in); d.Outcome != AgentAllowed || d.Plan[0].Type != domain.ActionInitiateRTO {
		t.Fatalf("auto policy: %+v", d)
	}
	in.Seller.EarlyRTOPolicy = "DISALLOWED"
	if d := Evaluate(in); d.Outcome != Clarify || len(d.Plan) != 0 {
		t.Fatalf("disallowed policy: %+v", d)
	}
}

func TestRefuseAsksReasonFirst(t *testing.T) {
	d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentRefuseOrder, Confidence: 0.8}))
	if d.Outcome != Clarify || d.BuyerKey != "ask.reason" {
		t.Fatalf("%+v", d)
	}
}

func TestCODNotReadyPrepaidOfferThenPaymentFlow(t *testing.T) {
	d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentCODNotReady, Confidence: 0.9}))
	if d.Outcome != OfferPrepaid || d.Pending == nil || d.Pending.Type != "PREPAID_OFFER" {
		t.Fatalf("%+v", d)
	}
	in := base(domain.ExtractedIntent{Intent: domain.IntentConfirmYes, Confidence: 0.95})
	in.Pending = d.Pending
	link := Evaluate(in)
	if link.Outcome != SendPaymentLink || link.Pending.Type != "PAYMENT_LINK_SENT" {
		t.Fatalf("%+v", link)
	}
	in = base(domain.ExtractedIntent{Intent: domain.IntentPaymentDone, Confidence: 0.9})
	in.Pending = link.Pending
	paid := Evaluate(in)
	if paid.Outcome != AgentAllowed || len(paid.Plan) != 2 || paid.Plan[0].Type != domain.ActionConvertPrepaid || paid.Plan[1].Type != domain.ActionReattempt {
		t.Fatalf("%+v", paid)
	}
	// payment claim without a link is never acted on
	in.Pending = nil
	if d := Evaluate(in); d.Outcome != Clarify {
		t.Fatalf("%+v", d)
	}
}

func TestCODNotReadyWithDateSchedulesReattemptAndPrepaidRuleRespected(t *testing.T) {
	d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentCODNotReady, PreferredDate: sp("2026-10-06"), Confidence: 0.9}))
	if d.Outcome != AgentAllowed || d.Plan[0].Date != "2026-10-06" {
		t.Fatalf("%+v", d)
	}
	in := base(domain.ExtractedIntent{Intent: domain.IntentCODNotReady, Confidence: 0.9})
	in.Seller.PrepaidConversionAllowed = false
	if d := Evaluate(in); d.Outcome != Clarify || d.BuyerKey != "ask.cod_date" {
		t.Fatalf("seller rule disallows prepaid: %+v", d)
	}
	in = base(domain.ExtractedIntent{Intent: domain.IntentCODNotReady, Confidence: 0.9})
	in.Carrier = reliable()
	in.Carrier.CanChangePaymentMode = false
	if d := Evaluate(in); d.Outcome != Clarify {
		t.Fatalf("carrier cannot change payment mode: %+v", d)
	}
}

func TestFalseAttemptRequestsReattemptAndDraftsDispute(t *testing.T) {
	d := Evaluate(base(domain.ExtractedIntent{Intent: domain.IntentFalseAttempt, Confidence: 0.9}))
	if d.Outcome != AgentAllowed || d.ReasonOverride != domain.ReasonSuspectFalse || len(d.Plan) != 1 {
		t.Fatalf("%+v", d)
	}
	if len(d.Approvals) != 1 || d.Approvals[0].Kind != "DISPUTE_DRAFT" || d.Approvals[0].Blocking || d.Approvals[0].Roles[0] != domain.RoleOps {
		t.Fatalf("dispute must be a non-blocking ops approval: %+v", d.Approvals)
	}
}

func TestAttemptLimits(t *testing.T) {
	in := base(resched("2026-10-06"))
	in.Attempt = 3 // seller max 3 reached, carrier max 3 reached
	if d := Evaluate(in); d.Outcome != Escalate {
		t.Fatalf("carrier cap is a hard stop: %+v", d)
	}
	in.Carrier.MaxAttempts = 5 // only seller cap
	if d := Evaluate(in); d.Outcome != SellerApproval || d.Approvals[0].Kind != "EXTRA_ATTEMPT" {
		t.Fatalf("seller cap needs approval: %+v", d)
	}
}

func TestCODLimitNeedsApprovalOnRepeatAttempts(t *testing.T) {
	in := base(resched("2026-10-06"))
	in.Order.CODAmount = 25000
	if d := Evaluate(in); d.Outcome != AgentAllowed {
		t.Fatalf("first attempt is fine: %+v", d)
	}
	in.Attempt = 2
	if d := Evaluate(in); d.Outcome != SellerApproval || d.Approvals[0].Kind != "HIGH_VALUE_COD_REATTEMPT" {
		t.Fatalf("%+v", d)
	}
}

func TestSellerActionAllowListAndCarrierSupport(t *testing.T) {
	in := base(resched("2026-10-06"))
	in.Seller.AllowedActions = []string{"UPDATE_PHONE"}
	if d := Evaluate(in); d.Outcome != SellerApproval {
		t.Fatalf("not pre-authorised: %+v", d)
	}
	in = base(resched("2026-10-06"))
	in.Carrier.SupportedActions = []string{"INITIATE_RTO"}
	if d := Evaluate(in); d.Outcome != Escalate {
		t.Fatalf("carrier cannot do it: %+v", d)
	}
}

func TestTimeSlotUnsupportedCarrierGetsAdvisoryRemarkOnly(t *testing.T) {
	in := base(resched("2026-10-06"))
	in.Carrier = reliable()
	d := Evaluate(in)
	if d.Outcome != AgentAllowed || d.Plan[0].TimeStart != "" || !contains(d.Plan[0].Remark, "advisory") {
		t.Fatalf("%+v", d.Plan)
	}
	if d.BuyerParams["time"] != "" {
		t.Fatal("must not promise a time slot the carrier cannot honour")
	}
}

func TestDefaultOnNoResponse(t *testing.T) {
	in := base(domain.ExtractedIntent{})
	in.Attempt = 1
	d := DefaultOnNoResponse(in)
	if d.Outcome != AgentAllowed || d.Plan[0].Type != domain.ActionReattempt {
		t.Fatalf("non-final: %+v", d)
	}
	in.Attempt = 3
	d = DefaultOnNoResponse(in)
	if d.Outcome != SellerApproval || d.Approvals[0].Kind != "FINAL_ATTEMPT_DECISION" || d.Plan[0].Type != domain.ActionInitiateRTO {
		t.Fatalf("final attempt must ask seller: %+v", d)
	}
	r := RTOByDefault(in)
	if r.Outcome != AgentAllowed || r.Plan[0].Type != domain.ActionInitiateRTO {
		t.Fatalf("%+v", r)
	}
	in.Seller.DefaultOnSilence = "ESCALATE"
	if r := RTOByDefault(in); r.Outcome != Escalate {
		t.Fatalf("%+v", r)
	}
}

func TestCommHoursAndChannelOrder(t *testing.T) {
	s := seller()
	if ok, _ := CommAllowed(s, time.Date(2026, 10, 5, 3, 0, 0, 0, IST)); !ok {
		t.Fatal("not enforced by default")
	}
	s.EnforceCommHours = true
	if ok, _ := CommAllowed(s, time.Date(2026, 10, 5, 3, 0, 0, 0, IST)); ok {
		t.Fatal("3am is outside hours")
	}
	if ok, _ := CommAllowed(s, time.Date(2026, 10, 5, 10, 0, 0, 0, IST)); !ok {
		t.Fatal("10am is inside hours")
	}
	s.AllowedChannels = []string{"SMS", "WHATSAPP"}
	if got := ChannelOrder(s); len(got) != 2 || got[0] != "WHATSAPP" || got[1] != "SMS" {
		t.Fatalf("priority must be WhatsApp > IVR > SMS: %v", got)
	}
}

func TestRecommendedActionCoversEveryReason(t *testing.T) {
	for _, r := range domain.AllNDRReasons {
		if RecommendedAction(r) == "ASK_BUYER" {
			t.Errorf("reason %s has no playbook", r)
		}
	}
}

func contains(s, sub string) bool {
	return len(sub) == 0 || (len(s) >= len(sub) && (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})())
}

func needChecks(t *testing.T, d Decision, rules ...string) {
	t.Helper()
	have := map[string]bool{}
	for _, c := range d.Checks {
		have[c.Rule] = true
	}
	for _, r := range rules {
		if !have[r] {
			t.Errorf("expected rule check %q to be recorded; have %v", r, d.Checks)
		}
	}
}
