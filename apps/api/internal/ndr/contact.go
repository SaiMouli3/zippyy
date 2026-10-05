package ndr

import (
	"context"
	"fmt"

	"github.com/saimouli3/zippyy/apps/api/internal/agent"
	"github.com/saimouli3/zippyy/apps/api/internal/comms"
	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/rules"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

type ContactOptions struct {
	SimulateFailures []string `json:"simulateFailures"` // channels forced to fail (demo/testing)
	Channel          string   `json:"channel"`          // start from this channel (used for escalation reminders)
	Reminder         bool     `json:"reminder"`
}

type ContactResult struct {
	Delivered bool          `json:"delivered"`
	Deferred  bool          `json:"deferred"`
	Exhausted bool          `json:"exhausted"`
	Channel   string        `json:"channel,omitempty"`
	MessageID string        `json:"messageId,omitempty"`
	Case      store.NDRCase `json:"case"`
}

// Contact opens (or repeats) the conversation with the buyer in the case language.
func (s *Service) Contact(ctx context.Context, ref string, opts ContactOptions) (*ContactResult, error) {
	var res *ContactResult
	err := s.withCase(ctx, ref, func(ctx context.Context, c *store.NDRCase) error {
		var err error
		res, err = s.contactCase(ctx, c, opts)
		return err
	})
	return res, err
}

// contactCase assumes the case lock is already held.
func (s *Service) contactCase(ctx context.Context, c *store.NDRCase, opts ContactOptions) (*ContactResult, error) {
	var res *ContactResult
	err := func() error {
		switch c.State {
		case domain.CaseOpened, domain.CaseBuyerContactPending, domain.CaseEscalated:
		default:
			return domain.Conflict("INVALID_CASE_STATE", fmt.Sprintf("cannot contact the buyer while the case is %s", c.State))
		}
		r := s.Store.R()
		order, err := r.GetOrder(ctx, c.OrderID, false)
		if err != nil {
			return err
		}
		seller, err := r.GetOrCreateSellerRules(ctx, order.MerchantID)
		if err != nil {
			return err
		}
		if ok, detail := rules.CommAllowed(*seller, s.Now()); !ok {
			_ = r.InsertCommAttempt(ctx, c.ID, "NONE", "DEFERRED", "outside seller communication hours: "+detail, "")
			if c.State == domain.CaseOpened {
				if err := s.move(ctx, c, domain.CaseBuyerContactPending, agentActor, "CONTACT_DEFERRED", "Buyer contact deferred: outside the seller's communication hours", map[string]any{"detail": detail}); err != nil {
					return err
				}
			} else if err := s.note(ctx, c, agentActor, "CONTACT_DEFERRED", "Buyer contact deferred: outside the seller's communication hours", map[string]any{"detail": detail}); err != nil {
				return err
			}
			res = &ContactResult{Deferred: true, Case: *c}
			return nil
		}

		key := "contact." + string(c.NormalizedReason)
		if opts.Reminder || c.ContactAttempts > 0 {
			key = "reminder"
		}
		channels := rules.ChannelOrder(*seller)
		if opts.Channel != "" {
			channels = rotateTo(channels, opts.Channel)
		}
		fail := map[string]bool{}
		for _, ch := range opts.SimulateFailures {
			fail[ch] = true
		}
		text, err := s.LLM.ComposeMessage(ctx, key, c.Language, nil)
		if err != nil {
			return err
		}
		internal, _ := s.LLM.ComposeMessage(ctx, key, "en", nil)
		attempts, delivered := s.Comms.Send(ctx, channels, comms.Message{CaseNumber: c.CaseNumber, To: order.Customer.Phone, Language: c.Language, Text: text}, fail)

		var deliveredCh, msgID string
		err = s.Store.InTx(ctx, func(tr *store.Repo) error {
			for _, a := range attempts {
				status, errMsg := a.Result.Status, ""
				if a.Err != nil {
					status, errMsg = "FAILED", a.Err.Error()
				}
				if err := tr.InsertCommAttempt(ctx, c.ID, a.Channel, status, errMsg, a.Result.ProviderRef); err != nil {
					return err
				}
				s.Metrics.Inc("ndr_comm_attempts_total", "channel", a.Channel, "status", status)
			}
			now := s.Now()
			c.ContactAttempts++
			c.LastContactedAt = &now
			if delivered {
				last := attempts[len(attempts)-1]
				deliveredCh = last.Channel
				id, err := tr.InsertMessage(ctx, store.Message{CaseID: c.ID, Direction: "OUTBOUND", SenderType: domain.ActorAgent, Channel: deliveredCh, Language: c.Language,
					OriginalText: text, InternalText: internal, DeliveryStatus: last.Result.Status, Processed: true})
				if err != nil {
					return err
				}
				msgID = id
				c.ContactExhausted = false
				desc := fmt.Sprintf("Agent contacted the buyer via %s in %s", deliveredCh, agent.LanguageName(c.Language))
				if len(attempts) > 1 {
					desc += fmt.Sprintf(" (after %d failed channel(s))", len(attempts)-1)
				}
				return s.moveR(ctx, tr, c, domain.CaseBuyerContactPending, agentActor, "BUYER_CONTACTED", desc, map[string]any{"channel": deliveredCh, "language": c.Language, "messageKey": key, "failedChannels": failedChannels(attempts)})
			}
			c.ContactExhausted = true
			if _, err := tr.InsertMessage(ctx, store.Message{CaseID: c.ID, Direction: "OUTBOUND", SenderType: domain.ActorAgent, Channel: firstChannel(attempts, channels), Language: c.Language,
				OriginalText: text, InternalText: internal, DeliveryStatus: "FAILED", Processed: true}); err != nil {
				return err
			}
			return s.noteR(ctx, tr, c, agentActor, "CONTACT_FAILED", "All buyer communication channels failed", map[string]any{"attempts": len(attempts), "failedChannels": failedChannels(attempts)})
		})
		if err != nil {
			return err
		}
		if !delivered {
			if err := s.onContactExhausted(ctx, c, order, seller); err != nil {
				return err
			}
		}
		res = &ContactResult{Delivered: delivered, Exhausted: !delivered, Channel: deliveredCh, MessageID: msgID}
		fresh, _ := s.Store.R().GetCase(ctx, c.ID, false)
		if fresh != nil {
			res.Case = *fresh
		}
		return nil
	}()
	return res, err
}

func failedChannels(a []comms.Attempt) []string {
	var out []string
	for _, x := range a {
		if x.Err != nil {
			out = append(out, x.Channel)
		}
	}
	return out
}

func firstChannel(a []comms.Attempt, fallback []string) string {
	if len(a) > 0 {
		return a[0].Channel
	}
	if len(fallback) > 0 {
		return fallback[0]
	}
	return "NONE"
}

func rotateTo(channels []string, start string) []string {
	idx := -1
	for i, c := range channels {
		if c == start {
			idx = i
		}
	}
	if idx < 0 {
		return channels
	}
	return append(append([]string{}, channels[idx:]...), channels[:idx]...)
}

// onContactExhausted: every channel failed. A final attempt goes to the seller decision flow; otherwise the
// seller is alerted to supply an alternate contact (UC3).
func (s *Service) onContactExhausted(ctx context.Context, c *store.NDRCase, order *domain.Order, seller *domain.SellerRules) error {
	r := s.Store.R()
	carrier, err := r.GetCarrierRules(ctx, c.CarrierCode)
	if err != nil {
		return err
	}
	if rules.IsFinalAttempt(c.AttemptNumber, *seller, *carrier) {
		return s.finalAttemptDecision(ctx, c, order, seller, carrier, "buyer unreachable on every channel")
	}
	if c.State != domain.CaseEscalated {
		if err := s.move(ctx, c, domain.CaseEscalated, agentActor, "SELLER_ALERTED", "Buyer unreachable on all channels: seller alerted to provide an alternate contact number",
			map[string]any{"needs": "ALTERNATE_CONTACT", "channels": rules.ChannelOrder(*seller)}); err != nil {
			return err
		}
	} else if err := s.note(ctx, c, agentActor, "SELLER_ALERTED", "Seller re-alerted: still unreachable", nil); err != nil {
		return err
	}
	return nil
}

var _ = platform.L
