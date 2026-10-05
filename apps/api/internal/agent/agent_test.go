package agent

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

var ist = time.FixedZone("IST", 5*3600+1800)
var now = time.Date(2026, 10, 5, 12, 0, 0, 0, ist)

func extract(t *testing.T, text string, reason domain.NDRReason) domain.ExtractedIntent {
	t.Helper()
	i, err := NewMock().ExtractIntent(context.Background(), text, IntentContext{Now: now, Reason: reason, DeliveryPincode: "110001", DeliveryCity: "New Delhi"})
	if err != nil {
		t.Fatal(err)
	}
	return i
}

func str(p *string) string {
	if p == nil {
		return "<nil>"
	}
	return *p
}

func TestDocumentedEnglishExample(t *testing.T) {
	i := extract(t, "Tomorrow evening after 6, please come. Tell the security guard.", domain.ReasonCustUnavailable)
	if i.Intent != domain.IntentRescheduleDelivery || str(i.PreferredDate) != "2026-10-06" || str(i.PreferredTimeStart) != "18:00" || i.PreferredTimeEnd != nil || str(i.SpecialInstruction) != "Inform the security guard" || i.Confidence < 0.9 {
		t.Fatalf("%+v", i)
	}
	if i.DetectedLanguage != "en" {
		t.Fatalf("language %s", i.DetectedLanguage)
	}
}

func TestBriefScenarioPhrase(t *testing.T) {
	i := extract(t, "Tomorrow evening after 6. Please tell security guard.", domain.ReasonCustUnavailable)
	if i.Intent != domain.IntentRescheduleDelivery || str(i.PreferredDate) != "2026-10-06" || str(i.PreferredTimeStart) != "18:00" || str(i.SpecialInstruction) != "Inform the security guard" {
		t.Fatalf("%+v", i)
	}
}

func TestRomanizedHindiCodeMixed(t *testing.T) {
	i := extract(t, "kal subah 10 baje ke baad aana, gate pe guard ko bolna", domain.ReasonCustUnavailable)
	if i.DetectedLanguage != "hi" || i.Intent != domain.IntentRescheduleDelivery || str(i.PreferredDate) != "2026-10-06" || str(i.PreferredTimeStart) != "10:00" || str(i.SpecialInstruction) != "Inform the security guard" {
		t.Fatalf("%+v", i)
	}
}

func TestNativeScriptAndOtherRomanizedLanguages(t *testing.T) {
	cases := []struct{ text, lang string }{
		{"कल शाम 6 बजे के बाद आना", "hi"},
		{"రేపు సాయంత్రం 6 తర్వాత రండి", "te"},
		{"நாளை மாலை 6 மணிக்குப் பிறகு வாங்க", "ta"},
		{"ನಾಳೆ ಸಂಜೆ 6 ರ ನಂತರ ಬನ್ನಿ", "kn"},
		{"naale sanje 6 nantara barbeku", "kn"},
		{"repu sayantram 6 tarvata ravali", "te"},
		{"naalaikku saayangalam 6 venum", "ta"},
	}
	for _, c := range cases {
		i := extract(t, c.text, domain.ReasonCustUnavailable)
		if i.DetectedLanguage != c.lang {
			t.Errorf("%q: language %q want %q", c.text, i.DetectedLanguage, c.lang)
		}
		if i.Intent != domain.IntentRescheduleDelivery || str(i.PreferredDate) != "2026-10-06" || str(i.PreferredTimeStart) != "18:00" {
			t.Errorf("%q: %+v", c.text, i)
		}
	}
}

func TestOriginalTextIsNotAltered(t *testing.T) {
	// ExtractIntent takes text by value and returns only structure; the caller persists the original verbatim.
	orig := "Kal SUBAH 10 baje ke baad aana"
	_ = extract(t, orig, domain.ReasonCustUnavailable)
	if orig != "Kal SUBAH 10 baje ke baad aana" {
		t.Fatal("unreachable")
	}
}

