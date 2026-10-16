import { Button } from "./Button";
import { MockPanel } from "./MockPanel";

export function Hero() {
  return (
    <section className="relative overflow-hidden bg-zy-ink pt-20">
      <div className="pointer-events-none absolute -right-40 top-10 h-[500px] w-[500px] rounded-full bg-[radial-gradient(circle,rgba(213,64,41,.35)_0%,rgba(213,64,41,.11)_50%,transparent_75%)]" />
      <div className="relative mx-auto flex max-w-zy flex-col items-center gap-12 px-5 py-16 lg:flex-row lg:px-[60px] lg:py-[100px]">
        <div className="lg:w-1/2 lg:pr-[60px]">
          <h1 className="font-heading text-4xl font-semibold leading-[1.5] text-white lg:text-5xl lg:leading-[76px]">
            One agent for every carrier you ship with
          </h1>
          <p className="mt-6 text-base leading-[26px] text-white">
            Zippy asks every carrier for a price at the same time, books the one you pick exactly once,
            and turns their different tracking feeds into one clean timeline.
          </p>
          <Button href="/orders" className="mt-8">Get started</Button>
        </div>
        <div className="w-full lg:w-1/2">
          <MockPanel title="Quotes · 560001 → 400001 · 1.2 kg" rows={[["FastShip · 2 days", "₹ 84"], ["QuickExpress · 1 day", "₹ 112"], ["ReliableCourier · 3 days", "₹ 79 · COD fee ₹ 30"]]} />
        </div>
      </div>
    </section>
  );
}

const PARTNERS = ["FastShip", "QuickExpress", "ReliableCourier", "Your ERP", "Shopify store", "WhatsApp", "Voice IVR", "Webhooks"];

export function LogoMarquee() {
  return (
    <section className="bg-zy-paper px-5 py-16 lg:px-[60px] lg:pt-[100px]">
      <h2 className="text-center font-heading text-[28px] font-semibold leading-[1.5] text-black lg:text-5xl">Plugs into the tools you already run</h2>
      <div className="mt-10 overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_10%,#000_90%,transparent)]">
        <div className="flex w-max animate-marquee gap-16">
          {[...PARTNERS, ...PARTNERS].map((p, i) => (
            <span key={i} className="whitespace-nowrap font-heading text-2xl font-bold text-zy-muted">{p}</span>
          ))}
        </div>
      </div>
    </section>
  );
}

export function WideBand({ heading, tone, children }: { heading: string; tone: "ink" | "ink-2"; children: React.ReactNode }) {
  return (
    <section className={`${tone === "ink" ? "bg-zy-ink" : "bg-zy-ink-2"} relative overflow-hidden px-5 py-16 lg:px-[60px] lg:py-[100px]`}>
      <div className="pointer-events-none absolute inset-0 opacity-[.07] [background-image:repeating-linear-gradient(135deg,#fff_0_1px,transparent_1px_48px)]" />
      <h2 className="relative text-center font-heading text-[26px] font-bold leading-[1.5] text-white lg:text-5xl lg:leading-[80px]">{heading}</h2>
      <div className="relative mx-auto mt-10 max-w-zy">{children}</div>
    </section>
  );
}

export function Chips({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap justify-center gap-4">
      {items.map((s) => (
        <span key={s} className="rounded-xl border border-white/15 bg-white/5 px-6 py-4 font-heading text-lg text-white">{s}</span>
      ))}
    </div>
  );
}

export function Flow() {
  const steps = ["WhatsApp / voice", "Zippy agent", "Rates · Book · Track", "Carrier adapters", "Carriers"];
  return (
    <div className="flex flex-col items-center gap-3 lg:flex-row lg:justify-center">
      {steps.map((s, i) => (
        <div key={s} className="flex flex-col items-center gap-3 lg:flex-row">
          <span className={`rounded-xl px-6 py-4 font-heading font-semibold ${i === 1 ? "bg-zy-brand text-white" : "bg-white/10 text-white"}`}>{s}</span>
          {i < steps.length - 1 && <span className="text-zy-brand">→</span>}
        </div>
      ))}
    </div>
  );
}

const ADVANTAGES = [
  { title: "Parallel quotes", body: "Every carrier is asked at once with its own timeout; a slow one never blocks the rest.", offset: "lg:mb-[94px]" },
  { title: "Price you saw is price you pay", body: "Bookings copy the stored quote, and expired or stale quotes are refused.", offset: "lg:mb-[112px]" },
  { title: "Book once", body: "Booking is idempotent, so a retry returns the same tracking number.", offset: "lg:mb-[106px]" },
  { title: "Clean timelines", body: "Duplicate or backwards carrier events are recognised and ignored.", offset: "lg:mb-[96px]" },
];

