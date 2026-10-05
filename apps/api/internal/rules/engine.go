// Package rules is the deterministic NDR decision core. It consumes structured intent (never raw text)
// plus seller rules, carrier constraints and the clock, and returns what may happen next.
// Nothing in this package performs I/O or calls an LLM; the LLM can never override its output.
package rules

import (
	"fmt"
	"strings"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// IST is a fixed zone so behaviour does not depend on tzdata being installed in the container.
var IST = time.FixedZone("IST", 5*3600+1800)

type Outcome string

const (
	AgentAllowed      Outcome = "AGENT_ALLOWED"
	SellerApproval    Outcome = "SELLER_APPROVAL"
	SellerOpsApproval Outcome = "SELLER_OPS_APPROVAL"
	OpsApproval       Outcome = "OPS_APPROVAL"
	Escalate          Outcome = "ESCALATE"
	NeedsConfirmation Outcome = "NEEDS_CONFIRMATION"
	Clarify           Outcome = "CLARIFY"
	OfferAlternative  Outcome = "OFFER_ALTERNATIVE"
	OfferPrepaid      Outcome = "OFFER_PREPAID"
	SendPaymentLink   Outcome = "SEND_PAYMENT_LINK"
	NoAction          Outcome = "NO_ACTION"
)

// Check is one evaluated rule, recorded verbatim in the audit trail ("rules checked").
type Check struct {
	Rule   string `json:"rule"`
	Passed bool   `json:"passed"`
	Detail string `json:"detail"`
}

type ApprovalReq struct {
	Kind     string                 `json:"kind"`
	Roles    []string               `json:"roles"`
	Reason   string                 `json:"reason"`
	Blocking bool                   `json:"blocking"`
	Plan     []domain.PlannedAction `json:"plan"`
}

// Pending is what the agent is waiting on the buyer to answer.
type Pending struct {
	Type   string                  `json:"type"` // LOW_CONFIDENCE | DATE_OFFER | PREPAID_OFFER | PAYMENT_LINK_SENT
	Intent *domain.ExtractedIntent `json:"intent,omitempty"`
	Plan   []domain.PlannedAction  `json:"plan,omitempty"`
	Params map[string]string       `json:"params,omitempty"`
}

type Decision struct {
	Outcome        Outcome                `json:"outcome"`
	Plan           []domain.PlannedAction `json:"plan,omitempty"`
	Approvals      []ApprovalReq          `json:"approvals,omitempty"`
	Checks         []Check                `json:"checks"`
	Reason         string                 `json:"reason"`
	ActualAction   string                 `json:"actualAction,omitempty"`
	BuyerKey       string                 `json:"buyerKey,omitempty"`
	BuyerParams    map[string]string      `json:"buyerParams,omitempty"`
	Pending        *Pending               `json:"pending,omitempty"`
	ReasonOverride domain.NDRReason       `json:"reasonOverride,omitempty"`
}

type OrderFacts struct {
	PaymentType     domain.PaymentType
	CODAmount       float64
	DeliveryAddress domain.Address
	CustomerPhone   string
}

type Input struct {
	Reason                 domain.NDRReason
	Attempt                int
	Order                  OrderFacts
	Intent                 domain.ExtractedIntent
	Seller                 domain.SellerRules
	Carrier                domain.CarrierRules
	Now                    time.Time
	ConfidenceMin          float64
	Pending                *Pending
	PriorReattemptAccepted bool
}

// ---- helpers -----------------------------------------------------------------------------------

func dayStart(t time.Time) time.Time {
	t = t.In(IST)
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, IST)
}

func parseClock(s string) (int, int) {
	var h, m int
	fmt.Sscanf(s, "%d:%d", &h, &m)
	return h, m
}

// EarliestValidDate is the first day a carrier can act on an instruction given now and its daily cutoff.
func EarliestValidDate(now time.Time, c domain.CarrierRules) time.Time {
	n := now.In(IST)
	h, m := parseClock(c.InstructionCutoff)
	cutoff := time.Date(n.Year(), n.Month(), n.Day(), h, m, 0, 0, IST)
	d := dayStart(n).AddDate(0, 0, 1)
	if n.After(cutoff) {
		d = d.AddDate(0, 0, 1)
	}
	return d
}

// LatestValidDate is the end of the carrier's hold window.
func LatestValidDate(now time.Time, c domain.CarrierRules) time.Time {
	return dayStart(now).AddDate(0, 0, c.HoldWindowDays)
}

