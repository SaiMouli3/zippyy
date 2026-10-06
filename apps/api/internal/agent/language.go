package agent

import (
	"regexp"
	"strings"
	"unicode"
)

// Romanized (Latin-script) keyword lexicons. They are intentionally small: the mock provider only needs to
// be convincing on the demo phrases and degrade safely (unknown -> keep the current case language).
var romanLexicon = map[string]map[string]bool{
	"hi": words("kal aaj parso subah shaam dopahar raat baje baad ke aana aao bhej dena dijiye mujhe mera meri nahi nahin haan ji kripya bolna bol hai hain ho karo kar karna chahiye wapas paise ghar aap aapka mein pe par se ko ka ki rakhna mat bhai dobara phir fir koi aaya aayi tha thi paas saamne pehle mujhse number"),
	"te": words("repu ravali ravandi kavali ledu ela nenu naaku naa mee meeru tarvata taruvata ghantalaku ocharu pampandi avunu sare ippudu sayantram udayam rathri cheppandi ra undi ledhu kaadu randi cheyyandi vachi"),
	"ta": words("naalai naalaikku venum vendam illai illa enakku ungal neenga neengal saayangalam kaalai anuppunga seri aama ippo varavum pannunga irukku ennoda mathiyam yaarum varala vanga thaan"),
	"kn": words("naale beku beda illa nanage nimma neevu sanje bilaga madhyahna kalisi sari houdu ippa bandu hakbeku annu maadi ide nanna yaaru bandilla barbeku nantara mundu"),
	"en": words("tomorrow today please come deliver after before evening morning afternoon tell security guard gate address cancel order pay cash yes no nobody the my is not want will can at on to send phone number landmark near call again try delivery i you it me thanks thank ok okay home was nothing anyone"),
}

func words(s string) map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(s) {
		m[w] = true
	}
	return m
}

var splitRe = regexp.MustCompile(`[^\p{L}\p{N}']+`)

// DetectLanguage returns an ISO code and a 0..1 confidence. Non-Latin scripts are decisive; Latin text is
// scored against the romanized lexicons. Empty result means "no signal" and callers keep the case language.
func DetectLanguage(text string) (string, float64) {
	var dev, tel, tam, kan, latin int
	for _, r := range text {
		switch {
		case unicode.Is(unicode.Devanagari, r):
			dev++
		case unicode.Is(unicode.Telugu, r):
			tel++
		case unicode.Is(unicode.Tamil, r):
			tam++
		case unicode.Is(unicode.Kannada, r):
			kan++
		case unicode.Is(unicode.Latin, r):
			latin++
		}
	}
	script := map[string]int{"hi": dev, "te": tel, "ta": tam, "kn": kan}
	best, bn := "", 0
	for l, n := range script {
		if n > bn {
			best, bn = l, n
		}
	}
	if bn > 0 && bn >= latin/2 {
		return best, 0.99
	}
	toks := splitRe.Split(strings.ToLower(text), -1)
	score := map[string]int{}
	total := 0
	for _, t := range toks {
		if t == "" {
			continue
		}
		total++
		for l, lex := range romanLexicon {
			if lex[t] {
				score[l]++
			}
		}
	}
	best, bn = "", 0
	second := 0
	for _, l := range []string{"hi", "te", "ta", "kn", "en"} { // deterministic tie-break order
		n := score[l]
		if n > bn {
			second = bn
			best, bn = l, n
		} else if n > second {
			second = n
		}
	}
	if bn == 0 || total == 0 {
		return "", 0
	}
	// english words co-occur in code-mixed text; a non-English lexicon with >=1 hit beats english unless english dominates
	if best == "en" {
		for _, l := range []string{"hi", "te", "ta", "kn"} {
			if score[l] >= 2 && score[l]*2 >= score["en"] {
				best, bn = l, score[l]
			}
		}
	}
	conf := 0.55 + 0.4*float64(bn)/float64(total)
	if bn == second {
		conf -= 0.2
	}
	if conf > 0.98 {
		conf = 0.98
	}
	return best, conf
}

// LanguageName is used for UI/audit text.
func LanguageName(code string) string {
	switch code {
	case "hi":
		return "Hindi"
	case "te":
		return "Telugu"
	case "ta":
		return "Tamil"
	case "kn":
		return "Kannada"
	}
	return "English"
}

// PincodeLanguage is the last-resort default by pincode prefix.
func PincodeLanguage(pin string) string {
	if len(pin) < 2 {
		return "en"
	}
	switch pin[:2] {
	case "56", "57", "58", "59":
		return "kn"
	case "50", "51", "52", "53":
		return "te"
	case "60", "61", "62", "63", "64":
		return "ta"
	case "11", "12", "13", "14", "20", "21", "22", "23", "24", "25", "26", "27", "28", "30", "31", "32", "33", "34", "45", "46", "47", "48", "80", "81", "82", "83", "84", "85":
		return "hi"
	}
	return "en"
}