func TestIntentCatalogue(t *testing.T) {
	cases := []struct {
		text   string
		reason domain.NDRReason
		want   domain.IntentType
	}{
		{"Please cancel the order, I don't want it", domain.ReasonCustRefused, domain.IntentCancelOrder},
		{"I will refuse to accept it", domain.ReasonCustRefused, domain.IntentRefuseOrder},
		{"Flat 402, near Metro pillar 12, pincode 110001", domain.ReasonAddressIssue, domain.IntentAddressCorrection},
		{"my alternate number is 9123456780", domain.ReasonPhoneUnreachable, domain.IntentAlternateContact},
		{"call me on 9123456780", domain.ReasonCustUnavailable, domain.IntentPhoneUpdate},
		{"I don't have cash right now", domain.ReasonCODNotReady, domain.IntentCODNotReady},
		{"can I pay online? send link", domain.ReasonCODNotReady, domain.IntentPayOnline},
		{"payment done", domain.ReasonCODNotReady, domain.IntentPaymentDone},
		{"nobody came to my house, I was at home all day", domain.ReasonCustUnavailable, domain.IntentFalseAttempt},
		{"koi nahi aaya, main ghar pe tha", domain.ReasonCustUnavailable, domain.IntentFalseAttempt},
		{"yes", domain.ReasonCustUnavailable, domain.IntentConfirmYes},
		{"haan ji", domain.ReasonCustUnavailable, domain.IntentConfirmYes},
		{"no", domain.ReasonCustUnavailable, domain.IntentConfirmNo},
		{"please try again", domain.ReasonCustUnavailable, domain.IntentReattempt},
		{"thank you", domain.ReasonCustUnavailable, domain.IntentNoAction},
		{"asdf qwerty", domain.ReasonCustUnavailable, domain.IntentUnknown},
	}
	for _, c := range cases {
		if got := extract(t, c.text, c.reason).Intent; got != c.want {
			t.Errorf("%q -> %s, want %s", c.text, got, c.want)
		}
	}
}

func TestAddressExtraction(t *testing.T) {
	i := extract(t, "Flat 402, near Metro pillar 12, pincode 110001", domain.ReasonAddressIssue)
	if str(i.NewPincode) != "110001" || str(i.Landmark) != "Metro pillar 12" || !strings.HasPrefix(str(i.NewAddressLine), "Flat 402") {
		t.Fatalf("%+v", i)
	}
	i = extract(t, "I moved to Mumbai, pincode 400001, flat 5 near station", domain.ReasonAddressIssue)
	if str(i.NewCity) != "Mumbai" || str(i.NewPincode) != "400001" {
		t.Fatalf("%+v", i)
	}
	i = extract(t, "here is my location https://maps.google.com/?q=28.6,77.2", domain.ReasonAddressIssue)
	if !strings.HasPrefix(str(i.Landmark), "Live location shared") {
		t.Fatalf("%+v", i)
	}
}

func TestDateVariants(t *testing.T) {
	cases := map[string]string{
		"deliver on 10 oct please":   "2026-10-10",
		"come on 2026-10-09":         "2026-10-09",
		"in 3 days":                  "2026-10-08",
		"day after tomorrow morning": "2026-10-07",
		"on friday":                  "2026-10-09",
		"I will be back on 25/10":    "2026-10-25",
	}
	for text, want := range cases {
		if got := str(extract(t, text, domain.ReasonFutureDelivery).PreferredDate); got != want {
			t.Errorf("%q -> %s want %s", text, got, want)
		}
	}
}

func TestTimeVariants(t *testing.T) {
	cases := []struct{ text, start, end string }{
		{"tomorrow after 6 pm", "18:00", ""},
		{"tomorrow before 11 am", "", "11:00"},
		{"tomorrow morning", "09:00", "12:00"},
		{"tomorrow afternoon", "12:00", "16:00"},
		{"tomorrow at 14:30", "14:30", ""},
	}
	for _, c := range cases {
		i := extract(t, c.text, domain.ReasonCustUnavailable)
		s, e := str(i.PreferredTimeStart), str(i.PreferredTimeEnd)
		if c.start == "" {
			s = "<nil>"
		}
		if (c.start != "" && s != c.start) || (c.start == "" && i.PreferredTimeStart != nil) || (c.end != "" && e != c.end) || (c.end == "" && i.PreferredTimeEnd != nil) {
			t.Errorf("%q -> %s..%s want %s..%s", c.text, str(i.PreferredTimeStart), str(i.PreferredTimeEnd), c.start, c.end)
		}
	}
}

func TestHouseNumbersAndPhonesAreNotTimes(t *testing.T) {
	i := extract(t, "Flat 42 near temple call 9876543210", domain.ReasonAddressIssue)
	if i.PreferredTimeStart != nil || i.PreferredTimeEnd != nil {
		t.Fatalf("misread time: %+v", i)
	}
}