func IsFinalAttempt(attempt int, s domain.SellerRules, c domain.CarrierRules) bool {
	limit := min(s.MaxAttempts, c.MaxAttempts)
	if s.AutoRTOAttempt > 0 {
		limit = min(limit, s.AutoRTOAttempt)
	}
	return attempt >= limit
}

// CommAllowed applies the seller's communication-hours rule (only when enforcement is on).
func CommAllowed(s domain.SellerRules, now time.Time) (bool, string) {
	if !s.EnforceCommHours {
		return true, "communication hours not enforced"
	}
	n := now.In(IST)
	sh, sm := parseClock(s.CommHoursStart)
	eh, em := parseClock(s.CommHoursEnd)
	mins := n.Hour()*60 + n.Minute()
	ok := mins >= sh*60+sm && mins <= eh*60+em
	return ok, fmt.Sprintf("local time %s, allowed %s-%s", n.Format("15:04"), s.CommHoursStart, s.CommHoursEnd)
}

// ChannelOrder returns channels in priority order WhatsApp > IVR > SMS filtered by the seller's allow-list.
func ChannelOrder(s domain.SellerRules) []string {
	var out []string
	for _, ch := range []string{"WHATSAPP", "IVR", "SMS"} {
		for _, a := range s.AllowedChannels {
			if a == ch {
				out = append(out, ch)
				break
			}
		}
	}
	return out
}

// RecommendedAction is the default playbook step for a normalized NDR reason (shown in the UI at case open).
func RecommendedAction(r domain.NDRReason) string {
	switch r {
	case domain.ReasonCustUnavailable:
		return "REQUEST_REATTEMPT"
	case domain.ReasonCustRefused:
		return "ASK_REASON_THEN_EARLY_RTO_IF_CANCELLED"
	case domain.ReasonAddressIssue:
		return "COLLECT_ADDRESS_CORRECTION"
	case domain.ReasonPhoneUnreachable:
		return "TRY_ALTERNATE_CHANNELS_THEN_SELLER_ALTERNATE_NUMBER"
	case domain.ReasonCODNotReady:
		return "ASK_PAYMENT_READINESS_OFFER_PREPAID"
	case domain.ReasonFutureDelivery:
		return "CHECK_CARRIER_HOLD_WINDOW"
	case domain.ReasonAccessRestricted:
		return "ASK_BUYER_TO_INFORM_SECURITY"
	case domain.ReasonOutOfArea:
		return "ESCALATE_TO_CARRIER_OPS"
	case domain.ReasonSuspectFalse:
		return "RECORD_STATEMENT_COLLECT_EVIDENCE_DRAFT_DISPUTE"
	}
	return "ASK_BUYER"
}

func sameCity(a, b string) bool {
	norm := func(s string) string {
		s = strings.ToLower(strings.TrimSpace(s))
		switch s {
		case "new delhi", "delhi", "delhi ncr":
			return "delhi"
		case "bangalore", "bengaluru", "bengaluru urban":
			return "bengaluru"
		case "bombay", "mumbai":
			return "mumbai"
		case "madras", "chennai":
			return "chennai"
		case "calcutta", "kolkata":
			return "kolkata"
		}
		return s
	}
	return norm(a) == norm(b)
}

func strOr(p *string, d string) string {
	if p == nil {
		return d
	}
	return *p
}

func roleOutcome(roles []string) Outcome {
	hasS, hasO := false, false
	for _, r := range roles {
		hasS = hasS || r == domain.RoleSeller
		hasO = hasO || r == domain.RoleOps
	}
	switch {
	case hasS && hasO:
		return SellerOpsApproval
	case hasO:
		return OpsApproval
	}
	return SellerApproval
}

func unionRoles(reqs []ApprovalReq) []string {
	seen := map[string]bool{}
	var out []string
	for _, r := range reqs {
		for _, role := range r.Roles {
			if !seen[role] {
				seen[role] = true
				out = append(out, role)
			}
		}
	}
	return out
}

type eval struct {
	in       Input
	checks   []Check
	approval []ApprovalReq
	escalate string
}

func (e *eval) check(rule string, ok bool, detail string) bool {
	e.checks = append(e.checks, Check{Rule: rule, Passed: ok, Detail: detail})
	return ok
}

// ---- remark -------------------------------------------------------------------------------------

