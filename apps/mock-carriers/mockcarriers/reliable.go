package mockcarriers

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/gofiber/fiber/v2"
)

func (s *Server) reliable(app *fiber.App) {
	app.Get("/reliablecourier/shipping-options", func(c *fiber.Ctx) error {
		s.count("reliable.options")
		s.latency()
		if s.applyFault(c, "RELIABLE") {
			return nil
		}
		from, to := c.Query("from"), c.Query("to")
		grams, _ := strconv.Atoi(c.Query("weight"))
		cod := strings.EqualFold(c.Query("cod"), "true")
		amount, _ := strconv.ParseFloat(c.Query("amount"), 64)
		if !pinOK(from) || !pinOK(to) || grams <= 0 {
			return badRequest(c, "from, to and weight are required")
		}
		kg := float64(grams) / 1000
		z := zoneFactor(from, to)
		cash := 0.0
		if cod {
			cash = round2(maxF(25, 0.012*amount))
		}
		option := func(id, name string, base, handling float64, eta string) fiber.Map {
			b := round2(base * z)
			if z == 1 {
				b = round2(base)
			}
			tax := round2(0.18 * (b + handling + cash))
			return fiber.Map{"id": id, "name": name, "eta": eta,
				"rate": fiber.Map{"base": b, "handling": handling, "cashCollectionFee": cash, "taxAmount": tax, "grandTotal": round2(b + handling + cash + tax)}}
		}
		return c.JSON(fiber.Map{"code": 200, "data": []fiber.Map{
			option("RC-SURFACE", "Reliable Surface", 50+30*kg, 10, "4-5 business days"),
			option("RC-AIR", "Reliable Air", 70+40*kg, 12, "2-3 business days"),
		}})
	})

	app.Put("/reliablecourier/orders", func(c *fiber.Ctx) error {
		s.count("reliable.orders")
		s.latency()
		if s.applyFault(c, "RELIABLE") {
			return nil
		}
		var in struct {
			Ref    string `json:"orderReference"`
			Option string `json:"selectedOption"`
			Dest   struct {
				Phone string `json:"phone"`
			} `json:"destination"`
			Callback string `json:"statusNotificationUrl"`
		}
		if err := c.BodyParser(&in); err != nil || in.Ref == "" || in.Option == "" || !phoneOK(in.Dest.Phone) {
			return badRequest(c, "orderReference, selectedOption and destination.phone are required")
		}
		id := fmt.Sprintf("RC-DO-%d", s.next("rc_do"))
		track := fmt.Sprintf("RC%d", s.next("rc_track"))
		s.register(&Shipment{Carrier: "RELIABLE", ShipmentID: id, Tracking: track, CallbackURL: in.Callback, Status: "10", CreatedAt: time.Now()})
		return c.JSON(fiber.Map{"result": "ACCEPTED", "deliveryOrder": fiber.Map{"id": id, "trackingCode": track}, "message": "Shipment successfully registered"})
	})

	app.Post("/reliablecourier/actions", func(c *fiber.Ctx) error {
		s.count("reliable.actions")
		s.latency()
		if s.applyFault(c, "RELIABLE") {
			return nil
		}
		var in struct {
			RequestKey string `json:"requestKey"`
			Tracking   string `json:"trackingCode"`
			Action     string `json:"action"`
			Params     struct {
				DeliveryDate string `json:"deliveryDate"`
				Phone        string `json:"phone"`
			} `json:"params"`
		}
		if err := c.BodyParser(&in); err != nil || in.Tracking == "" || in.RequestKey == "" {
			return badRequest(c, "requestKey and trackingCode are required")
		}
		kind := map[string]string{"REATTEMPT": "REATTEMPT", "RESCHEDULE": "RESCHEDULE", "CONTACT_CHANGE": "UPDATE_PHONE",
			"ADDRESS_CHANGE": "UPDATE_ADDRESS", "PAYMENT_CONVERSION": "CONVERT_PREPAID", "RETURN": "RTO"}[in.Action]
		if kind == "" {
			return badRequest(c, "unknown action")
		}
		st, ref, reason := s.decideAction("RELIABLE", in.RequestKey, in.Tracking, kind, in.Params.DeliveryDate, in.Params.Phone)
		decision := "APPROVED"
		if st == "REJECTED" {
			decision = "DENIED"
		}
		return c.JSON(fiber.Map{"code": 200, "data": fiber.Map{"decision": decision, "ref": ref, "reason": reason}})
	})
}
