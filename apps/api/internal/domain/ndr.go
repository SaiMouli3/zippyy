package domain

import "time"

// ---- NDR reasons -------------------------------------------------------------------------------

type NDRReason string

const (
	ReasonCustUnavailable  NDRReason = "CUST_UNAVAILABLE"
	ReasonCustRefused      NDRReason = "CUST_REFUSED"
	ReasonAddressIssue     NDRReason = "ADDRESS_ISSUE"
	ReasonPhoneUnreachable NDRReason = "PHONE_UNREACHABLE"
	ReasonCODNotReady      NDRReason = "COD_NOT_READY"
	ReasonFutureDelivery   NDRReason = "FUTURE_DELIVERY"
	ReasonAccessRestricted NDRReason = "ACCESS_RESTRICTED"
	ReasonOutOfArea        NDRReason = "OUT_OF_AREA"
	ReasonSuspectFalse     NDRReason = "SUSPECT_FALSE_ATTEMPT"
)

var AllNDRReasons = []NDRReason{
	ReasonCustUnavailable, ReasonCustRefused, ReasonAddressIssue, ReasonPhoneUnreachable, ReasonCODNotReady,
	ReasonFutureDelivery, ReasonAccessRestricted, ReasonOutOfArea, ReasonSuspectFalse,
}

func (r NDRReason) Valid() bool {
	for _, a := range AllNDRReasons {
		if a == r {
			return true
		}
	}
	return false
}

// ---- Case state machine ------------------------------------------------------------------------

type CaseState string

const (
	CaseOpened              CaseState = "OPENED"
	CaseBuyerContactPending CaseState = "BUYER_CONTACT_PENDING"
	CaseBuyerResponded      CaseState = "BUYER_RESPONDED"
	CaseIntentExtracted     CaseState = "INTENT_EXTRACTED"
	CaseAwaitingApproval    CaseState = "AWAITING_APPROVAL"
	CaseActionPending       CaseState = "ACTION_PENDING"
	CaseActionSubmitted     CaseState = "ACTION_SUBMITTED"
	CaseCarrierAccepted     CaseState = "CARRIER_ACCEPTED"
	CaseReattemptScheduled  CaseState = "REATTEMPT_SCHEDULED"
	CaseResolved            CaseState = "RESOLVED"
	CaseEscalated           CaseState = "ESCALATED"
	CaseRTOInitiated        CaseState = "RTO_INITIATED"
	CaseClosed              CaseState = "CLOSED"
)

// caseTransitions is owned by the deterministic core. Neither the LLM nor the UI can move a case
// outside this table; every state change goes through CanTransition.
var caseTransitions = map[CaseState][]CaseState{
	CaseOpened:              {CaseBuyerContactPending, CaseIntentExtracted, CaseActionPending, CaseAwaitingApproval, CaseEscalated, CaseClosed},
	CaseBuyerContactPending: {CaseBuyerResponded, CaseBuyerContactPending, CaseActionPending, CaseAwaitingApproval, CaseEscalated, CaseRTOInitiated, CaseClosed},
	CaseBuyerResponded:      {CaseIntentExtracted, CaseEscalated, CaseClosed},
	CaseIntentExtracted:     {CaseBuyerContactPending, CaseAwaitingApproval, CaseActionPending, CaseEscalated, CaseClosed},
	CaseAwaitingApproval:    {CaseActionPending, CaseBuyerContactPending, CaseEscalated, CaseClosed},
	CaseActionPending:       {CaseActionSubmitted, CaseEscalated, CaseClosed},
	CaseActionSubmitted:     {CaseCarrierAccepted, CaseEscalated, CaseClosed},
	CaseCarrierAccepted:     {CaseActionPending, CaseReattemptScheduled, CaseRTOInitiated, CaseBuyerContactPending, CaseResolved, CaseEscalated, CaseClosed},
	CaseReattemptScheduled:  {CaseBuyerContactPending, CaseActionPending, CaseResolved, CaseEscalated, CaseClosed},
	CaseResolved:            {CaseClosed},
	CaseEscalated:           {CaseBuyerContactPending, CaseActionPending, CaseRTOInitiated, CaseResolved, CaseClosed},
	CaseRTOInitiated:        {CaseResolved, CaseClosed},
	CaseClosed:              {},
}

