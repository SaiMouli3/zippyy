package tests

import (
	"fmt"
	"strings"
	"testing"

	"github.com/saimouli3/zippyy/apps/api/testkit"
)

func TestNDRCaseCreatedWithNormalizedReasonsPerCarrier(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	cases := []struct{ carrier, service, reason, code string }{
		{"FASTSHIP", "FAST-AIR", "ADDRESS_ISSUE", "ADDRESS_INCOMPLETE"},
		{"QUICKEXPRESS", "EXPRESS", "COD_NOT_READY", "NDR-05"},
		{"RELIABLE", "RC-SURFACE", "PHONE_UNREACHABLE", "R-14"},
		{"FASTSHIP", "FAST-AIR", "ACCESS_RESTRICTED", "ACCESS_DENIED"},
		{"QUICKEXPRESS", "EXPRESS", "FUTURE_DELIVERY", "NDR-06"},
		{"RELIABLE", "RC-SURFACE", "CUST_REFUSED", "R-12"},
		{"FASTSHIP", "FAST-AIR", "SUSPECT_FALSE_ATTEMPT", "ATTEMPT_ANOMALY"},
	}
	for i, c := range cases {
		s := e.NewShipment(fmt.Sprintf("NR-%d", i), c.carrier, c.service, testkit.OrderOpts{Phone: fmt.Sprintf("98765432%02d", i+10)})
		id := e.OpenNDR(s, c.reason)
		r := e.Case(id)
		if r.Str("case.normalizedReason") != c.reason || r.Str("case.carrierReasonCode") != c.code || r.Num("case.attemptNumber") != 1 || r.Str("case.state") != "OPENED" ||
			r.Str("case.reasonSource") != "MAPPING" || r.Str("case.carrierRemark") == "" || r.Str("case.carrierCode") != c.carrier || r.Str("case.recommendedAction") == "" ||
			r.At("sellerRules.maxAttempts") == nil || r.At("carrierRules.holdWindowDays") == nil {
			t.Errorf("%s/%s: %s", c.carrier, c.reason, r.Raw)
		}
		if r.Str("case.language") == "" || r.Str("case.languageSource") == "" {
			t.Errorf("language is a first-class field: %s", r.Raw)
		}
		if et := eventTypes(e, id); len(et) != 1 || et[0] != "CARRIER_NDR" {
			t.Errorf("timeline: %v", et)
		}
	}
	// shipment is DELIVERY_FAILED; order mirrors it
	if got := e.Get("/api/ndr/cases?reason=PHONE_UNREACHABLE"); got.Len("cases") != 1 {
		t.Fatalf("filtering by reason: %s", got.Raw)
	}
}

