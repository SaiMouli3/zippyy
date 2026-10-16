"use client";

import Link from "next/link";
import { useState } from "react";
import { Button } from "./Button";

type Item = { title: string; desc: string; href: string };
const SOLUTIONS: { group: string; items: Item[] }[] = [
  { group: "Ship", items: [
    { title: "Rate comparison", desc: "Live quotes from every connected carrier, sorted by price and speed.", href: "/orders" },
    { title: "Booking", desc: "Book the chosen quote once; retries never double-book.", href: "/orders" },
  ] },
  { group: "Track", items: [
    { title: "Unified tracking", desc: "One normalised timeline, whatever the carrier sends.", href: "/orders" },
    { title: "Carrier webhooks", desc: "Duplicate and out-of-order events handled for you.", href: "/mock" },
  ] },
  { group: "Automate", items: [
    { title: "WhatsApp agent", desc: "Customers ask for quotes and status in a chat.", href: "#agent" },
    { title: "Voice agent", desc: "The same tools, reachable over a phone call.", href: "#agent" },
  ] },
];
const NAV = [
  { label: "Platform", href: "#platform" },
  { label: "Customers", href: "#customers" },
  { label: "Pricing", href: "#pricing" },
];

export function SiteHeader() {
  const [menu, setMenu] = useState(false);
  const [mobile, setMobile] = useState(false);

  return (
    <header className="fixed inset-x-0 top-0 z-50 bg-zy-ink px-4 lg:px-[60px]">
      <div className="mx-auto flex h-20 max-w-zy items-center justify-between">
        <Link href="/site" className="font-heading text-2xl font-bold text-white">
          zippy<span className="text-zy-brand">.</span>
        </Link>

        <button className="text-zy-brand lg:hidden" aria-label="Toggle menu" aria-expanded={mobile} onClick={() => setMobile(!mobile)}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>

        <nav className={`${mobile ? "flex" : "hidden"} absolute inset-x-0 top-20 flex-col gap-5 bg-zy-ink px-4 pb-6 lg:static lg:ml-20 lg:flex lg:flex-1 lg:flex-row lg:items-center lg:gap-5 lg:p-0`}>
          <div className="lg:static" onMouseEnter={() => setMenu(true)} onMouseLeave={() => setMenu(false)}>
            <button
              className={`font-heading text-base font-medium ${menu ? "font-bold text-zy-brand" : "text-white"}`}
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              Solutions
            </button>
            {menu && (
              <div className="pt-4 lg:absolute lg:inset-x-0 lg:top-14 lg:mx-auto lg:max-w-[1200px]">
                <div className="relative grid gap-5 rounded-[10px] bg-white p-6 shadow-zy-menu lg:grid-cols-3 lg:rounded-2xl">
                  <span className="absolute -top-1.5 left-24 hidden h-3.5 w-3.5 rotate-45 rounded-[3px] bg-white lg:block" />
                  {SOLUTIONS.map((col) => (
                    <div key={col.group}>
                      <span className="text-xs font-semibold uppercase text-zy-muted">{col.group}</span>
                      <ul className="mt-4">
                        {col.items.map((it) => (
                          <li key={it.title}>
                            <Link href={it.href} className="group mb-2 flex max-w-[350px] gap-4 rounded-[10px] p-2.5 hover:bg-zy-paper-2">
                              <span className="mt-0.5 h-6 w-6 shrink-0 rounded-md bg-zy-muted/40 transition group-hover:bg-zy-brand" />
                              <span>
                                <span className="block font-heading text-sm font-medium text-zy-ink group-hover:text-zy-brand">{it.title}</span>
                                <span className="hidden text-xs text-zy-muted lg:block">{it.desc}</span>
                              </span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          {NAV.map((n) => (
            <a key={n.label} href={n.href} className="font-heading text-base font-medium text-white transition-all duration-500 hover:text-zy-brand">{n.label}</a>
          ))}
          <div className="flex flex-col gap-4 lg:ml-auto lg:flex-row lg:items-center lg:gap-5">
            <Button href="/orders" variant="outline">Track order</Button>
            <Button href="/orders">Open dashboard</Button>
          </div>
        </nav>
      </div>
    </header>
  );
}