// BuildRemark creates the structured English remark carrier operations receive. It is assembled from
// structured fields only; the buyer's original text is never forwarded.
func BuildRemark(base string, in domain.ExtractedIntent, timeSupported bool) string {
	parts := []string{base}
	if in.PreferredTimeStart != nil || in.PreferredTimeEnd != nil {
		t := ""
		switch {
		case in.PreferredTimeStart != nil && in.PreferredTimeEnd != nil:
			t = fmt.Sprintf("between %s and %s", *in.PreferredTimeStart, *in.PreferredTimeEnd)
		case in.PreferredTimeStart != nil:
			t = "after " + *in.PreferredTimeStart
		default:
			t = "before " + *in.PreferredTimeEnd
		}
		if timeSupported {
			parts = append(parts, "Preferred time: "+t+".")
		} else {
			parts = append(parts, "Preferred time (advisory, no slot guarantee): "+t+".")
		}
	}
	if in.SpecialInstruction != nil && *in.SpecialInstruction != "" {
		parts = append(parts, "Instruction: "+*in.SpecialInstruction+".")
	}
	if in.Landmark != nil && *in.Landmark != "" {
		parts = append(parts, "Landmark: "+*in.Landmark+".")
	}
	return strings.Join(parts, " ")
}

// ---- main entry ---------------------------------------------------------------------------------

func Evaluate(in Input) Decision {
	if in.ConfidenceMin <= 0 {
		in.ConfidenceMin = 0.75
	}
	intent := in.Intent
	e := &eval{in: in}

	// Resolve a yes/no against what the agent previously asked the buyer.
	if intent.Intent == domain.IntentConfirmYes || intent.Intent == domain.IntentConfirmNo {
		if in.Pending == nil {
			e.check("confirmation.context", false, "buyer replied yes/no but nothing is awaiting confirmation")
			return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "no pending question to confirm"})
		}
		if intent.Intent == domain.IntentConfirmNo {
			e.check("confirmation.context", true, "buyer declined the proposal of type "+in.Pending.Type)
			return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.declined", Reason: "buyer declined the agent's proposal"})
		}
		switch in.Pending.Type {
		case "LOW_CONFIDENCE", "DATE_OFFER", "PREPAID_OFFER":
			if in.Pending.Intent != nil {
				confirmed := *in.Pending.Intent
				confirmed.Confidence = 1.0
				if in.Pending.Type == "PREPAID_OFFER" {
					confirmed.Intent = domain.IntentPayOnline
				}
				e.check("confirmation.context", true, "buyer confirmed the "+in.Pending.Type+" proposal")
				in.Intent, in.Pending = confirmed, nil
				e.in = in
				return e.dispatch(confirmed)
			}
		}
		e.check("confirmation.context", false, "pending state cannot be confirmed with yes")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "nothing to confirm"})
	}
	return e.dispatch(intent)
}

func (e *eval) dispatch(intent domain.ExtractedIntent) Decision {
	in := e.in
	switch intent.Intent {
	case domain.IntentUnknown:
		e.check("intent.recognised", false, "could not understand the buyer's message")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "intent unknown"})
	case domain.IntentNoAction:
		e.check("intent.recognised", true, "no action requested")
		return e.done(Decision{Outcome: NoAction, BuyerKey: "ack.thanks", Reason: "buyer asked for nothing"})
	case domain.IntentRefuseOrder:
		e.check("intent.recognised", true, "buyer refusing; reason must be clarified before any action")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "ask.reason", Reason: "refusal without a clear cancel request"})
	}
	// Low confidence NEVER acts: ask the buyer to confirm our interpretation.
	if intent.Confidence < in.ConfidenceMin {
		e.check("intent.confidence", false, fmt.Sprintf("confidence %.2f below threshold %.2f", intent.Confidence, in.ConfidenceMin))
		cp := intent
		return e.done(Decision{Outcome: NeedsConfirmation, BuyerKey: "clarify.confirm", BuyerParams: map[string]string{"summary": intent.InternalSummary},
			Pending: &Pending{Type: "LOW_CONFIDENCE", Intent: &cp}, Reason: "low-confidence intent requires buyer confirmation"})
	}
	e.check("intent.confidence", true, fmt.Sprintf("confidence %.2f >= %.2f", intent.Confidence, in.ConfidenceMin))

	switch intent.Intent {
	case domain.IntentReattempt, domain.IntentReschedule, domain.IntentRescheduleDelivery, domain.IntentCODReady:
		return e.dateFlow(intent, nil, "Buyer requested delivery reattempt.")
	case domain.IntentFalseAttempt:
		d := e.dateFlow(intent, nil, "Buyer states no delivery attempt was made at the address; please reattempt.")
		d.ReasonOverride = domain.ReasonSuspectFalse
		d.Approvals = append(d.Approvals, ApprovalReq{Kind: "DISPUTE_DRAFT", Roles: []string{domain.RoleOps}, Blocking: false,
			Reason: "Buyer reports no attempt was made. Agent drafted a carrier dispute with collected evidence for ops review."})
		e.check("false_attempt.dispute_draft", true, "dispute drafted for ops approval (non-blocking); buyer is not told the carrier is at fault")
		d.Checks = e.checks
		return d
	case domain.IntentAddressCorrection:
		return e.addressFlow(intent)
	case domain.IntentPhoneUpdate, domain.IntentAlternateContact:
		return e.phoneFlow(intent)
	case domain.IntentCODNotReady:
		return e.codNotReadyFlow(intent)
	case domain.IntentPayOnline:
		return e.payOnlineFlow(intent)
	case domain.IntentPaymentDone:
		return e.paymentDoneFlow(intent)
	case domain.IntentCancelOrder:
		return e.cancelFlow(intent)
	}
	e.check("intent.recognised", false, "unsupported intent "+string(intent.Intent))
	return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "unsupported intent"})
}

