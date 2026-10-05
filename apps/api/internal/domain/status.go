package domain

// ShipmentStatus is Zippy's normalized shipment lifecycle. Carrier codes never leave the adapters.
type ShipmentStatus string

const (
	StatusShipmentCreated ShipmentStatus = "SHIPMENT_CREATED"
	StatusPickedUp        ShipmentStatus = "PICKED_UP"
	StatusInTransit       ShipmentStatus = "IN_TRANSIT"
	StatusOutForDelivery  ShipmentStatus = "OUT_FOR_DELIVERY"
	StatusDelivered       ShipmentStatus = "DELIVERED"
	StatusDeliveryFailed  ShipmentStatus = "DELIVERY_FAILED"
	StatusRTO             ShipmentStatus = "RTO"
)

// Order statuses that precede a shipment. After a shipment exists the order mirrors shipment status.
const (
	OrderCreated         = "ORDER_CREATED"
	OrderRatesFetched    = "RATES_FETCHED"
	OrderCarrierSelected = "CARRIER_SELECTED"
)

func (s ShipmentStatus) Valid() bool {
	switch s {
	case StatusShipmentCreated, StatusPickedUp, StatusInTransit, StatusOutForDelivery, StatusDelivered, StatusDeliveryFailed, StatusRTO:
		return true
	}
	return false
}

func (s ShipmentStatus) String() string { return string(s) }

func (s ShipmentStatus) Terminal() bool { return s == StatusDelivered || s == StatusRTO }

// allowedTransitions is the complete, explicit transition table.
//
// Strategy (documented in docs/business-rules.md):
//   - Forward moves are accepted, including forward skips, because carriers drop intermediate events.
//   - A repeat of the current state with a new event id is accepted (no state change, history kept).
//   - Anything not listed is a regression and is REJECTED (HTTP 409): the raw event is stored as
//     disposition=REJECTED_TRANSITION for investigation but never touches shipment state or history.
//   - DELIVERED and RTO are terminal.
//   - DELIVERY_FAILED -> OUT_FOR_DELIVERY models a reattempt; DELIVERY_FAILED -> IN_TRANSIT models a hub return.
var allowedTransitions = map[ShipmentStatus][]ShipmentStatus{
	StatusShipmentCreated: {StatusPickedUp, StatusInTransit, StatusOutForDelivery, StatusDelivered, StatusDeliveryFailed, StatusRTO},
	StatusPickedUp:        {StatusInTransit, StatusOutForDelivery, StatusDelivered, StatusDeliveryFailed, StatusRTO},
	StatusInTransit:       {StatusOutForDelivery, StatusDelivered, StatusDeliveryFailed, StatusRTO},
	StatusOutForDelivery:  {StatusDelivered, StatusDeliveryFailed, StatusRTO},
	StatusDeliveryFailed:  {StatusOutForDelivery, StatusInTransit, StatusDelivered, StatusRTO},
	StatusDelivered:       {},
	StatusRTO:             {},
}

type TransitionResult int

const (
	TransitionApply TransitionResult = iota // state changes
	TransitionSame                          // same state, record history only
	TransitionReject
)

// CheckTransition decides what to do with an event moving from -> to.
func CheckTransition(from, to ShipmentStatus) TransitionResult {
	if from == to {
		if from.Terminal() {
			return TransitionReject
		}
		return TransitionSame
	}
	for _, a := range allowedTransitions[from] {
		if a == to {
			return TransitionApply
		}
	}
	return TransitionReject
}
