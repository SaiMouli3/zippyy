"use client";

import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { FormEvent, useState } from "react";

import { api, ApiError } from "@/lib/platform/api";

function safeNext(raw: string | null): string {
  // Only same-origin paths: never redirect to another host after sign-in.
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/overview";
  return raw;
}

export function LoginForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", { method: "POST", body: { email: email.trim(), password } });
      window.location.assign(safeNext(params.get("next")));
    } catch (err) {
      const ae = err as ApiError;
      setError(ae.status === 429 ? "Too many attempts. Wait a minute and try again." : ae.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
      <label className="block">
        <span className="text-[12px] font-medium text-fg-strong">Work email</span>
        <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)}
          className="mt-1 h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-[14px] text-fg-strong focus:border-fg-subtle focus:outline-none" />
      </label>
      <label className="block">
        <span className="text-[12px] font-medium text-fg-strong">Password</span>
        <span className="relative mt-1 block">
          <input type={show ? "text" : "password"} autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-10 w-full rounded-md border border-line-strong bg-surface pl-3 pr-10 text-[14px] text-fg-strong focus:border-fg-subtle focus:outline-none" />
          <button type="button" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1.5 text-fg-muted hover:bg-zy-paper-2">
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </span>
      </label>
      {error && <p role="alert" className="rounded-md border border-[#F6C9C4] bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
      <button type="submit" disabled={busy || !email || !password}
        className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-zy-brand text-[14px] font-semibold text-white transition-colors hover:bg-zy-brand-hover disabled:opacity-60">
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />} {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