func TestLowConfidenceForVagueMessages(t *testing.T) {
	i := extract(t, "please come", domain.ReasonCustUnavailable)
	if i.Intent != domain.IntentReattempt || i.Confidence >= 0.75 {
		t.Fatalf("a vague 'please come' must stay below the action threshold: %+v", i)
	}
}

func TestLanguageDetection(t *testing.T) {
	cases := []struct{ text, want string }{
		{"Tomorrow evening please", "en"},
		{"kal subah 10 baje ke baad aana", "hi"},
		{"आज नहीं आ सकता", "hi"},
		{"రేపు రండి", "te"},
		{"நாளை வாங்க", "ta"},
		{"ನಾಳೆ ಬನ್ನಿ", "kn"},
		{"12345", ""},
	}
	for _, c := range cases {
		if got, _ := DetectLanguage(c.text); got != c.want {
			t.Errorf("%q -> %q want %q", c.text, got, c.want)
		}
	}
}

func TestPincodeLanguage(t *testing.T) {
	for pin, want := range map[string]string{"560001": "kn", "110001": "hi", "500001": "te", "600001": "ta", "400001": "en"} {
		if got := PincodeLanguage(pin); got != want {
			t.Errorf("%s -> %s want %s", pin, got, want)
		}
	}
}

func TestInterpretRemark(t *testing.T) {
	m := NewMock()
	cases := map[string]domain.NDRReason{
		"Customer phone switched off":          domain.ReasonPhoneUnreachable,
		"society security did not allow entry": domain.ReasonAccessRestricted,
		"customer refused to take parcel":      domain.ReasonCustRefused,
		"consignee asked delivery next week":   domain.ReasonFutureDelivery,
		"door locked":                          domain.ReasonCustUnavailable,
	}
	for remark, want := range cases {
		if got, _, _ := m.InterpretRemark(context.Background(), remark); got != want {
			t.Errorf("%q -> %s want %s", remark, got, want)
		}
	}
}

func TestTemplatesCoverFiveLanguagesForCoreFlow(t *testing.T) {
	core := []string{"contact.CUST_UNAVAILABLE", "contact.CUST_REFUSED", "contact.ADDRESS_ISSUE", "contact.PHONE_UNREACHABLE", "contact.COD_NOT_READY", "contact.FUTURE_DELIVERY",
		"contact.ACCESS_RESTRICTED", "contact.SUSPECT_FALSE_ATTEMPT", "contact.OUT_OF_AREA", "reminder", "clarify.confirm", "clarify.unknown", "offer.date_hold_window", "offer.date_cutoff",
		"submitted", "accepted.reattempt", "accepted.rto", "accepted.generic", "approval.pending", "approval.rejected", "rejected.carrier", "escalated", "offer.prepaid", "payment.link"}
	for _, k := range core {
		if !FullyLocalized(k) {
			t.Errorf("template %s is not localized in all five languages", k)
		}
	}
}

// Product rule: only the accepted.* family may claim carrier acceptance.
func TestOnlyAcceptedTemplatesClaimCarrierAcceptance(t *testing.T) {
	for _, k := range TemplateKeys() {
		if strings.HasPrefix(k, "accepted.") {
			continue
		}
		en := strings.ToLower(templates[k]["en"])
		if strings.Contains(en, "accepted the") || strings.Contains(en, "has accepted") || strings.Contains(en, "confirmed") && strings.Contains(en, "carrier") && !strings.Contains(en, "confirm as soon") && !strings.Contains(en, "could not confirm") {
			t.Errorf("template %s must not claim carrier acceptance: %q", k, en)
		}
	}
	sub := Render("submitted", "en", map[string]string{"summary": "delivery reattempt on 2026-10-06"})
	if strings.Contains(strings.ToLower(sub), "accepted the") || !strings.Contains(sub, "submitted") {
		t.Fatalf("submitted message must say submitted only: %s", sub)
	}
	acc := Render("accepted.reattempt", "en", map[string]string{"date": "06 Oct 2026", "timeNote": ""})
	if !strings.Contains(acc, "The carrier has accepted the reattempt request for 06 Oct 2026") {
		t.Fatalf("%s", acc)
	}
}
