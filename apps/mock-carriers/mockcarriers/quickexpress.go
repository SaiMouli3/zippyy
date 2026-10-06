package mockcarriers

import (
	"fmt"
	"strings"
	"time"

	"github.com/gofiber/fiber/v2"
)

func (s *Server) quickexpress(app *fiber.App) {
	app.Post("/quickexpress/rates/check", func(c *fiber.Ctx) error {
		s.count("quickexpress.rates")
		s.latency()
		if s.applyFault(c, "QUICKEXPRESS") {
			return nil
		}
		var in struct {
			Pickup   string                                    `json:"pickupPincode"`
			Delivery string                                    `json:"deliveryPincode"`
			Grams    int                                       `json:"weightInGrams"`
			Dim      struct{ Length, Breadth, Height float64 } `json:"dimensions"`
			IsCod    bool                                      `json:"isCod"`
			Amount   float64                                   `json:"collectableAmount"`
		}
		if err := c.BodyParser(&in); err != nil || !pinOK(in.Pickup) || !pinOK(in.Delivery) || in.Grams <= 0 {
			return badRequest(c, "pickupPincode, deliveryPincode and weightInGrams are required")
		}
		kg := chargeableKg(in.Grams, in.Dim.Length, in.Dim.Breadth, in.Dim.Height)
		shipping := round2((55 + 40*kg) * zoneFactor(in.Pickup, in.Delivery))
		if zoneFactor(in.Pickup, in.Delivery) == 1 {
			shipping = round2(55 + 40*kg)
		}
		cod := 0.0
		if in.IsCod {
			cod = round2(maxF(30, 0.016*in.Amount))
		}
		fuel := round2(float64(int64(shipping*0.10 + 0.5)))
		gst := round2(0.18 * (shipping + cod + fuel))
		return c.JSON(fiber.Map{
			"status": "AVAILABLE", "quoteId": fmt.Sprintf("QE-Q-%d", s.next("qe_quote")),
			"charges":          fiber.Map{"shipping": shipping, "cod": cod, "fuelSurcharge": fuel, "gst": gst},
			"payable":          round2(shipping + cod + fuel + gst),
			"deliveryEstimate": fiber.Map{"minimumDays": 2, "maximumDays": 3}, "product": "EXPRESS",
		})
	})

	app.Post("/quickexpress/booking/create", func(c *fiber.Ctx) error {
		s.count("quickexpress.booking")
		s.latency()
		if s.applyFault(c, "QUICKEXPRESS") {
			return nil
		}
		var in struct {
			ClientOrderID string `json:"clientOrderId"`
			QuoteID       string `json:"quoteId"`
			Product       string `json:"productType"`
			Receiver      struct {
				MobileNumber string `json:"mobileNumber"`
			} `json:"receiverDetails"`
			Webhook string `json:"webhook"`
		}
		if err := c.BodyParser(&in); err != nil || in.ClientOrderID == "" || !strings.HasPrefix(in.QuoteID, "QE-Q-") || !phoneOK(in.Receiver.MobileNumber) {
			return badRequest(c, "clientOrderId, a valid quoteId and receiverDetails.mobileNumber are required")
		}
		id := fmt.Sprintf("QE-B-%d", s.next("qe_book"))
		awb := fmt.Sprintf("QE%d", s.next("qe_awb"))
		s.register(&Shipment{Carrier: "QUICKEXPRESS", ShipmentID: id, Tracking: awb, CallbackURL: in.Webhook, Status: "SC", CreatedAt: time.Now()})
		return c.JSON(fiber.Map{"bookingStatus": "CONFIRMED", "booking": fiber.Map{"bookingId": id, "awb": awb, "currentState": "SHIPMENT_CREATED"}})
	})

	act := func(kind string) fiber.Handler {
		return func(c *fiber.Ctx) error {
			s.count("quickexpress.action." + kind)
			s.latency()
			if s.applyFault(c, "QUICKEXPRESS") {
				return nil
			}
			var in struct {
				RequestID   string                  `json:"requestId"`
				AWB         string                  `json:"awb"`
				Instruction struct{ Date string }   `json:"instruction"`
				Contact     struct{ Mobile string } `json:"contact"`
			}
			if err := c.BodyParser(&in); err != nil || in.AWB == "" || in.RequestID == "" {
				return badRequest(c, "requestId and awb are required")
			}
			st, ref, reason := s.decideAction("QUICKEXPRESS", in.RequestID, in.AWB, kind, in.Instruction.Date, in.Contact.Mobile)
			state := st
			if st == "REJECTED" {
				state = "DECLINED"
			}
			return c.JSON(fiber.Map{"result": fiber.Map{"state": state, "ticket": ref, "message": reason}})
		}
	}
	app.Post("/quickexpress/actions/reattempt", act("REATTEMPT"))
	app.Post("/quickexpress/actions/reschedule", act("RESCHEDULE"))
	app.Post("/quickexpress/actions/contact-update", act("UPDATE_PHONE"))
	app.Post("/quickexpress/actions/address-update", act("UPDATE_ADDRESS"))
	app.Post("/quickexpress/actions/payment-mode", act("CONVERT_PREPAID"))
	app.Post("/quickexpress/actions/return", act("RTO"))
}