func TestUnknownCarrierReasonCodeFallsBackToRemarkInterpretation(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("NR-OTHER", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	e.ToOFD(s)
	r := e.Post("/api/mock-carriers/FASTSHIP/shipments/"+s.ShipmentID+"/trigger", map[string]any{"event": "NDR", "ndrReason": "OTHER", "remark": "Society security did not allow entry, gate closed"})
	if r.Str("deliveries.0.status") != "200" {
		t.Fatalf("%s", r.Raw)
	}
	c := e.Get("/api/ndr/cases?orderId=" + s.OrderID)
	if c.Str("cases.0.normalizedReason") != "ACCESS_RESTRICTED" || c.Str("cases.0.reasonSource") != "LLM_REMARK" || c.Str("cases.0.carrierReasonCode") != "OTHER" {
		t.Fatalf("messy remark must be interpreted into the taxonomy and flagged as AI-sourced: %s", c.Raw)
	}
}

func TestOutOfAreaEscalatesImmediately(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("NR-OOA", "RELIABLE", "RC-SURFACE", testkit.OrderOpts{})
	id := e.OpenNDR(s, "OUT_OF_AREA")
	if state(e, id) != "ESCALATED" {
		t.Fatalf("out-of-area must escalate to carrier/ops: %s", state(e, id))
	}
}

// The scenario from the brief (section 58), end to end.
func TestUC1BuyerUnavailableReattemptAcceptedThenDelivered(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Language: "kn"})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")

	c := e.Case(id)
	if c.Str("case.language") != "kn" || c.Str("case.languageSource") != "seller" {
		t.Fatalf("initial language comes from the seller order language: %s", c.Raw)
	}
	ct := contact(e, id, nil)
	if !ct.Bool("delivered") || ct.Str("channel") != "WHATSAPP" || ct.Str("case.state") != "BUYER_CONTACT_PENDING" {
		t.Fatalf("WhatsApp is the first channel: %s", ct.Raw)
	}
	first := outbound(e, id)[0]
	if !strings.Contains(first, "ಡೆಲಿವರಿ") {
		t.Fatalf("agent must contact the buyer in the case language (Kannada): %q", first)
	}

	const buyerText = "Tomorrow evening after 6. Please tell security guard."
	r := reply(e, id, buyerText)
	if r.Str("intent.intent") != "RESCHEDULE_DELIVERY" || r.Str("intent.preferredDate") != istDate(1) || r.Str("intent.preferredTimeStart") != "18:00" || r.Str("intent.specialInstruction") != "Inform the security guard" {
		t.Fatalf("intent: %s", r.Raw)
	}
	if r.Str("decision.outcome") != "AGENT_ALLOWED" || r.Str("case.state") != "REATTEMPT_SCHEDULED" || r.Str("case.language") != "en" || r.Str("case.languageSource") != "reply" {
		t.Fatalf("decision/state/language: %s", r.Raw)
	}
	checks := map[string]bool{}
	for i := 0; i < r.Len("decision.checks"); i++ {
		checks[r.Str(fmt.Sprintf("decision.checks.%d.rule", i))] = r.Bool(fmt.Sprintf("decision.checks.%d.passed", i))
	}
	for _, rule := range []string{"seller.allowed_action.REQUEST_REATTEMPT", "carrier.supported_action.REQUEST_REATTEMPT", "carrier.hold_window", "carrier.max_attempts", "carrier.instruction_cutoff"} {
		if !checks[rule] {
			t.Errorf("rule %s should have been checked and passed: %v", rule, checks)
		}
	}

	// ---- the product rule: the buyer is told "submitted" first and "accepted" only after the carrier accepted
	out := outbound(e, id)
	subIdx, accIdx := -1, -1
	for i, m := range out {
		if strings.Contains(m, "submitted your request") {
			subIdx = i
		}
		if strings.Contains(m, "The carrier has accepted the reattempt request for") {
			accIdx = i
		}
	}
	if subIdx < 0 || accIdx < 0 || subIdx > accIdx {
		t.Fatalf("expected submitted-then-accepted messages: %v", out)
	}
	ev := eventTypes(e, id)
	if !(indexOf(ev, "ACTION_SUBMITTED") < indexOf(ev, "CARRIER_ACCEPTED") && indexOf(ev, "CARRIER_ACCEPTED") < indexOf(ev, "REATTEMPT_SCHEDULED")) {
		t.Fatalf("timeline order: %v", ev)
	}
	// the message ordering vs carrier acceptance is also visible in event order: the 'accepted' message is the last BUYER_MESSAGE_SENT
	lastMsg := -1
	for i, x := range ev {
		if x == "BUYER_MESSAGE_SENT" {
			lastMsg = i
		}
	}
	if lastMsg < indexOf(ev, "CARRIER_ACCEPTED") {
		t.Fatalf("buyer was informed before carrier acceptance: %v", ev)
	}

	// carrier received a structured English remark, not the buyer's raw text
	var reqPayload string
	if err := e.App.Store.Pool().QueryRow(t.Context(), `SELECT request_payload::text FROM carrier_actions WHERE action_type='REQUEST_REATTEMPT'`).Scan(&reqPayload); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(reqPayload, "Inform the security guard") || !strings.Contains(reqPayload, istDate(1)) || strings.Contains(reqPayload, buyerText) {
		t.Fatalf("carrier request must carry the structured remark only: %s", reqPayload)
	}
	// original buyer text preserved verbatim
	var orig string
	_ = e.App.Store.Pool().QueryRow(t.Context(), `SELECT original_text FROM conversation_messages WHERE direction='INBOUND'`).Scan(&orig)
	if orig != buyerText {
		t.Fatalf("original text must never be overwritten: %q", orig)
	}
	if st := e.MockStats(); st["fastship.action.REATTEMPT"] != 1 {
		t.Fatalf("exactly one carrier call expected: %v", st)
	}

	// carrier sends the next delivery events
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	if state(e, id) != "REATTEMPT_SCHEDULED" {
		t.Fatal("OFD keeps the case scheduled")
	}
	e.MustTrigger(s, "DELIVERED", "")
	fin := e.Case(id)
	if fin.Str("case.state") != "CLOSED" || fin.Str("case.outcome") != "DELIVERED" || fin.Str("case.closedAt") == "" {
		t.Fatalf("delivery closes the case: %s", fin.Raw)
	}
	tr := e.Get("/api/orders/" + s.OrderID + "/tracking")
	if fmt.Sprint(history(e, s.OrderID)) != "[SHIPMENT_CREATED PICKED_UP IN_TRANSIT OUT_FOR_DELIVERY DELIVERY_FAILED OUT_FOR_DELIVERY DELIVERED]" || tr.Str("currentStatus") != "DELIVERED" {
		t.Fatalf("tracking history: %v", history(e, s.OrderID))
	}

	// audit chain
	au := e.Get("/api/audit-logs?caseId=" + id + "&limit=500")
	var actions []string
	for i := au.Len("logs") - 1; i >= 0; i-- {
		actions = append(actions, au.Str(fmt.Sprintf("logs.%d.action", i)))
	}
	order := []string{"NDR_CASE_OPENED", "BUYER_CONTACTED", "LANGUAGE_SWITCHED", "BUYER_RESPONDED", "INTENT_EXTRACTED", "RULES_CHECKED", "ACTION_SUBMITTED", "CARRIER_ACTION_ACCEPTED", "CARRIER_ACCEPTED", "REATTEMPT_SCHEDULED", "CASE_RESOLVED", "CASE_CLOSED"}
	last := -1
	for _, a := range order {
		i := indexOf(actions[last+1:], a)
		if i < 0 {
			t.Fatalf("audit chain is missing %s (after index %d): %v", a, last, actions)
		}
		last += i + 1
	}
	types := map[string]bool{}
	for i := 0; i < au.Len("logs"); i++ {
		types[au.Str(fmt.Sprintf("logs.%d.actorType", i))] = true
	}
	for _, ty := range []string{"AGENT", "BUYER", "CARRIER"} {
		if !types[ty] {
			t.Errorf("audit trail should contain %s actions: %v", ty, types)
		}
	}
	if au.At("logs.0.requestPayload") == nil && au.Len("logs") == 0 {
		t.Fatal("audit rows carry payloads")
	}
}