func CanTransition(from, to CaseState) bool {
	for _, s := range caseTransitions[from] {
		if s == to {
			return true
		}
	}
	return false
}

func (s CaseState) Terminal() bool { return s == CaseClosed }

// Case outcomes recorded when a case closes.
const (
	OutcomeDelivered  = "DELIVERED"
	OutcomeRTO        = "RTO"
	OutcomeSuperseded = "SUPERSEDED"
	OutcomeEscalated  = "ESCALATED"
	OutcomeCancelled  = "CANCELLED"
)

// ---- Buyer intent -------------------------------------------------------------------------------

type IntentType string

const (
	IntentReattempt          IntentType = "REATTEMPT"
	IntentReschedule         IntentType = "RESCHEDULE"
	IntentRescheduleDelivery IntentType = "RESCHEDULE_DELIVERY"
	IntentAddressCorrection  IntentType = "ADDRESS_CORRECTION"
	IntentPhoneUpdate        IntentType = "PHONE_UPDATE"
	IntentRefuseOrder        IntentType = "REFUSE_ORDER"
	IntentCancelOrder        IntentType = "CANCEL_ORDER"
	IntentCODReady           IntentType = "COD_READY"
	IntentCODNotReady        IntentType = "COD_NOT_READY"
	IntentAlternateContact   IntentType = "ALTERNATE_CONTACT"
	IntentFalseAttempt       IntentType = "FALSE_ATTEMPT_CLAIM"
	IntentPayOnline          IntentType = "PAY_ONLINE"
	IntentPaymentDone        IntentType = "PAYMENT_DONE"
	IntentConfirmYes         IntentType = "CONFIRM_YES"
	IntentConfirmNo          IntentType = "CONFIRM_NO"
	IntentNoAction           IntentType = "NO_ACTION"
	IntentUnknown            IntentType = "UNKNOWN"
)

// ExtractedIntent is the ONLY thing the language layer hands to the deterministic core.
type ExtractedIntent struct {
	Intent             IntentType `json:"intent"`
	PreferredDate      *string    `json:"preferredDate"`      // YYYY-MM-DD
	PreferredTimeStart *string    `json:"preferredTimeStart"` // HH:MM
	PreferredTimeEnd   *string    `json:"preferredTimeEnd"`
	Landmark           *string    `json:"landmark"`
	SpecialInstruction *string    `json:"specialInstruction"`
	NewPincode         *string    `json:"newPincode,omitempty"`
	NewCity            *string    `json:"newCity,omitempty"`
	NewAddressLine     *string    `json:"newAddressLine,omitempty"`
	NewPhone           *string    `json:"newPhone,omitempty"`
	Confidence         float64    `json:"confidence"`
	DetectedLanguage   string     `json:"detectedLanguage"`
	LanguageConfidence float64    `json:"languageConfidence"`
	InternalSummary    string     `json:"internalSummary"` // English rendering for operators
}

// ---- Carrier actions ----------------------------------------------------------------------------

type ActionType string

const (
	ActionReattempt      ActionType = "REQUEST_REATTEMPT"
	ActionReschedule     ActionType = "RESCHEDULE"
	ActionUpdatePhone    ActionType = "UPDATE_PHONE"
	ActionUpdateAddress  ActionType = "UPDATE_ADDRESS"
	ActionConvertPrepaid ActionType = "CONVERT_TO_PREPAID"
	ActionInitiateRTO    ActionType = "INITIATE_RTO"
)

var AllActionTypes = []ActionType{ActionReattempt, ActionReschedule, ActionUpdatePhone, ActionUpdateAddress, ActionConvertPrepaid, ActionInitiateRTO}

func (a ActionType) Valid() bool {
	for _, x := range AllActionTypes {
		if x == a {
			return true
		}
	}
	return false
}