func (e *eval) done(d Decision) Decision {
	d.Checks = e.checks
	return d
}

// finish converts accumulated approvals into the final outcome for a plan.
func (e *eval) finish(plan []domain.PlannedAction, extra Decision) Decision {
	d := extra
	d.Plan = plan
	var types []string
	for _, a := range plan {
		types = append(types, string(a.Type))
	}
	d.ActualAction = strings.Join(types, "+")
	switch {
	case e.escalate != "":
		d.Outcome, d.Reason, d.Plan, d.BuyerKey = Escalate, e.escalate, nil, "escalated"
		d.Approvals = nil
	case len(e.approval) > 0:
		d.Approvals = e.approval
		d.Outcome = roleOutcome(unionRoles(e.approval))
		d.Reason = e.approval[0].Reason
		d.BuyerKey = "approval.pending"
		for i := range d.Approvals {
			d.Approvals[i].Plan = plan
		}
	default:
		if d.Outcome == "" {
			d.Outcome = AgentAllowed
		}
	}
	return e.done(d)
}

func (e *eval) require(a domain.ActionType) bool {
	okSeller := e.check("seller.allowed_action."+string(a), e.in.Seller.AllowsAction(a), fmt.Sprintf("seller rules allow %s", a))
	okCarrier := e.check("carrier.supported_action."+string(a), e.in.Carrier.Supports(a), fmt.Sprintf("carrier %s supports %s", e.in.Carrier.CarrierCode, a))
	if !okCarrier {
		e.escalate = fmt.Sprintf("carrier %s does not support %s through its API; ops must handle it manually", e.in.Carrier.CarrierCode, a)
	} else if !okSeller {
		e.approval = append(e.approval, ApprovalReq{Kind: "ACTION_NOT_PRE_AUTHORISED", Roles: []string{domain.RoleSeller}, Blocking: true,
			Reason: fmt.Sprintf("Seller rules do not pre-authorise %s; seller approval required.", a)})
	}
	return okSeller && okCarrier
}