export function Advantages() {
  return (
    <section className="bg-zy-paper px-5 py-10 lg:px-[60px]">
      <h2 className="text-center font-heading text-[26px] font-semibold text-zy-ink lg:text-5xl">Why Zippy</h2>
      <div className="mx-auto mt-12 grid max-w-zy items-end gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {ADVANTAGES.map((a, i) => (
          <article key={a.title} className={`rounded-[14px] p-7 shadow-zy-card ${i % 2 ? "bg-white" : "bg-zy-ink text-white"} ${a.offset}`}>
            <span className="font-heading text-sm font-bold text-zy-brand">0{i + 1}</span>
            <h3 className="mt-3 font-heading text-xl font-bold">{a.title}</h3>
            <p className={`mt-3 text-[15px] leading-normal ${i % 2 ? "text-zy-ink-3" : "text-white/80"}`}>{a.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

const STATS = [["3", "Carriers connected"], ["5 min", "Rate cache TTL"], ["15 min", "Quote validity"], ["1×", "Bookings per order"], ["2", "Agent channels"]];

export function Stats() {
  return (
    <section id="pricing" className="bg-zy-paper px-5 pb-20 lg:px-[60px]">
      <div className="mx-auto max-w-zy">
        <h2 className="font-heading text-[26px] font-semibold text-black lg:text-5xl">Built for scale from day one</h2>
        <div className="mt-10 flex flex-wrap gap-x-16 gap-y-8">
          {STATS.map(([n, l]) => (
            <div key={l}>
              <div className="font-heading text-[37px] font-semibold text-black">{n}</div>
              <div className="text-[13px] text-black">{l}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Cta() {
  return (
    <section id="agent" className="relative isolate overflow-hidden bg-zy-ink px-5 py-20 lg:p-[133px]">
      <div className="absolute -bottom-[237px] -left-[123px] -z-10 h-[500px] w-[500px] bg-[radial-gradient(circle,rgba(213,64,41,.55)_0%,rgba(213,64,41,.35)_25%,rgba(213,64,41,.11)_50%,transparent_75%)]" />
      <div className="absolute right-12 top-[42%] hidden h-24 w-24 rounded-full border border-white/20 lg:block" />
      <div className="flex flex-col items-center text-center">
        <h2 className="font-heading text-[26px] font-semibold capitalize leading-[35px] text-white lg:text-5xl lg:leading-[58px]">See Zippy work on a live order</h2>
        <p className="mt-7 max-w-[300px] font-accent text-[15px] leading-5 text-zy-muted-warm">Create an order, compare quotes and book it in under a minute.</p>
        <div className="mt-7 flex flex-wrap justify-center gap-5">
          <Button href="/orders">See it live →</Button>
          <Button href="/mock">Carrier sandbox →</Button>
        </div>
      </div>
    </section>
  );
}

const FOOTER = [
  { title: "Platform", links: [["Orders", "/orders"], ["Carrier sandbox", "/mock"]] },
  { title: "Product", links: [["Rates", "#platform"], ["Tracking", "#platform"], ["Agent", "#agent"]] },
  { title: "Company", links: [["Customers", "#customers"], ["Pricing", "#pricing"]] },
];

export function SiteFooter() {
  return (
    <footer className="relative overflow-hidden bg-zy-ink">
      <div className="mx-auto grid max-w-[1174px] grid-cols-2 gap-x-12 gap-y-10 px-6 py-12 md:grid-cols-4">
        <div className="col-span-2 md:col-span-1">
          <span className="font-heading text-2xl font-bold text-white">zippy<span className="text-zy-brand">.</span></span>
        </div>
        {FOOTER.map((c) => (
          <div key={c.title}>
            <span className="font-heading text-[21px] font-bold text-white">{c.title}</span>
            <ul className="mt-4 space-y-3">
              {c.links.map(([l, h]) => (
                <li key={l}><a href={h} className="font-heading text-sm text-white transition-all duration-500 hover:text-zy-brand">{l}</a></li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="bg-[linear-gradient(90deg,#D54029_0%,#121212_100%)] py-5 text-center text-sm text-white">
        © {new Date().getFullYear()} Zippy
      </div>
    </footer>
  );
}
