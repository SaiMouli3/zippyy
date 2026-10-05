package tests

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/saimouli3/zippyy/apps/api/testkit"
)

// istDate returns the IST calendar date n days from now (the clock the rules engine and mock carriers use).
func istDate(n int) string {
	return time.Now().UTC().Add(5*time.Hour+30*time.Minute).AddDate(0, 0, n).Format("2006-01-02")
}

func reply(e *testkit.Env, caseID, text string) testkit.Resp {
	e.T.Helper()
	r := e.Post("/api/ndr/cases/"+caseID+"/buyer-reply", map[string]any{"text": text})
	if r.Status != 200 {
		e.T.Fatalf("buyer reply %q: %d %s", text, r.Status, r.Raw)
	}
	return r
}

func contact(e *testkit.Env, caseID string, body map[string]any) testkit.Resp {
	e.T.Helper()
	r := e.Post("/api/ndr/cases/"+caseID+"/contact", body)
	if r.Status != 200 {
		e.T.Fatalf("contact: %d %s", r.Status, r.Raw)
	}
	return r
}

func process(e *testkit.Env, caseID, trigger string) testkit.Resp {
	e.T.Helper()
	r := e.Post("/api/ndr/cases/"+caseID+"/process", map[string]any{"trigger": trigger})
	if r.Status != 200 {
		e.T.Fatalf("process %s: %d %s", trigger, r.Status, r.Raw)
	}
	return r
}

func state(e *testkit.Env, caseID string) string { return e.Case(caseID).Str("case.state") }

func messages(e *testkit.Env, caseID string) []string {
	r := e.Case(caseID)
	var out []string
	for i := 0; i < r.Len("messages"); i++ {
		out = append(out, r.Str(fmt.Sprintf("messages.%d.direction", i))+": "+r.Str(fmt.Sprintf("messages.%d.originalText", i)))
	}
	return out
}

func outbound(e *testkit.Env, caseID string) []string {
	var out []string
	for _, m := range messages(e, caseID) {
		if strings.HasPrefix(m, "OUTBOUND: ") {
			out = append(out, strings.TrimPrefix(m, "OUTBOUND: "))
		}
	}
	return out
}

func eventTypes(e *testkit.Env, caseID string) []string {
	r := e.Get("/api/ndr/cases/" + caseID + "/timeline")
	var out []string
	for i := 0; i < r.Len("timeline"); i++ {
		out = append(out, r.Str(fmt.Sprintf("timeline.%d.eventType", i)))
	}
	return out
}

func indexOf(list []string, s string) int {
	for i, v := range list {
		if v == s {
			return i
		}
	}
	return -1
}

func anyContains(list []string, sub string) bool {
	for _, v := range list {
		if strings.Contains(v, sub) {
			return true
		}
	}
	return false
}

func actionStatuses(e *testkit.Env, caseID string) []string {
	r := e.Case(caseID)
	var out []string
	for i := 0; i < r.Len("carrierActions"); i++ {
		out = append(out, r.Str(fmt.Sprintf("carrierActions.%d.actionType", i))+":"+r.Str(fmt.Sprintf("carrierActions.%d.status", i)))
	}
	return out
}

func pendingApprovals(e *testkit.Env, caseID string) testkit.Resp {
	return e.Get("/api/approvals?status=PENDING&caseId=" + caseID)
}

func must(t *testing.T, ok bool, format string, args ...any) {
	t.Helper()
	if !ok {
		t.Fatalf(format, args...)
	}
}
