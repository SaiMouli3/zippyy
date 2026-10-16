import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "./form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-zy-ink p-10 text-white lg:flex">
        <img src="/brand/logo-on-dark.svg" alt="Zippyy" className="h-8 w-auto self-start" />
        <div className="relative z-10 max-w-md">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/15 px-3 py-1 text-[12px] text-white/70">
            <span className="h-1.5 w-1.5 rounded-full bg-zy-brand" aria-hidden /> Delivery &amp; NDR autonomy
          </p>
          <h1 className="font-heading text-[34px] font-black leading-[1.15] tracking-[-0.02em] text-white">
            Every failed delivery, <span className="text-zy-brand">recovered in the customer&apos;s language.</span>
          </h1>
          <p className="mt-4 text-[14px] leading-6 text-white/65">
            Zippyy agents confirm availability before dispatch, reach customers on WhatsApp and voice after a failed attempt,
            and only ask the carrier for what your policy allows.
          </p>
        </div>
        <ul className="relative z-10 grid max-w-md grid-cols-3 gap-4 border-t border-white/10 pt-6 text-[12px] text-white/55">
          <li><span className="block font-heading text-[13px] font-bold text-white">WhatsApp + voice</span>One case, one timeline</li>
          <li><span className="block font-heading text-[13px] font-bold text-white">5 languages</span>Switches mid-call</li>
          <li><span className="block font-heading text-[13px] font-bold text-white">Policy-gated</span>Every action audited</li>
        </ul>
        <div aria-hidden className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-zy-brand/20 blur-[120px]" />
      </section>
      <section className="flex items-center justify-center bg-canvas px-5 py-12">
        <div className="w-full max-w-[380px]">
          <img src="/brand/logo.svg" alt="Zippyy" className="mb-8 h-7 w-auto lg:hidden" />
          <h2 className="font-heading text-[22px] font-bold text-fg-strong">Sign in to your workspace</h2>
          <p className="mt-1 text-[13px] text-fg-muted">Use the email your administrator invited.</p>
          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
          <p className="mt-8 text-2xs leading-4 text-fg-subtle">
            Sessions expire after inactivity. Five failed attempts lock the account for a short period.
          </p>
        </div>
      </section>
    </div>
  );
}