// PlannedAction is a deterministic instruction destined for a carrier.
type PlannedAction struct {
	Type            ActionType `json:"type"`
	Date            string     `json:"date,omitempty"`      // YYYY-MM-DD
	TimeStart       string     `json:"timeStart,omitempty"` // HH:MM
	TimeEnd         string     `json:"timeEnd,omitempty"`
	Phone           string     `json:"phone,omitempty"`
	Address         *Address   `json:"address,omitempty"`
	Landmark        string     `json:"landmark,omitempty"`
	Remark          string     `json:"remark,omitempty"` // structured English remark sent to the carrier
	AmountToCollect *float64   `json:"amountToCollect,omitempty"`
}

type ActionStatus string

const (
	ActionPending  ActionStatus = "PENDING"
	ActionAccepted ActionStatus = "ACCEPTED"
	ActionRejected ActionStatus = "REJECTED"
	ActionFailed   ActionStatus = "FAILED"
)

type CarrierActionResult struct {
	Status    ActionStatus `json:"status"`
	Reference string       `json:"reference,omitempty"`
	Reason    string       `json:"reason,omitempty"`
	Request   []byte       `json:"-"`
	Response  []byte       `json:"-"`
}

// ---- Rules --------------------------------------------------------------------------------------

type SellerRules struct {
	MerchantID                   string    `json:"merchantId"`
	MaxAttempts                  int       `json:"maxAttempts"`
	AutoRTOAttempt               int       `json:"autoRtoAttempt"`
	CODLimit                     float64   `json:"codLimit"`
	AllowedChannels              []string  `json:"allowedChannels"`
	CommHoursStart               string    `json:"commHoursStart"`
	CommHoursEnd                 string    `json:"commHoursEnd"`
	EnforceCommHours             bool      `json:"enforceCommHours"`
	PrepaidConversionAllowed     bool      `json:"prepaidConversionAllowed"`
	AllowAddressChanges          bool      `json:"allowAddressChanges"`
	EarlyRTOPolicy               string    `json:"earlyRtoPolicy"` // AUTO | APPROVAL | DISALLOWED
	AllowedActions               []string  `json:"allowedActions"`
	DefaultOnSilence             string    `json:"defaultOnSilence"` // RTO | ESCALATE
	BuyerResponseTimeoutMinutes  int       `json:"buyerResponseTimeoutMinutes"`
	SellerResponseTimeoutMinutes int       `json:"sellerResponseTimeoutMinutes"`
	UpdatedAt                    time.Time `json:"updatedAt"`
}

func (r SellerRules) AllowsAction(a ActionType) bool {
	for _, x := range r.AllowedActions {
		if x == string(a) {
			return true
		}
	}
	return false
}

type CarrierRules struct {
	CarrierCode          string    `json:"carrierCode"`
	MaxAttempts          int       `json:"maxAttempts"`
	InstructionCutoff    string    `json:"instructionCutoff"`
	HoldWindowDays       int       `json:"holdWindowDays"`
	SupportedActions     []string  `json:"supportedActions"`
	SupportsTimeSlot     bool      `json:"supportsTimeSlot"`
	CanChangePaymentMode bool      `json:"canChangePaymentMode"`
	CanChangeAddress     bool      `json:"canChangeAddress"`
	CanChangePhone       bool      `json:"canChangePhone"`
	UpdatedAt            time.Time `json:"updatedAt"`
}

func (r CarrierRules) Supports(a ActionType) bool {
	for _, x := range r.SupportedActions {
		if x == string(a) {
			return true
		}
	}
	return false
}

// Approval roles.
const (
	RoleSeller = "SELLER"
	RoleOps    = "OPS"
)

// Actor types for audit logging.
const (
	ActorAgent   = "AGENT"
	ActorSeller  = "SELLER"
	ActorOps     = "OPS"
	ActorCarrier = "CARRIER"
	ActorSystem  = "SYSTEM"
	ActorBuyer   = "BUYER"
)