func TestCarrierRejectionIsNeverReportedToBuyerAsAcceptance(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("REJ", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	e.RejectActions(true)
	r := reply(e, id, "Please come tomorrow evening after 6")
	if r.Str("case.state") != "ESCALATED" {
		t.Fatalf("a rejected carrier action must escalate: %s", r.Raw)
	}
	out := outbound(e, id)
	if anyContains(out, "has accepted") {
		t.Fatalf("buyer was told the carrier accepted although it rejected: %v", out)
	}
	if !anyContains(out, "could not confirm") || fmt.Sprint(actionStatuses(e, id)) != "[REQUEST_REATTEMPT:REJECTED]" {
		t.Fatalf("buyer must be told honestly: %v %v", out, actionStatuses(e, id))
	}
	// recovery: carrier now accepts; retry uses a fresh idempotency key and succeeds
	e.RejectActions(false)
	p := process(e, id, "RETRY_ACTION")
	if p.Str("case.state") != "REATTEMPT_SCHEDULED" || fmt.Sprint(actionStatuses(e, id)) != "[REQUEST_REATTEMPT:REJECTED REQUEST_REATTEMPT:ACCEPTED]" {
		t.Fatalf("%s", p.Raw)
	}
	if n := countContains(outbound(e, id), "has accepted"); n != 1 {
		t.Fatalf("exactly one acceptance message expected, got %d", n)
	}
}

func countContains(list []string, sub string) int {
	n := 0
	for _, v := range list {
		if strings.Contains(v, sub) {
			n++
		}
	}
	return n
}

func TestCarrierOutageDuringActionEscalatesAfterRetries(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("OUT", "QUICKEXPRESS", "EXPRESS", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	e.SetFault("QUICKEXPRESS", "http500")
	r := reply(e, id, "come tomorrow morning")
	if r.Str("case.state") != "ESCALATED" || fmt.Sprint(actionStatuses(e, id)) != "[REQUEST_REATTEMPT:FAILED]" || anyContains(outbound(e, id), "has accepted") {
		t.Fatalf("%s %v", r.Raw, actionStatuses(e, id))
	}
	if st := e.MockStats(); st["quickexpress.action.REATTEMPT"] != 3 {
		t.Fatalf("transient failures retry 3 times with the same idempotency key: %v", st)
	}
	e.SetFault("QUICKEXPRESS", "")
	if p := process(e, id, "RETRY_ACTION"); p.Str("case.state") != "REATTEMPT_SCHEDULED" {
		t.Fatalf("%s", p.Raw)
	}
}

func TestUC2AddressCorrectionSamePincodeAgentApproved(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC2", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "ADDRESS_ISSUE")
	contact(e, id, nil)
	r := reply(e, id, "Flat 402, near Metro pillar 12, pincode 110001")
	if r.Str("intent.intent") != "ADDRESS_CORRECTION" || r.Str("decision.outcome") != "AGENT_ALLOWED" || r.Str("case.state") != "REATTEMPT_SCHEDULED" {
		t.Fatalf("%s", r.Raw)
	}
	if fmt.Sprint(actionStatuses(e, id)) != "[UPDATE_ADDRESS:ACCEPTED REQUEST_REATTEMPT:ACCEPTED]" {
		t.Fatalf("%v", actionStatuses(e, id))
	}
	o := e.Get("/api/orders/" + s.OrderID)
	if o.Str("deliveryAddress.addressLine2") != "Metro pillar 12" || o.Str("deliveryAddress.pincode") != "110001" || !strings.HasPrefix(o.Str("deliveryAddress.addressLine1"), "Flat 402") {
		t.Fatalf("address is mirrored only after carrier acceptance: %s", o.Raw)
	}
}

func TestAddressNewPincodeNeedsSellerApprovalAndShipmentIsUntouchedUntilApproved(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC2B", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "ADDRESS_ISSUE")
	contact(e, id, nil)
	r := reply(e, id, "Please deliver to my new address, flat 9 near City Mall, pincode 110002")
	if r.Str("decision.outcome") != "SELLER_APPROVAL" || r.Str("case.state") != "AWAITING_APPROVAL" {
		t.Fatalf("%s", r.Raw)
	}
	// nothing has reached the carrier or changed locally
	if st := e.MockStats(); st["fastship.action.UPDATE_ADDRESS"] != 0 || st["fastship.action.REATTEMPT"] != 0 {
		t.Fatalf("no carrier call may be made before approval: %v", st)
	}
	if o := e.Get("/api/orders/" + s.OrderID); o.Str("deliveryAddress.pincode") != "110001" {
		t.Fatal("order must not change before approval")
	}
	if !anyContains(outbound(e, id), "needs the seller's approval") || anyContains(outbound(e, id), "has accepted") {
		t.Fatalf("buyer is told the request awaits approval, with no false promise: %v", outbound(e, id))
	}
	pa := pendingApprovals(e, id)
	if pa.Len("approvals") != 1 || pa.Str("approvals.0.kind") != "ADDRESS_NEW_PINCODE" || !pa.Bool("approvals.0.blocking") || pa.Str("approvals.0.orderId") != s.OrderID ||
		pa.Str("approvals.0.trackingNumber") != s.Tracking || pa.Str("approvals.0.buyerRequest") == "" || pa.At("approvals.0.evidence.intent") == nil || pa.At("approvals.0.proposedAction.0.type") == nil {
		t.Fatalf("approval must show order, shipment, buyer request, proposed action, reason and evidence: %s", pa.Raw)
	}
	aid := pa.Str("approvals.0.id")
	// authorization
	if r := e.Post("/api/approvals/"+aid+"/approve", nil); r.Status != 403 {
		t.Fatalf("approving without a role must be forbidden: %d", r.Status)
	}
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Ops); r.Status != 403 {
		t.Fatalf("OPS is not an eligible approver for a seller-only approval: %d %s", r.Status, r.Raw)
	}
	if r := e.Post("/api/approvals/"+aid+"/approve", map[string]any{"note": "ok"}, testkit.Seller); r.Status != 200 || r.Str("status") != "APPROVED" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Seller); r.Status != 409 {
		t.Fatalf("a decided approval cannot be decided again: %d", r.Status)
	}
	if state(e, id) != "REATTEMPT_SCHEDULED" || fmt.Sprint(actionStatuses(e, id)) != "[UPDATE_ADDRESS:ACCEPTED REQUEST_REATTEMPT:ACCEPTED]" {
		t.Fatalf("%s %v", state(e, id), actionStatuses(e, id))
	}
	if o := e.Get("/api/orders/" + s.OrderID); o.Str("deliveryAddress.pincode") != "110002" {
		t.Fatalf("approved address change applies after carrier acceptance: %s", o.Raw)
	}
}

func TestApprovalRejectedNotifiesBuyerAndNeverTouchesCarrier(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC2C", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "ADDRESS_ISSUE")
	contact(e, id, nil)
	reply(e, id, "my address is flat 3, pincode 110005")
	aid := pendingApprovals(e, id).Str("approvals.0.id")
	r := e.Post("/api/approvals/"+aid+"/reject", map[string]any{"note": "address is outside our allowed zone"}, testkit.Seller)
	if r.Status != 200 || r.Str("status") != "REJECTED" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if state(e, id) != "BUYER_CONTACT_PENDING" || !anyContains(outbound(e, id), "couldn't approve") {
		t.Fatalf("rejection returns to the buyer conversation: %s %v", state(e, id), outbound(e, id))
	}
	if st := e.MockStats(); st["fastship.action.UPDATE_ADDRESS"] != 0 {
		t.Fatal("rejected approvals never reach the carrier")
	}
	if fmt.Sprint(actionStatuses(e, id)) != "[]" {
		t.Fatalf("%v", actionStatuses(e, id))
	}
}

func TestAddressNewCityNeedsSellerAndOpsApproval(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC2D", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "ADDRESS_ISSUE")
	contact(e, id, nil)
	r := reply(e, id, "I have moved to Mumbai, flat 5 near station, pincode 400001")
	if r.Str("decision.outcome") != "SELLER_OPS_APPROVAL" || r.Str("case.state") != "AWAITING_APPROVAL" {
		t.Fatalf("%s", r.Raw)
	}
	aid := pendingApprovals(e, id).Str("approvals.0.id")
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Seller); r.Status != 200 || r.Str("status") != "PENDING" || r.Len("grantedRoles") != 1 {
		t.Fatalf("seller alone must not complete a seller+ops approval: %s", r.Raw)
	}
	if state(e, id) != "AWAITING_APPROVAL" || e.MockStats()["fastship.action.UPDATE_ADDRESS"] != 0 {
		t.Fatal("still waiting for ops")
	}
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Seller); r.Status != 409 {
		t.Fatalf("same role cannot approve twice: %d", r.Status)
	}
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Ops); r.Status != 200 || r.Str("status") != "APPROVED" {
		t.Fatalf("%s", r.Raw)
	}
	if state(e, id) != "REATTEMPT_SCHEDULED" {
		t.Fatalf("%s", state(e, id))
	}
}