// dateFlow plans a reattempt (optionally preceded by other actions) honouring attempts, COD limit, cutoff and hold window.
func (e *eval) dateFlow(intent domain.ExtractedIntent, prefix []domain.PlannedAction, remarkBase string) Decision {
	in := e.in
	action := domain.ActionReattempt
	if in.PriorReattemptAccepted {
		action = domain.ActionReschedule
	}
	e.require(action)

	// attempts
	if !e.check("carrier.max_attempts", in.Attempt < in.Carrier.MaxAttempts, fmt.Sprintf("attempt %d of carrier max %d", in.Attempt, in.Carrier.MaxAttempts)) && e.escalate == "" {
		e.escalate = fmt.Sprintf("carrier maximum of %d delivery attempts reached; ops must decide (RTO likely)", in.Carrier.MaxAttempts)
	}
	if !e.check("seller.max_attempts", in.Attempt < in.Seller.MaxAttempts, fmt.Sprintf("attempt %d of seller max %d", in.Attempt, in.Seller.MaxAttempts)) {
		e.approval = append(e.approval, ApprovalReq{Kind: "EXTRA_ATTEMPT", Roles: []string{domain.RoleSeller}, Blocking: true,
			Reason: fmt.Sprintf("Seller maximum of %d attempts reached; seller must approve an extra attempt.", in.Seller.MaxAttempts)})
	}
	// COD exposure
	if in.Order.PaymentType == domain.PaymentCOD && in.Seller.CODLimit > 0 {
		ok := !(in.Order.CODAmount > in.Seller.CODLimit && in.Attempt >= 2)
		if !e.check("seller.cod_limit", ok, fmt.Sprintf("COD %.2f vs limit %.2f at attempt %d", in.Order.CODAmount, in.Seller.CODLimit, in.Attempt)) {
			e.approval = append(e.approval, ApprovalReq{Kind: "HIGH_VALUE_COD_REATTEMPT", Roles: []string{domain.RoleSeller}, Blocking: true,
				Reason: fmt.Sprintf("COD amount %.2f exceeds the seller limit %.2f for repeat attempts.", in.Order.CODAmount, in.Seller.CODLimit)})
		}
	}

	// date resolution
	earliest := EarliestValidDate(in.Now, in.Carrier)
	latest := LatestValidDate(in.Now, in.Carrier)
	date := earliest
	requested := ""
	if intent.PreferredDate != nil {
		requested = *intent.PreferredDate
		d, err := time.ParseInLocation("2006-01-02", requested, IST)
		if err != nil {
			e.check("date.valid", false, "unparseable date "+requested)
			return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "invalid date"})
		}
		switch {
		case d.Before(dayStart(in.Now)):
			e.check("date.valid", false, "requested date is in the past")
			return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "date in the past"})
		case d.Before(earliest):
			e.check("carrier.instruction_cutoff", false, fmt.Sprintf("requested %s is before the earliest date the carrier can act on (%s) given cutoff %s", requested, earliest.Format("2006-01-02"), in.Carrier.InstructionCutoff))
			return e.offerDate(intent, prefix, earliest, requested, "cutoff")
		case d.After(latest):
			e.check("carrier.hold_window", false, fmt.Sprintf("requested %s is beyond the %d-day hold window (latest %s)", requested, in.Carrier.HoldWindowDays, latest.Format("2006-01-02")))
			return e.offerDate(intent, prefix, latest, requested, "hold_window")
		default:
			e.check("carrier.instruction_cutoff", true, fmt.Sprintf("earliest actionable date %s", earliest.Format("2006-01-02")))
			e.check("carrier.hold_window", true, fmt.Sprintf("%s within hold window ending %s", requested, latest.Format("2006-01-02")))
			date = d
		}
	} else {
		e.check("carrier.instruction_cutoff", true, fmt.Sprintf("no date requested; using earliest actionable date %s", earliest.Format("2006-01-02")))
	}

	act := domain.PlannedAction{Type: action, Date: date.Format("2006-01-02")}
	if in.Carrier.SupportsTimeSlot {
		act.TimeStart, act.TimeEnd = strOr(intent.PreferredTimeStart, ""), strOr(intent.PreferredTimeEnd, "")
	}
	if intent.PreferredTimeStart != nil || intent.PreferredTimeEnd != nil {
		e.check("carrier.time_slot", in.Carrier.SupportsTimeSlot, "carrier time-slot support; unsupported preferences are sent as an advisory remark only")
	}
	act.Remark = BuildRemark(remarkBase+fmt.Sprintf(" Delivery date: %s.", act.Date), intent, in.Carrier.SupportsTimeSlot)
	plan := append(append([]domain.PlannedAction{}, prefix...), act)
	params := map[string]string{"date": act.Date, "time": timeText(intent, in.Carrier.SupportsTimeSlot), "summary": Summarize(plan)}
	return e.finish(plan, Decision{BuyerParams: params})
}

func timeText(in domain.ExtractedIntent, supported bool) string {
	if !supported {
		return ""
	}
	switch {
	case in.PreferredTimeStart != nil && in.PreferredTimeEnd != nil:
		return *in.PreferredTimeStart + "-" + *in.PreferredTimeEnd
	case in.PreferredTimeStart != nil:
		return "after " + *in.PreferredTimeStart
	case in.PreferredTimeEnd != nil:
		return "before " + *in.PreferredTimeEnd
	}
	return ""
}

