import { FeatureTabs, type Tab } from "./components/FeatureTabs";
import { SiteHeader } from "./components/SiteHeader";
import { Testimonials } from "./components/Testimonials";
import { Advantages, Chips, Cta, Flow, Hero, LogoMarquee, SiteFooter, Stats, WideBand } from "./components/Sections";

const SHIP_TABS: Tab[] = [
  { title: "Compare every carrier at once", body: "Quotes from all connected carriers arrive together, sorted by total. If one carrier is down you still get the rest.",
    panel: { title: "Rates", rows: [["Cheapest · ReliableCourier", "₹ 79"], ["Fastest · QuickExpress", "1 day"], ["Failed carriers", "0"]] } },
  { title: "Book with confidence", body: "The quote you select is checked against the latest batch and its expiry, then booked exactly once.",
    panel: { title: "Booking", rows: [["Status", "BOOKED"], ["Tracking no.", "FS-20931"], ["Charged", "₹ 84"]] } },
  { title: "Track on one timeline", body: "Each carrier's webhook format is normalised into the same set of statuses for your team and your buyers.",
    panel: { title: "Tracking", rows: [["Now", "OUT_FOR_DELIVERY"], ["09:12", "IN_TRANSIT"], ["Yesterday", "PICKED_UP"]] } },
];

const AGENT_TABS: Tab[] = [
  { title: "Answer on WhatsApp", body: "Buyers and ops staff ask for a price or a status in plain words; the agent replies using the same services as the dashboard.",
    panel: { title: "WhatsApp", rows: [["You", "Rate for order 42?"], ["Zippy", "Cheapest is ₹ 79 (3 days)"], ["You", "Book it"]] } },
  { title: "Pick up the phone", body: "The voice channel reuses the agent, so every rule that protects bookings applies to calls too.",
    panel: { title: "Voice call", rows: [["Caller", "Where is my parcel?"], ["Zippy", "Out for delivery today"], ["Duration", "0:41"]] } },
  { title: "Swap in an LLM later", body: "Today's rule-based agent sits behind a provider interface, ready to be replaced without touching carriers.",
    panel: { title: "Agent provider", rows: [["Active", "rule_based"], ["Tools", "rates · book · track"], ["Carrier access", "via services only"]] } },
];

const QUOTES = [
  { name: "Ops lead", role: "D2C apparel brand", text: "We stopped copy-pasting quotes from three portals. The cheapest option is just there." },
  { name: "Founder", role: "Electronics marketplace", text: "Retries used to double-book. With Zippy a retry gives us back the same tracking number." },
  { name: "Support manager", role: "Home goods store", text: "Customers ask on WhatsApp and get a real status in seconds." },
  { name: "Warehouse head", role: "3PL partner", text: "One timeline for every carrier made our daily exception review short." },
];

export default function SitePage() {
  return (
    <>
      <SiteHeader />
      <main>
        <Hero />
        <LogoMarquee />
        <FeatureTabs heading="Shipping, from quote to doorstep" tabs={SHIP_TABS} />
        <FeatureTabs heading="An agent your customers can talk to" tabs={AGENT_TABS} side="right" />
        <WideBand heading="Ready for every kind of shipment" tone="ink">
          <Chips items={["D2C", "B2B", "Marketplaces", "Cash on delivery", "Same-day", "Heavy parcels"]} />
        </WideBand>
        <Testimonials quotes={QUOTES} />
        <WideBand heading="How Zippy fits together" tone="ink-2"><Flow /></WideBand>
        <Advantages />
        <Stats />
        <Cta />
      </main>
      <SiteFooter />
    </>
  );
}