func TestUC3PhoneUnreachableAllChannelsFailSellerSuppliesAlternateNumber(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC3", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "9000000000", Language: "en"}) // reserved unreachable test number
	id := e.OpenNDR(s, "PHONE_UNREACHABLE")
	ct := contact(e, id, nil)
	if ct.Bool("delivered") || !ct.Bool("exhausted") || ct.Str("case.state") != "ESCALATED" || !ct.Bool("case.contactExhausted") {
		t.Fatalf("every channel failed: %s", ct.Raw)
	}
	cd := e.Case(id)
	if cd.Len("communicationAttempts") != 3 || cd.Str("communicationAttempts.0.channel") != "WHATSAPP" || cd.Str("communicationAttempts.1.channel") != "IVR" || cd.Str("communicationAttempts.2.channel") != "SMS" || cd.Str("communicationAttempts.0.status") != "FAILED" {
		t.Fatalf("channels are tried in priority order and recorded: %s", cd.Raw)
	}
	if !anyContains(eventTypes(e, id), "SELLER_ALERTED") {
		t.Fatalf("seller must be alerted: %v", eventTypes(e, id))
	}
	if r := e.Post("/api/ndr/cases/"+id+"/actions", map[string]any{"type": "UPDATE_PHONE", "phone": "9123456780"}); r.Status != 403 {
		t.Fatalf("manual actions require SELLER/OPS: %d", r.Status)
	}
	if r := e.Post("/api/ndr/cases/"+id+"/actions", map[string]any{"type": "UPDATE_PHONE", "phone": "123"}, testkit.Seller); r.Status != 422 || r.Str("error.code") != "ACTION_NOT_PERMITTED" {
		t.Fatalf("invalid number: %d %s", r.Status, r.Raw)
	}
	r := e.Post("/api/ndr/cases/"+id+"/actions", map[string]any{"type": "UPDATE_PHONE", "phone": "9123456780"}, testkit.Seller)
	if r.Status != 200 || r.Str("case.state") != "REATTEMPT_SCHEDULED" || fmt.Sprint(actionStatuses(e, id)) != "[UPDATE_PHONE:ACCEPTED REQUEST_REATTEMPT:ACCEPTED]" {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if o := e.Get("/api/orders/" + s.OrderID); o.Str("customer.phone") != "9123456780" {
		t.Fatalf("phone mirrored after carrier acceptance: %s", o.Raw)
	}
	cd = e.Case(id)
	n := cd.Len("messages")
	last := fmt.Sprintf("messages.%d.", n-1)
	if !strings.Contains(cd.Str(last+"originalText"), "accepted") || cd.Str(last+"deliveryStatus") == "FAILED" {
		t.Fatalf("the acceptance confirmation must reach the buyer on the NEW number: %s", cd.Raw)
	}
	prev := fmt.Sprintf("messages.%d.", n-2)
	if !strings.Contains(cd.Str(prev+"originalText"), "submitted") || cd.Str(prev+"deliveryStatus") != "FAILED" {
		t.Fatalf("the 'submitted' notice went to the old unreachable number and is recorded as failed: %s", cd.Raw)
	}
}

func TestSimulatedChannelFailuresFallBackInPriorityOrder(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("CH-1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	ct := contact(e, id, map[string]any{"simulateFailures": []string{"WHATSAPP"}})
	if !ct.Bool("delivered") || ct.Str("channel") != "IVR" {
		t.Fatalf("falls back to IVR: %s", ct.Raw)
	}
}

func TestUC4CODNotReadyPrepaidOfferAndConversion(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC4", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "COD_NOT_READY")
	contact(e, id, nil)
	r := reply(e, id, "I don't have cash right now")
	if r.Str("decision.outcome") != "OFFER_PREPAID" || r.Str("case.state") != "BUYER_CONTACT_PENDING" || !anyContains(outbound(e, id), "secure payment link") {
		t.Fatalf("%s", r.Raw)
	}
	r = reply(e, id, "yes")
	if r.Str("decision.outcome") != "SEND_PAYMENT_LINK" || !anyContains(outbound(e, id), "https://pay.zippyy.example/p/ndr-") {
		t.Fatalf("%s %v", r.Raw, outbound(e, id))
	}
	if e.MockStats()["fastship.action.CONVERT_PREPAID"] != 0 {
		t.Fatal("conversion must wait for payment")
	}
	r = reply(e, id, "paid")
	if r.Str("case.state") != "REATTEMPT_SCHEDULED" || fmt.Sprint(actionStatuses(e, id)) != "[CONVERT_TO_PREPAID:ACCEPTED REQUEST_REATTEMPT:ACCEPTED]" {
		t.Fatalf("%s %v", r.Raw, actionStatuses(e, id))
	}
	if o := e.Get("/api/orders/" + s.OrderID); o.Str("paymentType") != "PREPAID" || o.Num("codAmount") != 0 {
		t.Fatalf("order flips to prepaid after carrier acceptance: %s", o.Raw)
	}
}

func TestUC4CODNotReadyWithDateSchedulesReattemptAndSellerRuleCanDisablePrepaid(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC4B", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "COD_NOT_READY")
	contact(e, id, nil)
	if r := reply(e, id, "no cash today, come tomorrow"); r.Str("case.state") != "REATTEMPT_SCHEDULED" {
		t.Fatalf("%s", r.Raw)
	}
	// seller disables prepaid conversion -> agent asks for a date instead of offering a link
	rules := e.Get("/api/rules/seller").At("rules.0").(map[string]any)
	rules["prepaidConversionAllowed"] = false
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, testkit.Seller); r.Status != 200 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	s2 := e.NewShipment("UC4C", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "9876500011"})
	id2 := e.OpenNDR(s2, "COD_NOT_READY")
	contact(e, id2, nil)
	r := reply(e, id2, "I don't have cash right now")
	if r.Str("decision.outcome") != "CLARIFY" || anyContains(outbound(e, id2), "payment link") {
		t.Fatalf("seller rule must be honoured: %s", r.Raw)
	}
}

