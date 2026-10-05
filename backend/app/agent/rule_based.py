"""A deterministic, slot-filling agent. No LLM: enough to demo the full flow and exercise the tools.

It only understands: pickup/delivery pincode, weight, prepaid/COD (+amount), "book <carrier>", "where is my shipment".
"""
import re
from datetime import datetime

from app.agent.provider import AgentProvider, Conversation
from app.agent.tools import ZippyTools

PIN = r"\b[1-9]\d{5}\b"
WEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(kgs?|kilos?|kilograms?|grams?|gms?|g)\b", re.I)
MONEY = re.compile(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d+)?)", re.I)
RESET = re.compile(r"\b(start over|cancel|new shipment|another (parcel|shipment)|new parcel)\b", re.I)
TRACK = re.compile(r"\b(track|tracking|where|status|reach|delivered|arrive|update)\b", re.I)
BOOK = re.compile(r"\b(book|select|choose|go with|go for|take|confirm|ship with)\b|\boption\s*\d|^\s*\d\s*$|cheapest|fastest", re.I)
START = re.compile(r"\b(send|ship|parcel|package|courier|deliver)\b", re.I)

CARRIER_WORDS = {"fastship": "FASTSHIP", "fast ship": "FASTSHIP", "quick": "QUICKEXPRESS", "reliable": "RELIABLE"}
QUESTIONS = {
    "pickup": "What is the pickup pincode?",
    "delivery": "What is the delivery pincode?",
    "weight": "What is the package weight?",
    "payment": "Is this prepaid or COD? (For COD, include the amount to collect, e.g. COD ₹2000)",
    "cod_amount": "What amount should be collected on delivery (COD)?",
}


def _pretty(status: str) -> str:
    return status.replace("_", " ").lower()