func Summarize(plan []domain.PlannedAction) string {
	var parts []string
	for _, a := range plan {
		switch a.Type {
		case domain.ActionReattempt, domain.ActionReschedule:
			parts = append(parts, "delivery reattempt on "+a.Date)
		case domain.ActionUpdatePhone:
			parts = append(parts, "contact number update")
		case domain.ActionUpdateAddress:
			parts = append(parts, "address correction")
		case domain.ActionConvertPrepaid:
			parts = append(parts, "switch to prepaid")
		case domain.ActionInitiateRTO:
			parts = append(parts, "return to seller")
		}
	}
	return strings.Join(parts, " + ")
}

func (e *eval) offerDate(intent domain.ExtractedIntent, prefix []domain.PlannedAction, offered time.Time, requested, why string) Decision {
	if e.escalate != "" {
		return e.finish(nil, Decision{})
	}
	cp := intent
	d := offered.Format("2006-01-02")
	cp.PreferredDate = &d
	return e.done(Decision{Outcome: OfferAlternative, BuyerKey: "offer.date_" + why, BuyerParams: map[string]string{"requested": requested, "date": d},
		Pending: &Pending{Type: "DATE_OFFER", Intent: &cp, Plan: prefix}, Reason: "requested date not possible: " + why})
}

func (e *eval) addressFlow(intent domain.ExtractedIntent) Decision {
	in := e.in
	cur := in.Order.DeliveryAddress
	if !e.check("seller.address_changes_allowed", in.Seller.AllowAddressChanges, "seller permits address changes") {
		e.approval = append(e.approval, ApprovalReq{Kind: "ADDRESS_CHANGE", Roles: []string{domain.RoleSeller}, Blocking: true, Reason: "Seller rules do not allow agent-driven address changes."})
	}
	if !e.check("carrier.can_change_address", in.Carrier.CanChangeAddress, "carrier accepts address changes by API") {
		e.escalate = fmt.Sprintf("carrier %s cannot change the address via API; ops must coordinate manually", in.Carrier.CarrierCode)
	}
	e.require(domain.ActionUpdateAddress)

	newAddr := cur
	if intent.NewAddressLine != nil && *intent.NewAddressLine != "" {
		newAddr.AddressLine1 = *intent.NewAddressLine
	}
	if intent.Landmark != nil && *intent.Landmark != "" {
		newAddr.AddressLine2 = *intent.Landmark
	}
	pinChanged := intent.NewPincode != nil && *intent.NewPincode != cur.Pincode
	cityChanged := intent.NewCity != nil && !sameCity(*intent.NewCity, cur.City)
	if intent.NewPincode != nil {
		newAddr.Pincode = *intent.NewPincode
	}
	if intent.NewCity != nil {
		newAddr.City = *intent.NewCity
	}
	switch {
	case cityChanged:
		e.check("address.scope", false, fmt.Sprintf("city changes from %s to %s", cur.City, *intent.NewCity))
		e.approval = append(e.approval, ApprovalReq{Kind: "ADDRESS_NEW_CITY", Roles: []string{domain.RoleSeller, domain.RoleOps}, Blocking: true,
			Reason: fmt.Sprintf("Buyer asks to move delivery to a different city (%s → %s): seller and ops approval required.", cur.City, *intent.NewCity)})
	case pinChanged:
		e.check("address.scope", false, fmt.Sprintf("pincode changes from %s to %s", cur.Pincode, *intent.NewPincode))
		e.approval = append(e.approval, ApprovalReq{Kind: "ADDRESS_NEW_PINCODE", Roles: []string{domain.RoleSeller}, Blocking: true,
			Reason: fmt.Sprintf("Buyer asks to change delivery pincode %s → %s: seller approval required.", cur.Pincode, *intent.NewPincode)})
	default:
		e.check("address.scope", true, "minor correction within the same pincode and city")
	}
	if intent.NewPincode != nil && !domain.ValidPincode(*intent.NewPincode) {
		e.check("address.pincode_valid", false, "new pincode is not valid")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.address", Reason: "invalid pincode"})
	}
	if intent.NewAddressLine == nil && intent.Landmark == nil && intent.NewPincode == nil {
		e.check("address.has_details", false, "no usable address detail extracted")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.address", Reason: "no address detail"})
	}
	upd := domain.PlannedAction{Type: domain.ActionUpdateAddress, Address: &newAddr, Landmark: strOr(intent.Landmark, ""),
		Remark: BuildRemark("Buyer provided a corrected delivery address.", domain.ExtractedIntent{Landmark: intent.Landmark, SpecialInstruction: intent.SpecialInstruction}, true)}
	d := e.dateFlow(intent, []domain.PlannedAction{upd}, "Delivery reattempt after address correction.")
	if d.Outcome == OfferAlternative || d.Outcome == Clarify {
		return d
	}
	return d
}

