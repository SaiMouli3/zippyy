package mockcarriers

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/gofiber/fiber/v2"
)

// NDR scenarios use Zippy-neutral names; each carrier translates them into its own reason codes.
var ndrCatalog = map[string]struct{ fast, quick, reliable, remark string }{
	"CUST_UNAVAILABLE":      {"CONSIGNEE_UNAVAILABLE", "NDR-01", "R-11", "Consignee not available at address, door locked"},
	"CUST_REFUSED":          {"CONSIGNEE_REFUSED", "NDR-02", "R-12", "Consignee refused to accept the shipment"},
	"ADDRESS_ISSUE":         {"ADDRESS_INCOMPLETE", "NDR-03", "R-13", "Address incomplete, landmark missing"},
	"PHONE_UNREACHABLE":     {"PHONE_NOT_REACHABLE", "NDR-04", "R-14", "Consignee phone switched off / not reachable"},
	"COD_NOT_READY":         {"COD_NOT_READY", "NDR-05", "R-15", "Consignee does not have cash ready"},
	"FUTURE_DELIVERY":       {"FUTURE_DELIVERY_REQUESTED", "NDR-06", "R-16", "Consignee requested delivery on a future date"},
	"ACCESS_RESTRICTED":     {"ACCESS_DENIED", "NDR-07", "R-17", "Society security did not allow entry"},
	"OUT_OF_AREA":           {"OUT_OF_DELIVERY_AREA", "NDR-08", "R-18", "Address outside serviceable delivery area"},
	"SUSPECT_FALSE_ATTEMPT": {"ATTEMPT_ANOMALY", "NDR-09", "R-19", "Attempt location mismatch flagged"},
	"OTHER":                 {"OTHER", "NDR-99", "R-99", "Customer not available as per delivery executive"},
}

type triggerRequest struct {
	Carrier           string `json:"carrier"`
	TrackingNumber    string `json:"trackingNumber"`
	CarrierShipmentID string `json:"carrierShipmentId"`
	Event             string `json:"event"`
	NDRReason         string `json:"ndrReason"`
	Remark            string `json:"remark"`
	CallbackBase      string `json:"callbackBase"`
	Duplicates        int    `json:"duplicates"`
}

type delivery struct {
	URL    string          `json:"url"`
	Status int             `json:"status"`
	Body   json.RawMessage `json:"body,omitempty"`
	Error  string          `json:"error,omitempty"`
}

var eventText = map[string]string{
	"PICKED_UP": "Shipment picked up from merchant", "IN_TRANSIT": "Shipment departed origin hub",
	"OUT_FOR_DELIVERY": "Shipment is out for delivery", "DELIVERED": "Shipment delivered to consignee",
	"NDR": "Delivery attempt failed", "RTO": "Shipment returned to origin",
}

