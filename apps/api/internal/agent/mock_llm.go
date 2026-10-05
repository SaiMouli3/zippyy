package agent

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
)

// MockLLMProvider is a deterministic stand-in so the MVP runs with no API keys. It implements the same
// contract a real provider would: text in, structured JSON-shaped intent out.
type MockLLMProvider struct{}

func NewMock() *MockLLMProvider { return &MockLLMProvider{} }

func (*MockLLMProvider) Name() string { return "mock" }

var (
	reISO       = regexp.MustCompile(`\b(\d{4})-(\d{2})-(\d{2})\b`)
	reDMY       = regexp.MustCompile(`\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b`)
	reDayMonth  = regexp.MustCompile(`\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b`)
	reMonthDay  = regexp.MustCompile(`\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b`)
	reInDays    = regexp.MustCompile(`\b(?:in|after)\s+(\d{1,2})\s+days?\b|\b(\d{1,2})\s+(?:din|days?)\s+(?:baad|later|ke baad)\b`)
	rePhone     = regexp.MustCompile(`\b[6-9]\d{9}\b`)
	rePincode   = regexp.MustCompile(`\b[1-9]\d{5}\b`)
	reLongDigit = regexp.MustCompile(`\d{3,}`)
	reAMPM      = regexp.MustCompile(`(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)`)
	reColon     = regexp.MustCompile(`\b(\d{1,2}):(\d{2})\b`)
	reBaje      = regexp.MustCompile(`\b(\d{1,2})\s*(?:baje|bje|o'?clock|ghantalaku|gantalaku|mani|manikku|ಗಂಟೆ|बजे)`)
	reAtHour    = regexp.MustCompile(`\b(?:after|before|by|at|around|from|till|until)\s+(\d{1,2})(?::(\d{2}))?\b`)
	reBareHour  = regexp.MustCompile(`(\d{1,2})\s*(?:ke\s+baad|baad|ku\s+mela|ku\s+mele|tarvata|nantara|తర్వాత|பிறகு|மணிக்குப்?|மணி|ನಂತರ|ರ\s|के\s+बाद|बाद)`)
	reLoneHour  = regexp.MustCompile(`(?:^|\s)(\d{1,2})(?:\s|$|[.,])`)
	reLandmark  = regexp.MustCompile(`(?i)(?:near|opposite|opp\.?|behind|beside|next to|landmark(?:\s+is)?\s*[:\-]?)\s+([A-Za-z0-9 .'\-]{3,60})`)
	reLandmarkH = regexp.MustCompile(`(?i)([A-Za-z0-9 .'\-]{3,40})\s+(?:ke\s+paas|ke\s+pass|ke\s+saamne|ke\s+samne)`)
	reMapsLink  = regexp.MustCompile(`(?i)https?://\S*(?:maps|goo\.gl)\S*`)
	reLatLng    = regexp.MustCompile(`(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})`)
	reAddrLine  = regexp.MustCompile(`(?i)\b((?:flat|house\s*(?:no\.?)?|door\s*(?:no\.?)?|plot|room|h\.?\s*no\.?)\s*[A-Za-z0-9/\-]+[^,.\n]{0,50})`)
)

