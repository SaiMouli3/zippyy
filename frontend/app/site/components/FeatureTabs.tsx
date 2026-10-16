"use client";

import { useState } from "react";
import { MockPanel } from "./MockPanel";

export type Tab = { title: string; body: string; panel: { title: string; rows: [string, string][]; src?: string } };

// Signature zippyy.ai pattern: vertical tab rail + floating visual that swaps with the tab.
// side="left": dark section, rail on the left. side="right": light, mirrored, right-aligned.
export function FeatureTabs({ heading, tabs, side = "left" }: { heading: string; tabs: Tab[]; side?: "left" | "right" }) {
  const [active, setActive] = useState(0);
  const dark = side === "left";
  const panel = tabs[active].panel;

  const text = (
    <div className={`w-full lg:w-[45%] ${dark ? "" : "lg:text-right"}`}>
      <h2 className={`mb-8 font-heading text-[26px] font-bold leading-[1.5] md:text-4xl lg:text-5xl lg:leading-[1.3] ${dark ? "text-white" : "text-zy-ink"}`}>{heading}</h2>
      <ul role="tablist">
        {tabs.map((t, i) => {
          const on = i === active;
          const rail = dark
            ? `border-l-2 ${on ? "border-zy-brand" : "border-zy-paper hover:border-zy-brand"}`
            : `border-r-2 ${on ? "border-zy-brand" : "border-zy-ink-3 hover:border-zy-brand"}`;
          return (
            <li key={t.title} className={`mb-4 px-5 py-4 transition-all duration-300 ${rail}`}>
              <button role="tab" aria-selected={on} onClick={() => setActive(i)} onMouseEnter={() => setActive(i)} className={`w-full ${dark ? "text-left" : "text-left lg:text-right"}`}>
                <h3 className={`font-heading transition-all duration-300 ${on ? "text-[22px] font-bold text-zy-brand" : `text-xl font-medium lg:text-2xl ${dark ? "text-white" : "text-zy-ink-3"}`}`}>{t.title}</h3>
              </button>
              {on && <p className={`mt-2 animate-fade-in text-[15px] leading-normal ${dark ? "text-white" : "text-zy-ink-3"}`}>{t.body}</p>}
            </li>
          );
        })}
      </ul>
    </div>
  );
  const visual = (
    <div className="w-full lg:w-1/2">
      <MockPanel key={active} title={panel.title} rows={panel.rows} src={panel.src} tone={dark ? "dark" : "light"} />
    </div>
  );

  return (
    <section id={dark ? "platform" : undefined} className={dark ? "bg-zy-ink" : "bg-zy-paper"}>
      <div className={`mx-auto flex max-w-zy flex-col items-center gap-12 px-5 py-16 lg:flex-row lg:justify-between lg:px-[60px] lg:py-[100px] ${dark ? "" : "lg:flex-row-reverse"}`}>
        {text}
        {visual}
      </div>
    </section>
  );
}