func (e *eval) phoneFlow(intent domain.ExtractedIntent) Decision {
	in := e.in
	if intent.NewPhone == nil || !domain.ValidPhone(*intent.NewPhone) {
		e.check("phone.valid", false, "no valid 10-digit phone number provided")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.phone", Reason: "phone missing or invalid"})
	}
	e.check("phone.valid", true, "valid phone number supplied")
	if !e.check("carrier.can_change_phone", in.Carrier.CanChangePhone, "carrier accepts contact updates by API") {
		e.escalate = fmt.Sprintf("carrier %s cannot update the contact number via API", in.Carrier.CarrierCode)
	}
	e.require(domain.ActionUpdatePhone)
	upd := domain.PlannedAction{Type: domain.ActionUpdatePhone, Phone: *intent.NewPhone, Remark: "Consignee contact number updated; please use the new number for the delivery call."}
	return e.dateFlow(intent, []domain.PlannedAction{upd}, "Delivery reattempt after contact number update.")
}

func (e *eval) codNotReadyFlow(intent domain.ExtractedIntent) Decision {
	in := e.in
	if intent.PreferredDate != nil {
		e.check("cod.buyer_chose_date", true, "buyer gave a date; scheduling reattempt when cash is ready")
		return e.dateFlow(intent, nil, "Consignee will have cash ready on the requested date.")
	}
	if in.Order.PaymentType == domain.PaymentCOD && e.prepaidPossible() {
		cp := intent
		cp.Intent = domain.IntentPayOnline
		cp.Confidence = 1
		return e.done(Decision{Outcome: OfferPrepaid, BuyerKey: "offer.prepaid", Pending: &Pending{Type: "PREPAID_OFFER", Intent: &cp},
			Reason: "COD not ready; seller allows prepaid conversion"})
	}
	e.check("prepaid.available", false, "prepaid conversion not available; asking when cash will be ready")
	return e.done(Decision{Outcome: Clarify, BuyerKey: "ask.cod_date", Reason: "COD not ready; no prepaid option"})
}

func (e *eval) prepaidPossible() bool {
	in := e.in
	a := e.check("seller.prepaid_conversion_allowed", in.Seller.PrepaidConversionAllowed, "seller allows COD → prepaid conversion")
	b := e.check("carrier.can_change_payment_mode", in.Carrier.CanChangePaymentMode && in.Carrier.Supports(domain.ActionConvertPrepaid), "carrier can switch payment mode")
	c := e.check("seller.allowed_action.CONVERT_TO_PREPAID", in.Seller.AllowsAction(domain.ActionConvertPrepaid), "CONVERT_TO_PREPAID is an allowed action")
	return a && b && c
}

func (e *eval) payOnlineFlow(intent domain.ExtractedIntent) Decision {
	if e.in.Order.PaymentType != domain.PaymentCOD {
		e.check("order.is_cod", false, "order is already prepaid")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "order not COD"})
	}
	if !e.prepaidPossible() {
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.prepaid_unavailable", Reason: "prepaid conversion not available"})
	}
	cp := intent
	return e.done(Decision{Outcome: SendPaymentLink, BuyerKey: "payment.link", Pending: &Pending{Type: "PAYMENT_LINK_SENT", Intent: &cp}, Reason: "buyer chose online payment"})
}

func (e *eval) paymentDoneFlow(intent domain.ExtractedIntent) Decision {
	if e.in.Pending == nil || e.in.Pending.Type != "PAYMENT_LINK_SENT" {
		e.check("payment.link_issued", false, "no payment link is awaiting payment for this case")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.unknown", Reason: "no payment pending"})
	}
	e.check("payment.link_issued", true, "payment link was issued and buyer reports payment (verified by mock gateway)")
	if !e.prepaidPossible() {
		return e.done(Decision{Outcome: Escalate, BuyerKey: "escalated", Reason: "prepaid conversion no longer possible"})
	}
	conv := domain.PlannedAction{Type: domain.ActionConvertPrepaid, Remark: "Payment received online. Convert shipment to PREPAID; do not collect cash on delivery."}
	return e.dateFlow(intent, []domain.PlannedAction{conv}, "Delivery reattempt after prepaid conversion.")
}

