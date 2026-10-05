// Package mockcarriers implements three independent mock courier APIs (FastShip, QuickExpress,
// ReliableCourier) plus a control surface used to emit carrier webhooks on demand.
// It deliberately shares no code with the Zippy API: it plays the role of external systems.
package mockcarriers

import (
	"fmt"
	"log/slog"
	"math"
	"strings"
	"sync"
	"time"

	"github.com/gofiber/fiber/v2"
)

type Config struct {
	ZippyWebhookBase string
	Secrets          map[string]string // carrier code -> HMAC secret
	LatencyMS        int
}

// Shipment is the carrier-side record of a booking.
type Shipment struct {
	Carrier     string    `json:"carrier"`
	ShipmentID  string    `json:"shipmentId"`
	Tracking    string    `json:"trackingNumber"`
	CallbackURL string    `json:"callbackUrl"`
	Status      string    `json:"status"`
	Attempts    int       `json:"attempts"`
	CreatedAt   time.Time `json:"createdAt"`
	Actions     []string  `json:"actions"`
}

type Server struct {
	cfg Config
	log *slog.Logger

	mu        sync.Mutex
	shipments map[string]*Shipment // key: tracking number
	counters  map[string]int
	faults    map[string]string // carrier -> "", http500, timeout, malformed, unavailable
	rejectAll bool
	calls     map[string]int // endpoint call counters, for cache/coalescing verification
	actionIDs map[string]actionRecord
}

type actionRecord struct {
	status, ref, reason string
}

func New(cfg Config, log *slog.Logger) *Server {
	return &Server{cfg: cfg, log: log, shipments: map[string]*Shipment{}, faults: map[string]string{}, calls: map[string]int{},
		actionIDs: map[string]actionRecord{},
		counters:  map[string]int{"fs_ship": 700000, "fs_track": 123456788, "qe_quote": 90000, "qe_book": 800000, "qe_awb": 987654320, "rc_do": 600000, "rc_track": 1122334454, "act": 0}}
}

func (s *Server) next(key string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.counters[key]++
	return s.counters[key]
}

func (s *Server) count(endpoint string) {
	s.mu.Lock()
	s.calls[endpoint]++
	s.mu.Unlock()
}

func (s *Server) fault(carrier string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.faults[carrier]
}

// applyFault emulates a misbehaving carrier. Returns true when the response was written.
func (s *Server) applyFault(c *fiber.Ctx, carrier string) bool {
	switch s.fault(carrier) {
	case "http500":
		_ = c.Status(500).JSON(fiber.Map{"error": "internal carrier error"})
		return true
	case "timeout":
		time.Sleep(8 * time.Second)
		return true
	case "malformed":
		c.Set("Content-Type", "application/json")
		_ = c.Status(200).SendString(`{"unexpected": ["shape"], "service": "nope"`)
		return true
	case "unavailable":
		_ = c.Status(200).JSON(fiber.Map{"success": false, "status": "UNAVAILABLE", "code": 404, "message": "no service on this lane"})
		return true
	}
	return false
}

func (s *Server) latency() {
	if s.cfg.LatencyMS > 0 {
		time.Sleep(time.Duration(s.cfg.LatencyMS) * time.Millisecond)
	}
}

func (s *Server) register(sh *Shipment) {
	s.mu.Lock()
	s.shipments[sh.Tracking] = sh
	s.mu.Unlock()
}

func (s *Server) App() *fiber.App {
	app := fiber.New(fiber.Config{DisableStartupMessage: true, ErrorHandler: func(c *fiber.Ctx, err error) error {
		code := 500
		if fe, ok := err.(*fiber.Error); ok {
			code = fe.Code
		}
		return c.Status(code).JSON(fiber.Map{"error": err.Error()})
	}})
	app.Get("/health", func(c *fiber.Ctx) error { return c.JSON(fiber.Map{"status": "ok"}) })
	s.fastship(app)
	s.quickexpress(app)
	s.reliable(app)
	s.control(app)
	return app
}

// ---- pricing helpers (reproduce the documented sample numbers for the 560001 -> 110001, 1.5kg COD route) ----

func zoneFactor(origin, dest string) float64 {
	switch {
	case len(origin) < 2 || len(dest) < 2:
		return 1
	case origin[:2] == dest[:2]:
		return 0.8
	case origin[0] == dest[0]:
		return 0.9
	}
	return 1
}

func round2(v float64) float64 { return math.Round(v*100) / 100 }

func volumetricKg(l, w, h float64) float64 { return l * w * h / 5000 }

func chargeableKg(grams int, l, w, h float64) float64 {
	kg := float64(grams) / 1000
	return math.Max(kg, volumetricKg(l, w, h))
}

func phoneOK(p string) bool {
	if len(p) != 10 {
		return false
	}
	for _, r := range p {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func badRequest(c *fiber.Ctx, msg string) error {
	return c.Status(400).JSON(fiber.Map{"error": msg})
}

func pinOK(p string) bool {
	if len(p) != 6 {
		return false
	}
	for _, r := range p {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func fmtID(prefix string, n int) string { return fmt.Sprintf("%s%d", prefix, n) }

func lower(s string) string { return strings.ToLower(s) }
