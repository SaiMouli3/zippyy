package carriers

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

type httpClient struct {
	c       *http.Client
	baseURL string
}

func newHTTPClient(cfg Config) *httpClient {
	return &httpClient{c: &http.Client{Timeout: cfg.Timeout}, baseURL: strings.TrimRight(cfg.BaseURL, "/")}
}

// do sends a JSON request and returns the raw response body. Failures are classified into CarrierError.
func (h *httpClient) do(ctx context.Context, method, path string, body any) ([]byte, int, error) {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, 0, &CarrierError{Kind: domain.FailMalformed, Message: "cannot encode request", Err: err}
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, h.baseURL+path, rd)
	if err != nil {
		return nil, 0, &CarrierError{Kind: domain.FailUnavailable, Message: err.Error(), Err: err}
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")
	resp, err := h.c.Do(req)
	if err != nil {
		var ne net.Error
		if errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &ne) && ne.Timeout()) {
			return nil, 0, &CarrierError{Kind: domain.FailTimeout, Message: "carrier did not respond in time", Err: err}
		}
		return nil, 0, &CarrierError{Kind: domain.FailUnavailable, Message: "carrier unreachable", Err: err}
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		var ne net.Error
		if errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &ne) && ne.Timeout()) {
			return nil, resp.StatusCode, &CarrierError{Kind: domain.FailTimeout, Message: "carrier response timed out", Err: err}
		}
		return nil, resp.StatusCode, &CarrierError{Kind: domain.FailUnavailable, Message: "cannot read carrier response", Err: err}
	}
	if resp.StatusCode >= 500 {
		return data, resp.StatusCode, &CarrierError{Kind: domain.FailHTTPError, Message: fmt.Sprintf("carrier returned HTTP %d", resp.StatusCode)}
	}
	return data, resp.StatusCode, nil
}

func malformed(msg string, err error) error {
	return &CarrierError{Kind: domain.FailMalformed, Message: msg, Err: err}
}

func decode(data []byte, out any) error {
	if err := json.Unmarshal(data, out); err != nil {
		return malformed("carrier response is not valid JSON for the expected contract", err)
	}
	return nil
}

var etaRe = regexp.MustCompile(`(\d+)\s*(?:-|to|–)\s*(\d+)`)
var etaOneRe = regexp.MustCompile(`(\d+)`)

// parseETA turns "4-5 business days" / "2 business days" into min/max days.
func parseETA(s string) (int, int, bool) {
	if m := etaRe.FindStringSubmatch(s); m != nil {
		lo, _ := strconv.Atoi(m[1])
		hi, _ := strconv.Atoi(m[2])
		if hi < lo {
			lo, hi = hi, lo
		}
		return lo, hi, true
	}
	if m := etaOneRe.FindStringSubmatch(s); m != nil {
		n, _ := strconv.Atoi(m[1])
		return n, n, true
	}
	return 0, 0, false
}

// checkTotal guards against carriers whose arithmetic doesn't add up; we never silently "fix" prices.
func checkTotal(total float64, parts ...float64) error {
	sum := 0.0
	for _, p := range parts {
		sum += p
	}
	if d := sum - total; d > 0.05 || d < -0.05 {
		return malformed(fmt.Sprintf("charges sum to %.2f but carrier total is %.2f", sum, total), nil)
	}
	return nil
}

func nonNegative(vals ...float64) bool {
	for _, v := range vals {
		if v < 0 {
			return false
		}
	}
	return true
}

func parseTime(s string) (time.Time, error) {
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339, "2006-01-02T15:04:05"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t.UTC(), nil
		}
	}
	return time.Time{}, fmt.Errorf("unparseable timestamp %q", s)
}