func TestUC5FalseAttemptClaimReattemptAndOpsDisputeDraft(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC5", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	r := reply(e, id, "Nobody came to my house, I was at home all day")
	if r.Str("intent.intent") != "FALSE_ATTEMPT_CLAIM" || r.Str("case.normalizedReason") != "SUSPECT_FALSE_ATTEMPT" || r.Str("case.state") != "REATTEMPT_SCHEDULED" {
		t.Fatalf("%s", r.Raw)
	}
	if !anyContains(eventTypes(e, id), "REASON_RECLASSIFIED") {
		t.Fatal("reclassification must be on the timeline")
	}
	pa := e.Get("/api/approvals?caseId=" + id)
	if pa.Len("approvals") != 1 || pa.Str("approvals.0.kind") != "DISPUTE_DRAFT" || pa.Bool("approvals.0.blocking") || pa.Str("approvals.0.status") != "PENDING" ||
		pa.At("approvals.0.evidence.disputeDraft.asks") == nil || pa.Str("approvals.0.evidence.buyerMessage") == "" || pa.At("approvals.0.evidence.attemptTime") == nil {
		t.Fatalf("dispute draft with evidence for ops: %s", pa.Raw)
	}
	for _, m := range outbound(e, id)[1:] {
		low := strings.ToLower(m)
		for _, banned := range []string{"false", "lied", "carrier's fault", "carrier is wrong", "did not attempt"} {
			if strings.Contains(low, banned) {
				t.Fatalf("buyer-facing text must never accuse the carrier: %q", m)
			}
		}
	}
	aid := pa.Str("approvals.0.id")
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Seller); r.Status != 403 {
		t.Fatalf("dispute drafts need OPS: %d", r.Status)
	}
	if r := e.Post("/api/approvals/"+aid+"/approve", nil, testkit.Ops); r.Status != 200 || r.Str("status") != "APPROVED" {
		t.Fatalf("%s", r.Raw)
	}
	if state(e, id) != "REATTEMPT_SCHEDULED" {
		t.Fatal("non-blocking dispute decisions must not disturb the reattempt")
	}
}

func TestUC6BuyerCancelsEarlyRTONeedsSellerApprovalThenRTOCloses(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC6", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_REFUSED")
	contact(e, id, nil)
	if r := reply(e, id, "I will refuse to accept it"); r.Str("decision.outcome") != "CLARIFY" || !anyContains(outbound(e, id), "why") {
		t.Fatalf("agent asks the reason first: %s", r.Raw)
	}
	r := reply(e, id, "I don't want it, please cancel the order")
	if r.Str("intent.intent") != "CANCEL_ORDER" || r.Str("decision.outcome") != "SELLER_APPROVAL" || r.Str("case.state") != "AWAITING_APPROVAL" {
		t.Fatalf("%s", r.Raw)
	}
	pa := pendingApprovals(e, id)
	if pa.Str("approvals.0.kind") != "EARLY_RTO" || e.MockStats()["fastship.action.RTO"] != 0 {
		t.Fatalf("no RTO before approval: %s", pa.Raw)
	}
	// case-level approve endpoint
	if r := e.Post("/api/ndr/cases/"+id+"/approve", map[string]any{"note": "approved"}, testkit.Seller); r.Status != 200 || r.Len("approvals") != 1 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	if state(e, id) != "RTO_INITIATED" || fmt.Sprint(actionStatuses(e, id)) != "[INITIATE_RTO:ACCEPTED]" || !anyContains(outbound(e, id), "accepted the return request") {
		t.Fatalf("%s %v", state(e, id), actionStatuses(e, id))
	}
	e.MustTrigger(s, "RTO", "")
	fin := e.Case(id)
	if fin.Str("case.state") != "CLOSED" || fin.Str("case.outcome") != "RTO" || e.Get("/api/orders/"+s.OrderID+"/tracking").Str("currentStatus") != "RTO" {
		t.Fatalf("%s", fin.Raw)
	}
}

func TestEarlyRTOPolicyAutoAndDisallowed(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	setPolicy := func(p string) {
		rules := e.Get("/api/rules/seller").At("rules.0").(map[string]any)
		rules["earlyRtoPolicy"] = p
		if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, testkit.Seller); r.Status != 200 {
			t.Fatalf("%d %s", r.Status, r.Raw)
		}
	}
	setPolicy("AUTO")
	s := e.NewShipment("RTO-A", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_REFUSED")
	contact(e, id, nil)
	if r := reply(e, id, "please cancel, I don't want it"); r.Str("case.state") != "RTO_INITIATED" || e.Count(`SELECT count(*) FROM approvals`) != 0 {
		t.Fatalf("AUTO policy lets the agent act: %s", r.Raw)
	}
	setPolicy("DISALLOWED")
	s2 := e.NewShipment("RTO-D", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "9876500022"})
	id2 := e.OpenNDR(s2, "CUST_REFUSED")
	contact(e, id2, nil)
	if r := reply(e, id2, "please cancel, I don't want it"); r.Str("decision.outcome") != "CLARIFY" || r.Str("case.state") != "BUYER_CONTACT_PENDING" || e.MockStats()["fastship.action.RTO"] != 1 {
		t.Fatalf("DISALLOWED policy: %s", r.Raw)
	}
}

func TestUC7RequestBeyondHoldWindowOffersNearestValidDate(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC7", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "FUTURE_DELIVERY")
	contact(e, id, nil)
	far := istDate(20)
	r := reply(e, id, "I am travelling, please deliver on "+far)
	if r.Str("decision.outcome") != "OFFER_ALTERNATIVE" || r.Str("case.state") != "BUYER_CONTACT_PENDING" {
		t.Fatalf("%s", r.Raw)
	}
	if st := e.MockStats(); st["fastship.action.REATTEMPT"] != 0 {
		t.Fatal("no carrier call while offering an alternative")
	}
	offered := istDate(7) // FastShip hold window is 7 days
	if !anyContains(outbound(e, id), "Reply YES") {
		t.Fatalf("%v", outbound(e, id))
	}
	_ = offered
	r = reply(e, id, "yes")
	if r.Str("case.state") != "REATTEMPT_SCHEDULED" {
		t.Fatalf("%s", r.Raw)
	}
	var date string
	_ = e.App.Store.Pool().QueryRow(t.Context(), `SELECT payload->>'date' FROM carrier_actions WHERE action_type='REQUEST_REATTEMPT'`).Scan(&date)
	if date != offered {
		t.Fatalf("accepted date should be the nearest valid date %s, got %s", offered, date)
	}
}