class RuleBasedAgentProvider(AgentProvider):
    async def respond(self, conv: Conversation, message: str, tools: ZippyTools) -> str:
        st = conv.state
        text = message.strip()

        if RESET.search(text):
            st.clear()
            if not START.search(text) and not re.search(PIN, text):
                return "Okay, starting fresh. What is the pickup pincode?"

        # --- tracking questions can come at any time once a shipment exists
        if TRACK.search(text) and not BOOK.search(text) and not re.search(PIN, text):
            return await self._tracking(st, tools)

        if st.get("stage") == "offered" and BOOK.search(text):
            return await self._book(conv, text, tools)

        if st.get("stage") in ("offered", "booked"):
            if st.get("stage") == "booked" and not START.search(text):
                return "Your shipment is booked. Ask me 'where is my shipment?' any time, or say 'new shipment' to send another parcel."
            if st.get("stage") == "offered":
                return "Tell me which option to book (e.g. 'Book FastShip' or 'option 2'), or say 'start over'."
            st.clear()

        if not st.get("stage") and not (START.search(text) or re.search(PIN, text)):
            return "Hi! I can help you ship a parcel and track it. Say something like 'I want to send a parcel'."

        st["stage"] = "collecting"
        self._extract(st, text)
        missing = self._next_missing(st)
        if missing:
            st["awaiting"] = missing
            return ("Sure. " if len(conv.history) <= 1 else "") + QUESTIONS[missing]
        return await self._quote(conv, tools)

    # ------------------------------------------------------------------ slot filling
    def _extract(self, st: dict, text: str) -> None:
        awaiting = st.pop("awaiting", None)
        rest = text

        m = re.search(rf"from\s+({PIN}).*?\bto\s+({PIN})", rest, re.I | re.S)
        if m:
            st["pickup"], st["delivery"] = m.group(1), m.group(2)
        else:
            for pin in re.findall(PIN, rest):
                slot = "pickup" if "pickup" not in st else "delivery" if "delivery" not in st else None
                if slot:
                    st[slot] = pin
        rest = re.sub(PIN, " ", rest)

        w = WEIGHT.search(rest)
        if w:
            qty, unit = float(w.group(1)), w.group(2).lower()
            st["weight_grams"] = int(qty * 1000) if unit.startswith(("k")) else int(qty)
            rest = rest.replace(w.group(0), " ")
        elif awaiting == "weight":
            n = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", rest)
            if n:
                v = float(n.group(1))
                st["weight_grams"] = int(v * 1000) if v <= 50 else int(v)

        if re.search(r"\bcod\b|cash on delivery", rest, re.I):
            st["payment_type"] = "COD"
        elif re.search(r"pre-?paid|already paid|online", rest, re.I):
            st["payment_type"] = "PREPAID"
            st["cod_amount"] = 0

        if st.get("payment_type") == "COD" and not st.get("cod_amount"):
            money = MONEY.search(rest) or re.search(r"cod\D{0,15}?(\d[\d,]*(?:\.\d+)?)", rest, re.I)
            if not money and awaiting in ("cod_amount", "payment"):
                money = re.search(r"(\d[\d,]*(?:\.\d+)?)", rest)
            if money:
                st["cod_amount"] = float(money.group(1).replace(",", ""))

    @staticmethod
    def _next_missing(st: dict) -> str | None:
        if "pickup" not in st:
            return "pickup"
        if "delivery" not in st:
            return "delivery"
        if "weight_grams" not in st:
            return "weight"
        if "payment_type" not in st:
            return "payment"
        if st["payment_type"] == "COD" and not st.get("cod_amount"):
            return "cod_amount"
        return None

    # ------------------------------------------------------------------ actions
    async def _quote(self, conv: Conversation, tools: ZippyTools) -> str:
        st = conv.state
        if not st.get("order_id"):
            order = await tools.call(
                "create_order",
                customer_name=conv.customer_name, customer_phone=conv.customer_phone,
                pickup_pincode=st["pickup"], delivery_pincode=st["delivery"], weight_grams=st["weight_grams"],
                payment_type=st["payment_type"], cod_amount=st.get("cod_amount", 0),
            )
            if "error" in order:
                st.clear()
                return f"Sorry, I couldn't create the order: {order['message']}"
            st["order_id"] = order["orderId"]
        res = await tools.call("get_shipping_rates", order_id=st["order_id"])
        options = res.get("options", [])
        if not options:
            st["stage"] = "collecting"
            return "Sorry, none of our carriers could quote this shipment right now. Please try again in a minute."
        st["options"], st["stage"] = options, "offered"

        lines = [
            f"{i}. {o['carrierName']} – {o['serviceName']}: ₹{o['totalCharge']:g}, "
            f"{self._eta(o)}"
            for i, o in enumerate(options, 1)
        ]
        note = ""
        if res.get("failedCarriers"):
            note = "\n(Couldn't reach: " + ", ".join(f["carrierName"] for f in res["failedCarriers"]) + ".)"
        return (
            f"I found {len(options)} shipping options (cheapest first):\n" + "\n".join(lines) + note
            + "\nWhich one should I book? e.g. 'Book FastShip'."
        )

    @staticmethod
    def _eta(o: dict) -> str:
        lo, hi = o["estimatedMinDays"], o["estimatedMaxDays"]
        if lo is None:
            return "delivery time n/a"
        return f"{lo} day{'s' if lo != 1 else ''}" if lo == hi else f"{lo}-{hi} days"

    def _choose(self, text: str, options: list[dict]) -> tuple[dict | None, bool]:
        """Returns (option, was_ambiguous)."""
        t = text.lower()
        m = re.search(r"option\s*(\d)|^\s*(\d)\s*$", t)
        if m:
            i = int(m.group(1) or m.group(2))
            return (options[i - 1], False) if 1 <= i <= len(options) else (None, False)
        if "cheapest" in t:
            return options[0], False
        if "fastest" in t:
            return min(options, key=lambda o: (o["estimatedMinDays"] or 99, o["totalCharge"])), False
        codes = {code for word, code in CARRIER_WORDS.items() if word in t}
        cands = [o for o in options if o["carrierCode"] in codes] if codes else []
        if not cands:
            return None, False
        words = [w for w in ("air", "surface", "express") if w in t]
        narrowed = [o for o in cands if any(w in o["serviceName"].lower() for w in words)] if words else []
        pool = narrowed or cands
        return pool[0], len(pool) > 1 and not narrowed  # options are sorted cheapest first

    async def _book(self, conv: Conversation, text: str, tools: ZippyTools) -> str:
        st = conv.state
        opt, ambiguous = self._choose(text, st["options"])
        if opt is None:
            return "Sorry, I didn't catch which option. Say e.g. 'Book FastShip' or 'option 2'."

        sel = await tools.call(
            "select_carrier", order_id=st["order_id"], carrier_code=opt["carrierCode"],
            service_code=opt["serviceCode"], quoted_amount=opt["totalCharge"],
        )
        if sel.get("error") in ("QUOTE_EXPIRED", "STALE_QUOTE"):
            res = await tools.call("get_shipping_rates", order_id=st["order_id"], refresh=True)
            st["options"] = res.get("options", [])
            return "Those rates had expired, so I refreshed them. Please pick again:\n" + "\n".join(
                f"{i}. {o['carrierName']} – {o['serviceName']}: ₹{o['totalCharge']:g}" for i, o in enumerate(st["options"], 1)
            )
        if "error" in sel:
            return f"Sorry, I couldn't select that option: {sel['message']}"

        ship = await tools.call("create_shipment", order_id=st["order_id"])
        if "error" in ship:
            return f"I selected {opt['carrierName']} but booking failed: {ship['message']} Say 'book {opt['carrierName']}' to retry."
        st["stage"] = "booked"
        extra = f" (There were several {opt['carrierName']} services; I picked the cheaper one: {opt['serviceName']}.)" if ambiguous else ""
        return (
            f"Done. Your {opt['carrierName']} shipment is booked. Tracking number: {ship['trackingNumber']}. "
            f"Charge: ₹{opt['totalCharge']:g}.{extra}"
        )

    async def _tracking(self, st: dict, tools: ZippyTools) -> str:
        if not st.get("order_id"):
            return "I don't have a shipment for you yet. Say 'I want to send a parcel' to start one."
        t = await tools.call("get_tracking", order_id=st["order_id"])
        if "error" in t:
            return "Your shipment isn't booked yet. Tell me which option to book and I'll create it."
        last = t["history"][-1] if t["history"] else {}
        where = f" at {last['location']}" if last.get("location") else ""
        when = ""
        if last.get("timestamp"):
            when = " (" + datetime.fromisoformat(last["timestamp"]).strftime("%d %b, %H:%M UTC") + ")"
        trail = " → ".join(_pretty(h["status"]) for h in t["history"])
        return (
            f"Your shipment {t['trackingNumber']} is {_pretty(t['currentStatus'])}{where}{when}. "
            f"Progress so far: {trail}."
        )