var monthIdx = map[string]time.Month{"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
var weekdays = map[string]time.Weekday{"monday": time.Monday, "tuesday": time.Tuesday, "wednesday": time.Wednesday, "thursday": time.Thursday, "friday": time.Friday, "saturday": time.Saturday, "sunday": time.Sunday}

var tomorrowWords = []string{"tomorrow", "tmrw", "tomorow", "kal ", " kal", "naale", "naalai", "naalaikku", "repu", "कल", "రేపు", "நாளை", "ನಾಳೆ"}
var dayAfterWords = []string{"day after tomorrow", "parso", "parson", "परसों", "ఎల్లుండి", "நாளைமறுநாள்", "ನಾಡಿದ್ದು"}
var todayWords = []string{"today", "aaj", "ivvala", "indru", "indu ", "आज", "ఈరోజు", "இன்று", "ಇಂದು"}

func hasAny(s string, words []string) bool {
	for _, w := range words {
		if strings.Contains(s, w) {
			return true
		}
	}
	return false
}

func ptr(s string) *string { return &s }

func hhmm(h, m int) string { return fmt.Sprintf("%02d:%02d", h, m) }

// parseDate resolves relative and absolute dates in IST and returns the text with the date span removed so
// numbers inside it are not mistaken for clock times.
func parseDate(low string, now time.Time) (*string, string) {
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	out := func(d time.Time) *string { s := d.Format("2006-01-02"); return &s }
	if m := reISO.FindStringSubmatch(low); m != nil {
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		d, _ := strconv.Atoi(m[3])
		return out(time.Date(y, time.Month(mo), d, 0, 0, 0, 0, now.Location())), reISO.ReplaceAllString(low, " ")
	}
	if m := reInDays.FindStringSubmatch(low); m != nil {
		n := m[1]
		if n == "" {
			n = m[2]
		}
		k, _ := strconv.Atoi(n)
		return out(today.AddDate(0, 0, k)), reInDays.ReplaceAllString(low, " ")
	}
	if m := reDayMonth.FindStringSubmatch(low); m != nil {
		d, _ := strconv.Atoi(m[1])
		return out(rollForward(today, monthIdx[m[2]], d)), reDayMonth.ReplaceAllString(low, " ")
	}
	if m := reMonthDay.FindStringSubmatch(low); m != nil {
		d, _ := strconv.Atoi(m[2])
		return out(rollForward(today, monthIdx[m[1]], d)), reMonthDay.ReplaceAllString(low, " ")
	}
	if m := reDMY.FindStringSubmatch(low); m != nil && !strings.Contains(m[0], ":") {
		d, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		if mo >= 1 && mo <= 12 && d >= 1 && d <= 31 {
			y := today.Year()
			if m[3] != "" {
				y, _ = strconv.Atoi(m[3])
				if y < 100 {
					y += 2000
				}
				return out(time.Date(y, time.Month(mo), d, 0, 0, 0, 0, now.Location())), reDMY.ReplaceAllString(low, " ")
			}
			return out(rollForward(today, time.Month(mo), d)), reDMY.ReplaceAllString(low, " ")
		}
	}
	padded := " " + low + " "
	switch {
	case hasAny(padded, dayAfterWords):
		return out(today.AddDate(0, 0, 2)), padded
	case hasAny(padded, tomorrowWords):
		return out(today.AddDate(0, 0, 1)), padded
	case hasAny(padded, todayWords):
		return out(today), padded
	}
	for name, wd := range weekdays {
		if strings.Contains(low, name) {
			diff := (int(wd) - int(today.Weekday()) + 7) % 7
			if diff == 0 {
				diff = 7
			}
			return out(today.AddDate(0, 0, diff)), low
		}
	}
	return nil, low
}

func rollForward(today time.Time, m time.Month, d int) time.Time {
	t := time.Date(today.Year(), m, d, 0, 0, 0, 0, today.Location())
	if t.Before(today) {
		t = t.AddDate(1, 0, 0)
	}
	return t
}

var (
	morningWords   = []string{"morning", "subah", "subha", "udayam", "bilaga", "सुबह", "ఉదయం", "காலை", "ಬೆಳಿಗ್ಗೆ"}
	afternoonWords = []string{"afternoon", "dopahar", "madhyahnam", "madhyahna", "mathiyam", "दोपहर", "మధ్యాహ్నం", "மதியம்", "ಮಧ್ಯಾಹ್ನ"}
	eveningWords   = []string{"evening", "shaam", "sham ", "sayantram", "saayangalam", "saayankalam", "maalai", "sanje", "शाम", "సాయంత్రం", "மாலை", "ಸಂಜೆ"}
	nightWords     = []string{"night", "raat", "ratri", "rathri", "iravu", "रात", "రాత్రి", "இரவு", "ರಾತ್ರಿ"}
	afterWords     = []string{"after", "baad", "tarvata", "taruvata", "ku mela", "ku mele", "nantara", "बाद", "తర్వాత", "பிறகு", "ನಂತರ"}
	beforeWords    = []string{"before", "pehle", "till ", "until", "by ", "tak", "पहले", "ముందు", "முன்", "ಮುಂಚೆ"}
)

// parseTime extracts a preferred time window. Only numbers adjacent to a time marker count, so house numbers
// and amounts are not misread.
func parseTime(low string) (start, end *string) {
	s := rePhone.ReplaceAllString(low, " ")
	s = rePincode.ReplaceAllString(s, " ")
	s = reLongDigit.ReplaceAllString(s, " ")
	padded := " " + s + " "
	morning, afternoon, evening, night := hasAny(padded, morningWords), hasAny(padded, afternoonWords), hasAny(padded, eveningWords), hasAny(padded, nightWords)
	isAfter, isBefore := hasAny(padded, afterWords), hasAny(padded, beforeWords)

	hour, min, explicit := -1, 0, false
	if m := reAMPM.FindStringSubmatch(s); m != nil {
		hour, _ = strconv.Atoi(m[1])
		min, _ = strconv.Atoi(m[2])
		if strings.HasPrefix(m[3], "p") && hour < 12 {
			hour += 12
		}
		if strings.HasPrefix(m[3], "a") && hour == 12 {
			hour = 0
		}
		explicit = true
	} else if m := reColon.FindStringSubmatch(s); m != nil {
		hour, _ = strconv.Atoi(m[1])
		min, _ = strconv.Atoi(m[2])
		explicit = hour >= 13 || hour == 0
	} else if m := reBaje.FindStringSubmatch(s); m != nil {
		hour, _ = strconv.Atoi(m[1])
	} else if m := reAtHour.FindStringSubmatch(s); m != nil {
		hour, _ = strconv.Atoi(m[1])
		min, _ = strconv.Atoi(m[2])
	} else if m := reBareHour.FindStringSubmatch(s); m != nil {
		hour, _ = strconv.Atoi(m[1])
	} else if morning || afternoon || evening || night {
		if m := reLoneHour.FindStringSubmatch(s); m != nil {
			hour, _ = strconv.Atoi(m[1])
		}
	}
	if hour >= 0 && hour <= 24 {
		if !explicit && hour >= 1 && hour <= 11 {
			switch {
			case evening || night || afternoon && hour < 7:
				hour += 12
			case morning:
			case hour <= 7:
				hour += 12
			}
		}
		t := hhmm(hour%24, min)
		switch {
		case isBefore && !isAfter:
			return nil, &t
		default:
			return &t, nil
		}
	}
	switch {
	case morning:
		return ptr("09:00"), ptr("12:00")
	case afternoon:
		return ptr("12:00"), ptr("16:00")
	case evening:
		return ptr("17:00"), ptr("21:00")
	}
	return nil, nil
}

func parseInstruction(low string) *string {
	var parts []string
	add := func(s string) {
		for _, p := range parts {
			if p == s {
				return
			}
		}
		parts = append(parts, s)
	}
	if hasAny(low, []string{"security", "guard", "gaurd", "watchman", "chowkidar", "chowkidaar", "gatekeeper", "सिक्योरिटी", "गार्ड"}) {
		add("Inform the security guard")
	}
	if hasAny(low, []string{"call before", "call me before", "phone before", "call karna", "pehle call", "call chesi", "call pannunga"}) {
		add("Call the consignee before arriving")
	}
	if hasAny(low, []string{"neighbour", "neighbor", "padosi"}) {
		add("Leave with a neighbour if the consignee is unavailable")
	}
	if hasAny(low, []string{"reception", "front desk", "office"}) {
		add("Hand over at the reception")
	}
	if len(parts) == 0 {
		return nil
	}
	s := strings.Join(parts, "; ")
	return &s
}

var knownCities = map[string]string{"mumbai": "Mumbai", "bombay": "Mumbai", "new delhi": "New Delhi", "delhi": "Delhi", "bengaluru": "Bengaluru", "bangalore": "Bengaluru",
	"hyderabad": "Hyderabad", "chennai": "Chennai", "kolkata": "Kolkata", "pune": "Pune", "ahmedabad": "Ahmedabad", "jaipur": "Jaipur", "lucknow": "Lucknow", "gurgaon": "Gurgaon", "gurugram": "Gurgaon", "noida": "Noida"}

func parseAddress(text, low string) (pin, city, line, landmark *string) {
	if m := rePincode.FindString(low); m != "" && !rePhone.MatchString(m) {
		pin = ptr(m)
	}
	for k, v := range knownCities {
		if regexp.MustCompile(`\b` + k + `\b`).MatchString(low) {
			if city == nil || len(k) > len(strings.ToLower(*city)) {
				city = ptr(v)
			}
		}
	}
	if m := reMapsLink.FindString(text); m != "" {
		landmark = ptr("Live location shared: " + m)
	} else if m := reLatLng.FindStringSubmatch(text); m != nil {
		landmark = ptr("Live location shared: " + m[1] + "," + m[2])
	} else if m := reLandmark.FindStringSubmatch(text); m != nil {
		landmark = ptr(cleanPhrase(m[1]))
	} else if m := reLandmarkH.FindStringSubmatch(text); m != nil {
		landmark = ptr(cleanPhrase(m[1]))
	}
	if m := reAddrLine.FindStringSubmatch(text); m != nil {
		line = ptr(cleanPhrase(m[1]))
	}
	return
}

func cleanPhrase(s string) string {
	s = strings.TrimSpace(s)
	for _, cut := range []string{" pincode", " pin ", " and ", " please", " plz", " thanks"} {
		if i := strings.Index(strings.ToLower(s), cut); i > 0 {
			s = s[:i]
		}
	}
	return strings.TrimSpace(strings.Trim(s, ".,;:- "))
}

var (
	yesWords = []string{"yes", "yeah", "yep", "haan", "han", "ha", "ji", "ok", "okay", "sure", "confirm", "correct", "sahi", "theek", "thik", "avunu", "sare", "sari", "houdu", "aama", "seri", "हाँ", "हां", "అవును", "ஆம்", "ಹೌದು"}
	noWords  = []string{"no", "nope", "nahi", "nahin", "nahi", "illa", "illai", "vendam", "beda", "ledu", "kaadu", "नहीं", "కాదు", "இல்லை", "ಇಲ್ಲ"}

	falseClaims = []string{"nobody came", "no one came", "no one called", "nobody called", "did not come", "didn't come", "didnt come", "never came", "no attempt", "was at home", "i was home",
		"koi nahi aaya", "koi nahin aaya", "koi nahi aya", "koi aaya hi nahi", "koi call nahi", "ghar pe tha", "ghar par tha", "yaarum varala", "yarum vara", "evvaru raaledu", "yaaru bandilla"}
	cancelWords = []string{"cancel", "don't want", "dont want", "do not want", "not want it", "nahi chahiye", "nahin chahiye", "mat bhejo", "wapas bhej", "send it back", "return it", "venam", "vaddu", "beda ", "रद्द", "कैंसल"}
	refuseWords = []string{"refuse", "not accept", "wont accept", "won't accept", "reject"}
	altWords    = []string{"alternate", "alternative", "another number", "other number", "alt number", "dusra number", "doosra number", "different number"}
	noCashWords = []string{"no cash", "don't have cash", "dont have cash", "do not have cash", "cash nahi", "paise nahi", "paisa nahi", "money not ready", "cash is not ready", "not have money", "cash illa", "dabbu ledu", "panam illai"}
	payOnline   = []string{"online", "upi", "prepaid", "pay now", "payment link", "send link", "link bhej", "link pampandi", "link anuppunga"}
	paidWords   = []string{"paid", "payment done", "payment complete", "pay kar diya", "bhugtan ho gaya", "payment ho gaya", "kattiten", "chellinchanu"}
	cashReady   = []string{"cash ready", "have cash", "will pay cash", "paise ready", "paise hain", "cash hai"}
	reattempt   = []string{"try again", "reattempt", "re-attempt", "deliver again", "come again", "send again", "dobara", "phir se", "fir se", "once more", "again please", "please deliver", "mala vanga", "malli ra"}
	thanksOnly  = []string{"thanks", "thank you", "thankyou", "dhanyavad", "shukriya", "dhanyavadalu", "nandri", "dhanyavada"}
	weakCome    = []string{"come", "aana", "aao", "ravali", "vaanga", "bannu", "barbeku", "ravandi"}
)

func isShortExact(low string, set []string) bool {
	toks := strings.Fields(strings.Trim(splitRe.ReplaceAllString(low, " "), " "))
	if len(toks) == 0 || len(toks) > 3 {
		return false
	}
	for _, t := range toks {
		found := false
		for _, w := range set {
			if t == w {
				found = true
				break
			}
		}
		if !found && t != "please" && t != "plz" && t != "thanks" && t != "ji" {
			return false
		}
	}
	return true
}

// ExtractIntent implements deterministic keyword/regex NLU for English, Hindi/Telugu/Tamil/Kannada in native
// script and in Romanized/code-mixed form. Confidence is lowered for weak signals so the rules engine asks
// the buyer to confirm instead of acting.
func (m *MockLLMProvider) ExtractIntent(_ context.Context, text string, ic IntentContext) (domain.ExtractedIntent, error) {
	low := strings.ToLower(strings.TrimSpace(text))
	lang, lconf := DetectLanguage(text)
	out := domain.ExtractedIntent{Intent: domain.IntentUnknown, Confidence: 0.2, DetectedLanguage: lang, LanguageConfidence: lconf}
	now := ic.Now.In(time.FixedZone("IST", 5*3600+1800))
	finish := func(i domain.IntentType, conf float64) (domain.ExtractedIntent, error) {
		out.Intent, out.Confidence = i, conf
		out.InternalSummary = summary(out)
		return out, nil
	}
	if low == "" {
		return finish(domain.IntentUnknown, 0.0)
	}

	date, rest := parseDate(low, now)
	out.PreferredDate = date
	out.PreferredTimeStart, out.PreferredTimeEnd = parseTime(rest)
	out.SpecialInstruction = parseInstruction(low)
	phone := rePhone.FindString(low)
	if phone != "" {
		out.NewPhone = ptr(phone)
	}
	pin, city, line, landmark := parseAddress(text, low)
	out.NewPincode, out.NewCity, out.NewAddressLine, out.Landmark = pin, city, line, landmark
	hasDateTime := out.PreferredDate != nil || out.PreferredTimeStart != nil || out.PreferredTimeEnd != nil

	switch {
	case isShortExact(low, yesWords):
		return finish(domain.IntentConfirmYes, 0.95)
	case isShortExact(low, noWords):
		return finish(domain.IntentConfirmNo, 0.95)
	case hasAny(low, falseClaims):
		return finish(domain.IntentFalseAttempt, 0.9)
	case hasAny(low, cancelWords):
		return finish(domain.IntentCancelOrder, 0.93)
	case hasAny(low, refuseWords):
		return finish(domain.IntentRefuseOrder, 0.8)
	case phone != "" && (hasAny(low, altWords) || ic.Reason == domain.ReasonPhoneUnreachable):
		return finish(domain.IntentAlternateContact, 0.92)
	case phone != "" && !hasDateTime:
		return finish(domain.IntentPhoneUpdate, 0.9)
	case hasAny(low, paidWords):
		return finish(domain.IntentPaymentDone, 0.9)
	case hasAny(low, noCashWords):
		return finish(domain.IntentCODNotReady, 0.9)
	case hasAny(low, payOnline):
		return finish(domain.IntentPayOnline, 0.9)
	case isAddressMessage(ic, out, low):
		return finish(domain.IntentAddressCorrection, 0.9)
	case hasAny(low, cashReady) && !hasDateTime:
		return finish(domain.IntentCODReady, 0.85)
	case hasDateTime && (out.PreferredDate != nil && (out.PreferredTimeStart != nil || out.PreferredTimeEnd != nil)):
		return finish(domain.IntentRescheduleDelivery, 0.96)
	case hasDateTime:
		return finish(domain.IntentRescheduleDelivery, 0.9)
	case hasAny(low, reattempt):
		return finish(domain.IntentReattempt, 0.88)
	case hasAny(low, thanksOnly):
		return finish(domain.IntentNoAction, 0.9)
	case hasAny(" "+low+" ", paddedWords(weakCome)):
		return finish(domain.IntentReattempt, 0.55) // "please come" with no when: ask the buyer to confirm
	case lang != "" && lconf < 0.5:
		return finish(domain.IntentUnknown, 0.3)
	}
	return finish(domain.IntentUnknown, 0.2)
}

func paddedWords(ws []string) []string {
	out := make([]string, len(ws))
	for i, w := range ws {
		out[i] = " " + w + " "
	}
	return out
}

func isAddressMessage(ic IntentContext, o domain.ExtractedIntent, low string) bool {
	strong := o.NewPincode != nil || o.Landmark != nil || o.NewAddressLine != nil
	if !strong {
		return false
	}
	if ic.Reason == domain.ReasonAddressIssue {
		return true
	}
	// outside an address-related NDR, an address change needs an explicit signal, not just a mention of "gate"
	if o.PreferredDate != nil || o.PreferredTimeStart != nil {
		return false
	}
	return o.NewPincode != nil || hasAny(low, []string{"address", "pata", "pincode", "chirunama", "mugavari", "vilasa"}) || o.NewAddressLine != nil
}

func summary(i domain.ExtractedIntent) string {
	parts := []string{strings.ReplaceAll(strings.ToLower(string(i.Intent)), "_", " ")}
	if i.PreferredDate != nil {
		parts = append(parts, "date "+*i.PreferredDate)
	}
	switch {
	case i.PreferredTimeStart != nil && i.PreferredTimeEnd != nil:
		parts = append(parts, "between "+*i.PreferredTimeStart+" and "+*i.PreferredTimeEnd)
	case i.PreferredTimeStart != nil:
		parts = append(parts, "after "+*i.PreferredTimeStart)
	case i.PreferredTimeEnd != nil:
		parts = append(parts, "before "+*i.PreferredTimeEnd)
	}
	if i.NewPhone != nil {
		parts = append(parts, "new phone")
	}
	if i.NewPincode != nil {
		parts = append(parts, "pincode "+*i.NewPincode)
	}
	if i.NewCity != nil {
		parts = append(parts, "city "+*i.NewCity)
	}
	if i.Landmark != nil {
		parts = append(parts, "landmark: "+*i.Landmark)
	}
	if i.SpecialInstruction != nil {
		parts = append(parts, "instruction: "+*i.SpecialInstruction)
	}
	return strings.Join(parts, "; ")
}

// InterpretRemark maps messy carrier free text (when the reason code is generic like OTHER) to the taxonomy.
func (*MockLLMProvider) InterpretRemark(_ context.Context, remark string) (domain.NDRReason, float64, error) {
	low := strings.ToLower(remark)
	rules := []struct {
		r domain.NDRReason
		w []string
	}{
		{domain.ReasonCustRefused, []string{"refus", "rejected by", "not accept", "denied delivery"}},
		{domain.ReasonAddressIssue, []string{"address", "landmark", "wrong pin", "could not locate", "cannot locate", "house not found"}},
		{domain.ReasonPhoneUnreachable, []string{"switched off", "not reachable", "unreachable", "no answer", "not picking", "phone"}},
		{domain.ReasonCODNotReady, []string{"cash", "cod not", "payment not ready", "money"}},
		{domain.ReasonFutureDelivery, []string{"future", "later date", "reschedule", "next week", "requested delivery on"}},
		{domain.ReasonAccessRestricted, []string{"security", "gate", "society", "entry not", "not allowed", "restricted"}},
		{domain.ReasonOutOfArea, []string{"out of area", "outside", "not serviceable", "oda", "beyond delivery"}},
		{domain.ReasonSuspectFalse, []string{"anomaly", "location mismatch", "geo", "suspect"}},
		{domain.ReasonCustUnavailable, []string{"not available", "unavailable", "door locked", "closed", "not at home", "office closed", "consignee not", "customer not"}},
	}
	for _, r := range rules {
		if hasAny(low, r.w) {
			return r.r, 0.85, nil
		}
	}
	return domain.ReasonCustUnavailable, 0.3, nil
}

// ComposeMessage renders a localized template. A real LLM provider could paraphrase while preserving the
// semantic key's meaning; the mock keeps messages fully deterministic and auditable.
func (*MockLLMProvider) ComposeMessage(_ context.Context, key, lang string, params map[string]string) (string, error) {
	return Render(key, lang, params), nil
}