func TestUC7ForcedByCarrierRules(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	// ops tightens FastShip's hold window to 2 days
	rules := e.Get("/api/rules/carriers").At("rules.0").(map[string]any)
	for _, r := range e.Get("/api/rules/carriers").At("rules").([]any) {
		if r.(map[string]any)["carrierCode"] == "FASTSHIP" {
			rules = r.(map[string]any)
		}
	}
	rules["holdWindowDays"] = 2
	if r := e.Do("PUT", "/api/rules/carriers/FASTSHIP", rules, testkit.Seller); r.Status != 403 {
		t.Fatalf("only OPS may change carrier constraints: %d", r.Status)
	}
	if r := e.Do("PUT", "/api/rules/carriers/FASTSHIP", rules, testkit.Ops); r.Status != 200 {
		t.Fatalf("%d %s", r.Status, r.Raw)
	}
	s := e.NewShipment("UC7B", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "FUTURE_DELIVERY")
	contact(e, id, nil)
	r := reply(e, id, "deliver on "+istDate(5))
	if r.Str("decision.outcome") != "OFFER_ALTERNATIVE" {
		t.Fatalf("rules are read live from the database: %s", r.Raw)
	}
}

func TestUC8FinalAttemptNoResponseEscalatesChannelsThenDefaultRTO(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC8", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	e.ToOFD(s)
	e.MustTrigger(s, "NDR", "CUST_UNAVAILABLE")
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	e.MustTrigger(s, "NDR", "CUST_UNAVAILABLE")
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	e.MustTrigger(s, "NDR", "CUST_UNAVAILABLE")
	all := e.Get("/api/ndr/cases?orderId=" + s.OrderID)
	if all.Len("cases") != 3 {
		t.Fatalf("three attempts -> three cases: %s", all.Raw)
	}
	open := e.Get("/api/ndr/cases?orderId=" + s.OrderID + "&open=true")
	if open.Len("cases") != 1 || open.Num("cases.0.attemptNumber") != 3 {
		t.Fatalf("earlier cases are superseded, only the latest stays open: %s", open.Raw)
	}
	if e.Count(`SELECT count(*) FROM ndr_cases WHERE outcome='SUPERSEDED'`) != 2 {
		t.Fatal("superseded cases must be closed with that outcome")
	}
	id := open.Str("cases.0.id")
	contact(e, id, nil) // WhatsApp
	if p := process(e, id, "BUYER_TIMEOUT"); !strings.Contains(p.Str("summary"), "IVR") {
		t.Fatalf("escalate to IVR: %s", p.Raw)
	}
	if p := process(e, id, "BUYER_TIMEOUT"); !strings.Contains(p.Str("summary"), "SMS") {
		t.Fatalf("escalate to SMS: %s", p.Raw)
	}
	p := process(e, id, "BUYER_TIMEOUT")
	if p.Str("case.state") != "AWAITING_APPROVAL" {
		t.Fatalf("all channels exhausted on the final attempt -> seller decision: %s", p.Raw)
	}
	pa := pendingApprovals(e, id)
	if pa.Str("approvals.0.kind") != "FINAL_ATTEMPT_DECISION" || !anyContains(eventTypes(e, id), "SELLER_ALERT") {
		t.Fatalf("%s %v", pa.Raw, eventTypes(e, id))
	}
	if e.MockStats()["fastship.action.RTO"] != 0 {
		t.Fatal("RTO must wait for the seller or the timeout")
	}
	p = process(e, id, "SELLER_TIMEOUT")
	if p.Str("case.state") != "RTO_INITIATED" || fmt.Sprint(actionStatuses(e, id)) != "[INITIATE_RTO:ACCEPTED]" {
		t.Fatalf("default rule (RTO) applies when the seller stays silent: %s", p.Raw)
	}
	if ap := e.Get("/api/approvals?caseId=" + id); ap.Str("approvals.0.status") != "EXPIRED" || ap.Str("approvals.0.decidedBy") == "" {
		t.Fatalf("%s", ap.Raw)
	}
	e.MustTrigger(s, "RTO", "")
	if e.Case(id).Str("case.outcome") != "RTO" {
		t.Fatal("RTO event closes the case")
	}
}

func TestSellerSilenceWithEscalateDefault(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	rules := e.Get("/api/rules/seller").At("rules.0").(map[string]any)
	rules["defaultOnSilence"] = "ESCALATE"
	rules["maxAttempts"] = 1
	rules["autoRtoAttempt"] = 1
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, testkit.Seller); r.Status != 200 {
		t.Fatalf("%s", r.Raw)
	}
	s := e.NewShipment("UC8B", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	process(e, id, "BUYER_TIMEOUT")
	process(e, id, "BUYER_TIMEOUT")
	process(e, id, "BUYER_TIMEOUT")
	if state(e, id) != "AWAITING_APPROVAL" {
		t.Fatal(state(e, id))
	}
	if p := process(e, id, "SELLER_TIMEOUT"); p.Str("case.state") != "ESCALATED" || e.MockStats()["fastship.action.RTO"] != 0 {
		t.Fatalf("%s", p.Raw)
	}
}

