package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// MockControl talks to the mock carriers' control surface. In production this component would not exist;
// it only drives the demo.
type MockControl struct {
	BaseURLs       map[string]string // carrier code -> base URL
	ZippyPublicURL string
	Client         *http.Client
}

func NewMockControl(urls map[string]string, zippyURL string) *MockControl {
	return &MockControl{BaseURLs: urls, ZippyPublicURL: zippyURL, Client: &http.Client{Timeout: 15 * time.Second}}
}

type TriggerInput struct {
	Event      string `json:"event"`
	NDRReason  string `json:"ndrReason,omitempty"`
	Remark     string `json:"remark,omitempty"`
	Duplicates int    `json:"duplicates,omitempty"`
}

func (m *MockControl) call(ctx context.Context, carrier, method, path string, body any) (json.RawMessage, int, error) {
	base, ok := m.BaseURLs[carrier]
	if !ok {
		return nil, 0, domain.Validation("unknown carrier", map[string]string{"carrier": carrier})
	}
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(base, "/")+path, rd)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := m.Client.Do(req)
	if err != nil {
		return nil, 0, domain.NewError(http.StatusBadGateway, "MOCK_CARRIER_UNREACHABLE", "mock carrier control endpoint unreachable").With("detail", err.Error())
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	return b, resp.StatusCode, nil
}

// TriggerEvent makes the mock carrier emit a real webhook back to Zippy for an existing shipment.
func (s *Services) TriggerEvent(ctx context.Context, carrier, shipmentRef string, in TriggerInput) (json.RawMessage, error) {
	carrier = strings.ToUpper(carrier)
	if aliases := map[string]string{"RELIABLECOURIER": "RELIABLE"}; aliases[carrier] != "" {
		carrier = aliases[carrier]
	}
	if _, ok := s.Registry.Get(carrier); !ok {
		return nil, domain.Validation("unknown carrier", map[string]string{"carrier": carrier})
	}
	sh, err := s.GetShipmentForRef(ctx, shipmentRef)
	if err != nil {
		return nil, err
	}
	if sh.CarrierCode != carrier {
		return nil, domain.Validation("shipment belongs to a different carrier", map[string]string{"carrier": fmt.Sprintf("shipment is %s", sh.CarrierCode)})
	}
	body := map[string]any{"carrier": carrier, "trackingNumber": sh.TrackingNumber, "carrierShipmentId": sh.CarrierShipmentID, "event": in.Event,
		"ndrReason": in.NDRReason, "remark": in.Remark, "duplicates": in.Duplicates, "callbackBase": s.Control.ZippyPublicURL}
	out, status, err := s.Control.call(ctx, carrier, http.MethodPost, "/control/trigger", body)
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, domain.NewError(http.StatusBadRequest, "MOCK_CARRIER_REJECTED", "mock carrier rejected the trigger").With("response", string(out))
	}
	return out, nil
}

func (s *Services) MockFaultConfig(ctx context.Context, carrier, fault string, rejectActions *bool) (json.RawMessage, error) {
	carrier = strings.ToUpper(carrier)
	out, status, err := s.Control.call(ctx, carrier, http.MethodPost, "/control/config", map[string]any{"carrier": carrier, "fault": fault, "rejectActions": rejectActions})
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, domain.NewError(http.StatusBadRequest, "MOCK_CARRIER_REJECTED", "mock carrier rejected the config").With("response", string(out))
	}
	return out, nil
}

func (s *Services) MockStats(ctx context.Context, carrier string) (json.RawMessage, error) {
	out, _, err := s.Control.call(ctx, strings.ToUpper(carrier), http.MethodGet, "/control/stats", nil)
	return out, err
}