func (e *eval) cancelFlow(intent domain.ExtractedIntent) Decision {
	in := e.in
	supports := e.check("carrier.supported_action.INITIATE_RTO", in.Carrier.Supports(domain.ActionInitiateRTO), "carrier supports RTO instruction")
	allowed := e.check("seller.allowed_action.INITIATE_RTO", in.Seller.AllowsAction(domain.ActionInitiateRTO), "seller allows RTO action")
	plan := []domain.PlannedAction{{Type: domain.ActionInitiateRTO, Remark: "Buyer cancelled the order. Initiate return to origin."}}
	switch {
	case !supports:
		e.escalate = fmt.Sprintf("carrier %s does not support RTO instruction via API", in.Carrier.CarrierCode)
	case in.Seller.EarlyRTOPolicy == "DISALLOWED" || !allowed:
		e.check("seller.early_rto_policy", false, "seller does not allow early RTO")
		return e.done(Decision{Outcome: Clarify, BuyerKey: "clarify.rto_unavailable", Reason: "early RTO disallowed by seller"})
	case in.Seller.EarlyRTOPolicy == "APPROVAL":
		e.check("seller.early_rto_policy", false, "early RTO requires seller approval")
		e.approval = append(e.approval, ApprovalReq{Kind: "EARLY_RTO", Roles: []string{domain.RoleSeller}, Blocking: true,
			Reason: "Buyer has cancelled the order; seller approval needed to initiate early return (RTO)."})
	default:
		e.check("seller.early_rto_policy", true, "seller pre-authorises early RTO on buyer cancellation")
	}
	return e.finish(plan, Decision{BuyerParams: map[string]string{"summary": Summarize(plan)}})
}

// DefaultOnNoResponse decides what happens when the buyer never answers on any channel.
func DefaultOnNoResponse(in Input) Decision {
	e := &eval{in: in}
	if IsFinalAttempt(in.Attempt, in.Seller, in.Carrier) {
		e.check("attempts.final", true, fmt.Sprintf("attempt %d is the final allowed attempt", in.Attempt))
		plan := []domain.PlannedAction{{Type: domain.ActionInitiateRTO, Remark: "Final delivery attempt failed and consignee is unresponsive on all channels. Initiate return to origin per seller default rule."}}
		okCarrier := e.check("carrier.supported_action.INITIATE_RTO", in.Carrier.Supports(domain.ActionInitiateRTO), "carrier supports RTO")
		if !okCarrier {
			return e.done(Decision{Outcome: Escalate, BuyerKey: "escalated", Reason: "final attempt, buyer unresponsive, carrier cannot RTO via API"})
		}
		e.approval = append(e.approval, ApprovalReq{Kind: "FINAL_ATTEMPT_DECISION", Roles: []string{domain.RoleSeller}, Blocking: true, Plan: plan,
			Reason: fmt.Sprintf("Final attempt reached and the buyer did not respond on any channel. If the seller does not respond, the default rule (%s) applies.", in.Seller.DefaultOnSilence)})
		return e.finish(plan, Decision{})
	}
	e.check("attempts.final", false, "not the final attempt; default is a plain reattempt at the same address")
	synthetic := domain.ExtractedIntent{Intent: domain.IntentReattempt, Confidence: 1, InternalSummary: "reattempt (buyer unresponsive)"}
	e.in.Intent = synthetic
	return e.dateFlow(synthetic, nil, "Consignee could not be reached; reattempt at the same address.")
}

// RTOByDefault builds the carrier plan when the seller stays silent on a final-attempt decision.
func RTOByDefault(in Input) Decision {
	e := &eval{in: in}
	if in.Seller.DefaultOnSilence != "RTO" {
		e.check("seller.default_on_silence", false, "seller default is to escalate, not RTO")
		return e.done(Decision{Outcome: Escalate, BuyerKey: "escalated", Reason: "seller silent; default rule is escalation"})
	}
	e.check("seller.default_on_silence", true, "seller default on silence is RTO")
	if !e.check("carrier.supported_action.INITIATE_RTO", in.Carrier.Supports(domain.ActionInitiateRTO), "carrier supports RTO") {
		return e.done(Decision{Outcome: Escalate, BuyerKey: "escalated", Reason: "carrier cannot RTO via API"})
	}
	plan := []domain.PlannedAction{{Type: domain.ActionInitiateRTO, Remark: "Seller did not respond within the timeout; default rule applied: return to origin."}}
	return e.done(Decision{Outcome: AgentAllowed, Plan: plan, ActualAction: string(domain.ActionInitiateRTO), Reason: "seller silent; default RTO"})
}