func TestNoResponseOnNonFinalAttemptDefaultsToReattempt(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("NF-1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	process(e, id, "BUYER_TIMEOUT")
	process(e, id, "BUYER_TIMEOUT")
	p := process(e, id, "BUYER_TIMEOUT")
	if p.Str("case.state") != "REATTEMPT_SCHEDULED" || fmt.Sprint(actionStatuses(e, id)) != "[REQUEST_REATTEMPT:ACCEPTED]" {
		t.Fatalf("%s", p.Raw)
	}
}

func TestUC9LanguageSwitchKannadaToRomanizedHindi(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("UC9", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Language: "kn", Phone: "9811122233"})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	if c := e.Case(id); c.Str("case.language") != "kn" {
		t.Fatalf("%s", c.Raw)
	}
	contact(e, id, nil)
	const text = "kal subah 10 baje ke baad aana, gate pe guard ko bolna"
	r := reply(e, id, text)
	if r.Str("case.language") != "hi" || r.Str("case.languageSource") != "reply" || r.Str("intent.detectedLanguage") != "hi" {
		t.Fatalf("language must switch to Hindi: %s", r.Raw)
	}
	if r.Str("intent.intent") != "RESCHEDULE_DELIVERY" || r.Str("intent.preferredDate") != istDate(1) || r.Str("intent.preferredTimeStart") != "10:00" || !strings.Contains(r.Str("intent.specialInstruction"), "security guard") {
		t.Fatalf("romanized Hindi extraction: %s", r.Raw)
	}
	out := outbound(e, id)
	if !strings.Contains(out[len(out)-1], "कूरियर ने") || !strings.Contains(out[len(out)-2], "भेज दिया") {
		t.Fatalf("confirmations are in Hindi: %v", out)
	}
	if !anyContains(eventTypes(e, id), "LANGUAGE_SWITCHED") {
		t.Fatal("language switch is audited")
	}
	var remark, orig string
	_ = e.App.Store.Pool().QueryRow(t.Context(), `SELECT request_payload->'Action'->>'remark' FROM carrier_actions`).Scan(&remark)
	if !strings.Contains(remark, "Inform the security guard") || strings.Contains(remark, "baje") {
		t.Fatalf("carrier gets a structured English remark: %q", remark)
	}
	_ = e.App.Store.Pool().QueryRow(t.Context(), `SELECT original_text FROM conversation_messages WHERE direction='INBOUND'`).Scan(&orig)
	if orig != text {
		t.Fatalf("original text preserved: %q", orig)
	}
	// stored preference wins for the buyer's next case (priority: reply > stored > seller > pincode)
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	e.MustTrigger(s, "NDR", "CUST_UNAVAILABLE")
	next := e.Get("/api/ndr/cases?orderId=" + s.OrderID + "&open=true")
	if next.Str("cases.0.language") != "hi" || next.Str("cases.0.languageSource") != "stored" {
		t.Fatalf("%s", next.Raw)
	}
}

func TestLanguagePriorityPincodeDefaultAndSellerLanguage(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("LP-1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "9822200001", Pincode: "560001", City: "Bengaluru"})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	if c := e.Case(id); c.Str("case.language") != "kn" || c.Str("case.languageSource") != "pincode" {
		t.Fatalf("pincode default: %s", c.Raw)
	}
	s2 := e.NewShipment("LP-2", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "9822200002", Pincode: "600001", Language: "hi"})
	id2 := e.OpenNDR(s2, "CUST_UNAVAILABLE")
	if c := e.Case(id2); c.Str("case.language") != "hi" || c.Str("case.languageSource") != "seller" {
		t.Fatalf("seller language beats pincode: %s", c.Raw)
	}
	for lang, needle := range map[string]string{"te": "ఆర్డర్", "ta": "டெலிவரி", "kn": "ಆರ್ಡರ್", "hi": "ऑर्डर", "en": "order"} {
		s := e.NewShipment("LP-"+lang, "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "98222" + fmt.Sprint(10000+len(lang)*7+int(lang[0])), Language: lang})
		cid := e.OpenNDR(s, "CUST_UNAVAILABLE")
		contact(e, cid, nil)
		if !strings.Contains(outbound(e, cid)[0], needle) {
			t.Errorf("%s message missing %q: %q", lang, needle, outbound(e, cid)[0])
		}
	}
}

