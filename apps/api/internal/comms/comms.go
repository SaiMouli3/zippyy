// Package comms abstracts buyer communication channels. Providers here are mocks; the interface is what a
// real WhatsApp Business / IVR / SMS gateway integration would implement.
package comms

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync/atomic"
)

const (
	WhatsApp = "WHATSAPP"
	IVR      = "IVR"
	SMS      = "SMS"
)

type Message struct {
	CaseNumber string
	To         string
	Language   string
	Text       string
}

type Result struct {
	Status      string // SENT | DELIVERED
	ProviderRef string
}

type Provider interface {
	Channel() string
	Send(ctx context.Context, m Message) (Result, error)
}

var ErrChannelFailed = errors.New("channel delivery failed")

var seq atomic.Int64

// MockProvider always "delivers" unless the destination is a designated unreachable test number
// (ending 0000) or the dispatcher was told to simulate an outage for this channel.
type MockProvider struct {
	channel string
}

func NewMock(channel string) *MockProvider { return &MockProvider{channel: channel} }

func (p *MockProvider) Channel() string { return p.channel }

func (p *MockProvider) Send(_ context.Context, m Message) (Result, error) {
	if strings.HasSuffix(m.To, "0000") && p.channel != IVR {
		return Result{}, fmt.Errorf("%w: %s number %s is not reachable", ErrChannelFailed, p.channel, m.To)
	}
	status := "SENT"
	if p.channel == WhatsApp {
		status = "DELIVERED"
	}
	return Result{Status: status, ProviderRef: fmt.Sprintf("mock-%s-%d", strings.ToLower(p.channel), seq.Add(1))}, nil
}

type Attempt struct {
	Channel string
	Result  Result
	Err     error
}

// Dispatcher tries channels in the given order until one succeeds.
type Dispatcher struct {
	providers map[string]Provider
}

func NewDispatcher(ps ...Provider) *Dispatcher {
	d := &Dispatcher{providers: map[string]Provider{}}
	for _, p := range ps {
		d.providers[p.Channel()] = p
	}
	return d
}

func NewMockDispatcher() *Dispatcher {
	return NewDispatcher(NewMock(WhatsApp), NewMock(IVR), NewMock(SMS))
}

// Send walks channels in order, honouring simulated failures (for demos/tests). It returns every attempt.
func (d *Dispatcher) Send(ctx context.Context, channels []string, m Message, simulateFail map[string]bool) ([]Attempt, bool) {
	var attempts []Attempt
	for _, ch := range channels {
		p, ok := d.providers[ch]
		if !ok {
			continue
		}
		if simulateFail[ch] {
			attempts = append(attempts, Attempt{Channel: ch, Err: fmt.Errorf("%w: simulated %s outage", ErrChannelFailed, ch)})
			continue
		}
		res, err := p.Send(ctx, m)
		attempts = append(attempts, Attempt{Channel: ch, Result: res, Err: err})
		if err == nil {
			return attempts, true
		}
	}
	return attempts, false
}