func (s *Server) control(app *fiber.App) {
	g := app.Group("/control")

	g.Post("/trigger", func(c *fiber.Ctx) error {
		var in triggerRequest
		if err := c.BodyParser(&in); err != nil {
			return badRequest(c, "invalid body")
		}
		in.Event = strings.ToUpper(in.Event)
		if _, ok := eventText[in.Event]; !ok {
			return badRequest(c, "event must be one of PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, NDR, RTO")
		}
		carrier := strings.ToUpper(in.Carrier)
		if carrier != "FASTSHIP" && carrier != "QUICKEXPRESS" && carrier != "RELIABLE" {
			return badRequest(c, "unknown carrier")
		}
		if in.TrackingNumber == "" {
			return badRequest(c, "trackingNumber is required")
		}
		reason := strings.ToUpper(in.NDRReason)
		if in.Event == "NDR" {
			if reason == "" {
				reason = "CUST_UNAVAILABLE"
			}
			if _, ok := ndrCatalog[reason]; !ok {
				return badRequest(c, "unknown ndrReason")
			}
		}

		s.mu.Lock()
		sh := s.shipments[in.TrackingNumber]
		if sh == nil { // carrier restarted or shipment created elsewhere: rebuild a minimal record from the caller's context
			sh = &Shipment{Carrier: carrier, Tracking: in.TrackingNumber, ShipmentID: in.CarrierShipmentID, CreatedAt: time.Now()}
			s.shipments[in.TrackingNumber] = sh
		}
		if in.Event == "NDR" {
			sh.Attempts++
		}
		sh.Status = in.Event
		cb := sh.CallbackURL
		s.mu.Unlock()
		if in.CallbackBase != "" {
			cb = strings.TrimRight(in.CallbackBase, "/") + webhookPath(carrier)
		}
		if cb == "" {
			cb = strings.TrimRight(s.cfg.ZippyWebhookBase, "/") + webhookPath(carrier)
		}

		now := time.Now().UTC()
		payload, err := buildWebhook(carrier, sh, in, reason, now)
		if err != nil {
			return badRequest(c, err.Error())
		}
		var out []delivery
		for i := 0; i <= in.Duplicates && i < 10; i++ {
			out = append(out, s.deliver(carrier, cb, payload))
		}
		return c.JSON(fiber.Map{"carrier": carrier, "trackingNumber": in.TrackingNumber, "event": in.Event, "payload": json.RawMessage(payload), "deliveries": out})
	})

	g.Get("/shipments", func(c *fiber.Ctx) error {
		s.mu.Lock()
		defer s.mu.Unlock()
		list := make([]*Shipment, 0, len(s.shipments))
		for _, sh := range s.shipments {
			list = append(list, sh)
		}
		sort.Slice(list, func(i, j int) bool { return list[i].CreatedAt.After(list[j].CreatedAt) })
		return c.JSON(list)
	})

	g.Get("/stats", func(c *fiber.Ctx) error {
		s.mu.Lock()
		defer s.mu.Unlock()
		cp := map[string]int{}
		for k, v := range s.calls {
			cp[k] = v
		}
		return c.JSON(fiber.Map{"calls": cp, "faults": s.faults, "rejectActions": s.rejectAll})
	})

	g.Post("/reset-stats", func(c *fiber.Ctx) error {
		s.mu.Lock()
		s.calls = map[string]int{}
		s.mu.Unlock()
		return c.SendStatus(204)
	})

	// Fault injection: {"carrier":"QUICKEXPRESS","fault":"timeout"} ; rejectActions toggles carrier action refusal.
	g.Post("/config", func(c *fiber.Ctx) error {
		var in struct {
			Carrier       string `json:"carrier"`
			Fault         string `json:"fault"`
			RejectActions *bool  `json:"rejectActions"`
		}
		if err := c.BodyParser(&in); err != nil {
			return badRequest(c, "invalid body")
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		if in.Carrier != "" {
			switch in.Fault {
			case "", "http500", "timeout", "malformed", "unavailable":
				if in.Fault == "" {
					delete(s.faults, strings.ToUpper(in.Carrier))
				} else {
					s.faults[strings.ToUpper(in.Carrier)] = in.Fault
				}
			default:
				return badRequest(c, "fault must be one of '', http500, timeout, malformed, unavailable")
			}
		}
		if in.RejectActions != nil {
			s.rejectAll = *in.RejectActions
		}
		return c.JSON(fiber.Map{"faults": s.faults, "rejectActions": s.rejectAll})
	})
}

func webhookPath(carrier string) string {
	switch carrier {
	case "FASTSHIP":
		return "/api/webhooks/fastship"
	case "QUICKEXPRESS":
		return "/api/webhooks/quickexpress"
	}
	return "/api/webhooks/reliable"
}

// buildWebhook renders the event in the carrier's own wire format.
func buildWebhook(carrier string, sh *Shipment, in triggerRequest, reason string, now time.Time) ([]byte, error) {
	ts := now.Format("2006-01-02T15:04:05.000Z")
	desc := eventText[in.Event]
	remark := in.Remark
	switch carrier {
	case "FASTSHIP":
		code := map[string]string{"PICKED_UP": "PICKED_UP", "IN_TRANSIT": "IN_TRANSIT", "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY", "DELIVERED": "DELIVERED", "NDR": "DELIVERY_FAILED", "RTO": "RETURNED"}[in.Event]
		m := map[string]any{"shipment_id": sh.ShipmentID, "tracking_number": sh.Tracking, "event_code": code, "event_description": desc, "event_time": ts, "location": "Bengaluru Hub"}
		if in.Event == "NDR" {
			e := ndrCatalog[reason]
			if remark == "" {
				remark = e.remark
			}
			m["ndr_reason"], m["ndr_remark"] = e.fast, remark
		}
		return json.Marshal(m)
	case "QUICKEXPRESS":
		code := map[string]string{"PICKED_UP": "PU", "IN_TRANSIT": "IT", "OUT_FOR_DELIVERY": "OFD", "DELIVERED": "DLV", "NDR": "NDR", "RTO": "RTO"}[in.Event]
		m := map[string]any{"awb": sh.Tracking, "event": map[string]any{"type": code, "message": desc, "occurredAt": ts}, "facility": map[string]any{"city": "New Delhi", "code": "DEL-01"}}
		if in.Event == "NDR" {
			e := ndrCatalog[reason]
			if remark == "" {
				remark = e.remark
			}
			m["ndrDetails"] = map[string]any{"code": e.quick, "remarks": remark}
		}
		return json.Marshal(m)
	case "RELIABLE":
		id := map[string]int{"PICKED_UP": 20, "IN_TRANSIT": 30, "OUT_FOR_DELIVERY": 40, "DELIVERED": 50, "NDR": 60, "RTO": 70}[in.Event]
		text := map[string]string{"PICKED_UP": "Picked up", "IN_TRANSIT": "In transit", "OUT_FOR_DELIVERY": "Out for delivery", "DELIVERED": "Delivered", "NDR": "Delivery failed", "RTO": "Returned to origin"}[in.Event]
		m := map[string]any{"trackingCode": sh.Tracking, "statusId": id, "statusText": text, "updatedOn": ts, "hub": "Delhi Hub"}
		if in.Event == "DELIVERED" {
			m["proofOfDelivery"] = map[string]any{"receivedBy": "Consignee", "deliveryLocation": "New Delhi"}
		}
		if in.Event == "NDR" {
			e := ndrCatalog[reason]
			if remark == "" {
				remark = e.remark
			}
			m["failure"] = map[string]any{"reasonCode": e.reliable, "comment": remark}
		}
		return json.Marshal(m)
	}
	return nil, fmt.Errorf("unknown carrier")
}

func (s *Server) sign(carrier string, body []byte) string {
	secret := s.cfg.Secrets[carrier]
	if secret == "" {
		return ""
	}
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(body)
	return hex.EncodeToString(m.Sum(nil))
}

func (s *Server) deliver(carrier, url string, body []byte) delivery {
	d := delivery{URL: url}
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		d.Error = err.Error()
		return d
	}
	req.Header.Set("Content-Type", "application/json")
	if sig := s.sign(carrier, body); sig != "" {
		req.Header.Set("X-Carrier-Signature", sig)
	}
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		d.Error = err.Error()
		s.log.Warn("webhook delivery failed", "carrier", carrier, "error", err.Error())
		return d
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	d.Status = resp.StatusCode
	if json.Valid(b) {
		d.Body = b
	} else {
		d.Body, _ = json.Marshal(string(b))
	}
	return d
}