func TestLowConfidenceAsksForConfirmationAndDoesNotAct(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("LC", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	r := reply(e, id, "please come")
	if r.Str("decision.outcome") != "NEEDS_CONFIRMATION" || r.Str("case.state") != "BUYER_CONTACT_PENDING" || r.Num("intent.confidence") >= 0.75 {
		t.Fatalf("%s", r.Raw)
	}
	if e.MockStats()["fastship.action.REATTEMPT"] != 0 || e.Count(`SELECT count(*) FROM carrier_actions`) != 0 || !anyContains(outbound(e, id), "Reply YES") {
		t.Fatal("a low-confidence interpretation must never reach the carrier")
	}
	r = reply(e, id, "asdf qwerty")
	if r.Str("decision.outcome") != "CLARIFY" || e.Count(`SELECT count(*) FROM carrier_actions`) != 0 {
		t.Fatalf("%s", r.Raw)
	}
	r = reply(e, id, "please come")
	r = reply(e, id, "yes")
	if r.Str("case.state") != "REATTEMPT_SCHEDULED" || e.MockStats()["fastship.action.REATTEMPT"] != 1 {
		t.Fatalf("confirmation executes the confirmed intent: %s", r.Raw)
	}
	// "no" to a confirmation never acts either
	s2 := e.NewShipment("LC2", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{Phone: "9876500033"})
	id2 := e.OpenNDR(s2, "CUST_UNAVAILABLE")
	contact(e, id2, nil)
	reply(e, id2, "please come")
	if r := reply(e, id2, "no"); r.Str("decision.outcome") != "CLARIFY" || actionCountForCase(e, id2) != 0 {
		t.Fatalf("%s", r.Raw)
	}
}

func actionCountForCase(e *testkit.Env, id string) int {
	return e.Case(id).Len("carrierActions")
}

func TestCarrierRuleChecksReliableLimitations(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("RL-1", "RELIABLE", "RC-SURFACE", testkit.OrderOpts{})
	id := e.OpenNDR(s, "ADDRESS_ISSUE")
	contact(e, id, nil)
	r := reply(e, id, "Flat 402, near Metro pillar 12, pincode 110001")
	if r.Str("decision.outcome") != "ESCALATE" || r.Str("case.state") != "ESCALATED" || e.Count(`SELECT count(*) FROM carrier_actions`) != 0 {
		t.Fatalf("ReliableCourier cannot change addresses via API: %s", r.Raw)
	}
	if m := e.Post("/api/ndr/cases/"+id+"/actions", map[string]any{"type": "UPDATE_ADDRESS", "address": map[string]any{"addressLine1": "x", "city": "New Delhi", "pincode": "110001"}}, testkit.Seller); m.Status != 422 {
		t.Fatalf("manual actions cannot bypass carrier capability: %d %s", m.Status, m.Raw)
	}
	// no time-slot support: the preference goes in the remark as advisory only and the buyer is not promised a slot
	s2 := e.NewShipment("RL-2", "RELIABLE", "RC-SURFACE", testkit.OrderOpts{Phone: "9876500044"})
	id2 := e.OpenNDR(s2, "CUST_UNAVAILABLE")
	contact(e, id2, nil)
	reply(e, id2, "tomorrow after 6 pm")
	var remark string
	_ = e.App.Store.Pool().QueryRow(t.Context(), `SELECT payload->>'remark' FROM carrier_actions WHERE ndr_case_id=$1::uuid`, id2).Scan(&remark)
	if !strings.Contains(remark, "advisory") {
		t.Fatalf("%q", remark)
	}
	if anyContains(outbound(e, id2), "after 18:00") {
		t.Fatal("must not promise a time slot the carrier cannot honour")
	}
}

func TestCarrierMaxAttemptsEscalates(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("MA-1", "RELIABLE", "RC-SURFACE", testkit.OrderOpts{}) // Reliable allows 2 attempts
	e.ToOFD(s)
	e.MustTrigger(s, "NDR", "CUST_UNAVAILABLE")
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	e.MustTrigger(s, "NDR", "CUST_UNAVAILABLE")
	id := e.Get("/api/ndr/cases?orderId=" + s.OrderID + "&open=true").Str("cases.0.id")
	contact(e, id, nil)
	r := reply(e, id, "try again tomorrow")
	if r.Str("decision.outcome") != "ESCALATE" || r.Str("case.state") != "ESCALATED" || actionCountForCase(e, id) != 0 {
		t.Fatalf("carrier attempt cap is a hard stop: %s", r.Raw)
	}
}

func TestCommunicationHoursRuleDefersContact(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	rules := e.Get("/api/rules/seller").At("rules.0").(map[string]any)
	rules["enforceCommHours"] = true
	rules["commHoursStart"] = "00:00"
	rules["commHoursEnd"] = "00:01"
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, testkit.Seller); r.Status != 200 {
		t.Fatalf("%s", r.Raw)
	}
	s := e.NewShipment("CH-H", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	ct := contact(e, id, nil)
	if !ct.Bool("deferred") || e.Case(id).Len("messages") != 0 || e.Case(id).Str("communicationAttempts.0.status") != "DEFERRED" {
		t.Fatalf("contact outside communication hours is deferred, not sent: %s", ct.Raw)
	}
}

func TestInvalidCaseTransitionsAndGuards(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("GD", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	if r := e.Post("/api/ndr/cases/"+id+"/process", map[string]any{"trigger": "SELLER_TIMEOUT"}); r.Status != 409 {
		t.Fatalf("seller timeout only applies while awaiting approval: %d", r.Status)
	}
	if r := e.Post("/api/ndr/cases/"+id+"/process", map[string]any{"trigger": "NONSENSE"}); r.Status != 422 {
		t.Fatalf("%d", r.Status)
	}
	if r := e.Post("/api/ndr/cases/"+id+"/buyer-reply", map[string]any{"text": " "}); r.Status != 422 {
		t.Fatalf("%d", r.Status)
	}
	if r := e.Post("/api/ndr/cases/"+id+"/process", map[string]any{"trigger": "RETRY_ACTION"}); r.Status != 409 {
		t.Fatalf("nothing to retry: %d", r.Status)
	}
	if r := e.Get("/api/ndr/cases/NDR-99999"); r.Status != 404 {
		t.Fatalf("%d", r.Status)
	}
	if r := e.Get("/api/ndr/cases/not-a-uuid"); r.Status != 404 {
		t.Fatalf("%d", r.Status)
	}
	// reachable by human-readable case number too
	num := e.Case(id).Str("case.caseNumber")
	if r := e.Get("/api/ndr/cases/" + num); r.Status != 200 || r.Str("case.id") != id {
		t.Fatalf("%d %s", r.Status, num)
	}
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	e.MustTrigger(s, "DELIVERED", "")
	if r := e.Post("/api/ndr/cases/"+id+"/buyer-reply", map[string]any{"text": "hello"}); r.Status != 409 || r.Str("error.code") != "CASE_CLOSED" {
		t.Fatalf("closed cases are immutable: %d %s", r.Status, r.Raw)
	}
	if r := e.Post("/api/ndr/cases/"+id+"/contact", nil); r.Status != 409 {
		t.Fatalf("%d", r.Status)
	}
}

func TestSellerRulesAuthorizationAndValidation(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	rules := e.Get("/api/rules/seller").At("rules.0").(map[string]any)
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, nil); r.Status != 403 {
		t.Fatalf("%d", r.Status)
	}
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, testkit.Ops); r.Status != 403 {
		t.Fatalf("OPS cannot edit seller rules: %d", r.Status)
	}
	bad := map[string]any{}
	for k, v := range rules {
		bad[k] = v
	}
	bad["earlyRtoPolicy"] = "YOLO"
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", bad, testkit.Seller); r.Status != 422 {
		t.Fatalf("%d", r.Status)
	}
	bad["earlyRtoPolicy"], bad["allowedChannels"] = "AUTO", []string{"CARRIER_PIGEON"}
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", bad, testkit.Seller); r.Status != 422 {
		t.Fatalf("%d", r.Status)
	}
	if e.Count(`SELECT count(*) FROM audit_logs WHERE action='SELLER_RULES_UPDATED'`) != 0 {
		t.Fatal("failed updates are not audited as changes")
	}
	if r := e.Do("PUT", "/api/rules/seller/MRC-100", rules, testkit.Seller); r.Status != 200 || e.Count(`SELECT count(*) FROM audit_logs WHERE action='SELLER_RULES_UPDATED'`) != 1 {
		t.Fatalf("%d", r.Status)
	}
}

func TestDashboardReflectsRealState(t *testing.T) {
	e := testkit.New(t, testkit.Options{})
	s := e.NewShipment("DB-1", "FASTSHIP", "FAST-AIR", testkit.OrderOpts{})
	id := e.OpenNDR(s, "CUST_UNAVAILABLE")
	contact(e, id, nil)
	reply(e, id, "come tomorrow evening")
	e.MustTrigger(s, "OUT_FOR_DELIVERY", "")
	e.MustTrigger(s, "DELIVERED", "")
	s2 := e.NewShipment("DB-2", "QUICKEXPRESS", "EXPRESS", testkit.OrderOpts{Phone: "9876500055"})
	e.OpenNDR(s2, "ADDRESS_ISSUE")
	d := e.Get("/api/dashboard")
	if d.Num("orders") != 2 || d.Num("shipments") != 2 || d.Num("delivered") != 1 || d.Num("ndr") != 1 || d.Num("openNdrCases") != 1 || d.Num("totalNdrCases") != 2 || d.Num("recoveredCases") != 1 || d.Num("recoveryRate") != 1 {
		t.Fatalf("%s", d.Raw)
	}
	if d.Len("ndrByReason") != 2 || d.Len("ndrByCarrier") != 2 || d.Len("rtoTrend") != 7 || d.Len("languageResponse") == 0 {
		t.Fatalf("%s", d.Raw)
	}
}
