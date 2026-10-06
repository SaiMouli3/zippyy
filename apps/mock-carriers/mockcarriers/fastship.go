package mockcarriers

import (
	"fmt"
	"strings"
	"time"

	"github.com/gofiber/fiber/v2"
)

func (s *Server) fastship(app *fiber.App) {
	g := app.Group("/fastship/api/v1")

	g.Post("/rate", func(c *fiber.Ctx) error {
		s.count("fastship.rate")
		s.latency()
		if s.applyFault(c, "FASTSHIP") {
			return nil
		}
		var in struct {
			OriginPin      string  `json:"origin_pin"`
			DestinationPin string  `json:"destination_pin"`
			WeightKg       float64 `json:"weight_kg"`
			PaymentMode    string  `json:"payment_mode"`
			InvoiceValue   float64 `json:"invoice_value"`
		}
		if err := c.BodyParser(&in); err != nil || !pinOK(in.OriginPin) || !pinOK(in.DestinationPin) || in.WeightKg <= 0 {
			return badRequest(c, "origin_pin, destination_pin and weight_kg are required")
		}
		freight := round2((60 + 40*in.WeightKg) * zoneFactor(in.OriginPin, in.DestinationPin))
		if zoneFactor(in.OriginPin, in.DestinationPin) == 1 {
			freight = round2(60 + 40*in.WeightKg)
		}
		cod := 0.0
		if strings.EqualFold(in.PaymentMode, "COD") {
			cod = round2(maxF(25, 0.014*in.InvoiceValue))
		}
		tax := round2(0.18 * (freight + cod))
		return c.JSON(fiber.Map{"success": true, "service": fiber.Map{
			"service_code": "FAST-AIR", "service_name": "FastShip Air Express",
			"freight_charge": freight, "cod_charge": cod, "tax": tax, "total_amount": round2(freight + cod + tax), "estimated_days": 2,
		}})
	})

	g.Post("/shipments", func(c *fiber.Ctx) error {
		s.count("fastship.shipments")
		s.latency()
		if s.applyFault(c, "FASTSHIP") {
			return nil
		}
		var in struct {
			Reference string `json:"reference_number"`
			Service   string `json:"service_code"`
			Consignee struct {
				Name   string `json:"name"`
				Phone  string `json:"phone"`
				Postal string `json:"postal_code"`
			} `json:"consignee"`
			Callback string `json:"callback_url"`
		}
		if err := c.BodyParser(&in); err != nil || in.Reference == "" || in.Service == "" || !phoneOK(in.Consignee.Phone) {
			return badRequest(c, "reference_number, service_code and consignee.phone are required")
		}
		id := fmtID("FS-", s.next("fs_ship"))
		track := fmt.Sprintf("FST%d", s.next("fs_track"))
		s.register(&Shipment{Carrier: "FASTSHIP", ShipmentID: id, Tracking: track, CallbackURL: in.Callback, Status: "BOOKED", CreatedAt: time.Now()})
		return c.JSON(fiber.Map{"success": true, "shipment_id": id, "tracking_number": track,
			"label_url": "http://mock-fastship/labels/" + track + ".pdf", "status": "BOOKED"})
	})

	act := func(kind string) fiber.Handler {
		return func(c *fiber.Ctx) error {
			s.count("fastship.action." + kind)
			s.latency()
			if s.applyFault(c, "FASTSHIP") {
				return nil
			}
			var in struct {
				RequestID string `json:"request_id"`
				Tracking  string `json:"tracking_number"`
				Date      string `json:"preferred_date"`
				NewPhone  string `json:"new_phone"`
				Remark    string `json:"remark"`
			}
			if err := c.BodyParser(&in); err != nil || in.Tracking == "" || in.RequestID == "" {
				return badRequest(c, "request_id and tracking_number are required")
			}
			st, ref, reason := s.decideAction("FASTSHIP", in.RequestID, in.Tracking, kind, in.Date, in.NewPhone)
			return c.JSON(fiber.Map{"success": st == "ACCEPTED", "action_status": st, "reference": ref, "reason": reason})
		}
	}
	g.Post("/actions/reattempt", act("REATTEMPT"))
	g.Post("/actions/reschedule", act("RESCHEDULE"))
	g.Post("/actions/update-phone", act("UPDATE_PHONE"))
	g.Post("/actions/update-address", act("UPDATE_ADDRESS"))
	g.Post("/actions/convert-prepaid", act("CONVERT_PREPAID"))
	g.Post("/actions/rto", act("RTO"))
}

func maxF(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

var carrierMaxAttempts = map[string]int{"FASTSHIP": 3, "QUICKEXPRESS": 3, "RELIABLE": 2}
var carrierHoldDays = map[string]int{"FASTSHIP": 7, "QUICKEXPRESS": 5, "RELIABLE": 4}

// decideAction is the carrier-side decision, shared by all three carriers' action endpoints. It is idempotent
// per request id so Zippy's retries never double-apply an instruction.
func (s *Server) decideAction(carrier, requestID, tracking, kind, date, phone string) (status, ref, reason string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := carrier + ":" + requestID
	if rec, ok := s.actionIDs[key]; ok {
		return rec.status, rec.ref, rec.reason
	}
	s.counters["act"]++
	ref = fmt.Sprintf("%s-ACT-%d", map[string]string{"FASTSHIP": "FS", "QUICKEXPRESS": "QE", "RELIABLE": "RC"}[carrier], 5000+s.counters["act"])
	status = "ACCEPTED"
	sh := s.shipments[tracking]
	switch {
	case s.rejectAll:
		status, reason = "REJECTED", "Action declined by carrier operations (simulated)"
	case sh != nil && (sh.Status == "DELIVERED" || sh.Status == "RTO"):
		status, reason = "REJECTED", "Shipment already closed at carrier"
	case (kind == "REATTEMPT" || kind == "RESCHEDULE") && sh != nil && sh.Attempts >= carrierMaxAttempts[carrier]:
		status, reason = "REJECTED", "Maximum delivery attempts reached"
	case (kind == "REATTEMPT" || kind == "RESCHEDULE") && date != "":
		d, err := time.Parse("2006-01-02", date)
		if err != nil {
			status, reason = "REJECTED", "Invalid date"
		} else if d.After(time.Now().AddDate(0, 0, carrierHoldDays[carrier]+1)) {
			status, reason = "REJECTED", "Requested date is beyond the carrier hold window"
		}
	case kind == "UPDATE_PHONE" && phone != "" && !phoneOK(phone):
		status, reason = "REJECTED", "Invalid phone number"
	}
	if status == "REJECTED" {
		ref = ""
	}
	if sh != nil {
		sh.Actions = append(sh.Actions, kind+":"+status)
	}
	s.actionIDs[key] = actionRecord{status, ref, reason}
	return
}
