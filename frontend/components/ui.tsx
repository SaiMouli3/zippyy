import Link from "next/link";
import { ReactNode } from "react";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b bg-white">
        <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3 text-sm">
          <Link href="/" className="text-lg font-bold text-indigo-600">Zippy</Link>
          <Link href="/orders" className="hover:text-indigo-600">Orders</Link>
          <Link href="/mock" className="hover:text-indigo-600">Mock carrier control</Link>
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}

const COLORS: Record<string, string> = {
  DELIVERED: "bg-green-100 text-green-800", RTO: "bg-red-100 text-red-800", DELIVERY_FAILED: "bg-red-100 text-red-800",
  OUT_FOR_DELIVERY: "bg-amber-100 text-amber-800", IN_TRANSIT: "bg-blue-100 text-blue-800",
};
export function Badge({ status }: { status: string }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${COLORS[status] ?? "bg-slate-200 text-slate-700"}`}>{status}</span>;
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="mb-6 rounded-lg border bg-white p-4 shadow-sm">
      {title && <h2 className="mb-3 font-semibold">{title}</h2>}
      {children}
    </section>
  );
}

export function Btn(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={`rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 ${props.className ?? ""}`} />;
}

export function ErrorMsg({ error }: { error: string | null }) {
  return error ? <p className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">{error}</p> : null;
}

export function eta(lo: number | null, hi: number | null) {
  if (lo == null) return "n/a";
  return lo === hi ? `${lo} day${lo === 1 ? "" : "s"}` : `${lo}-${hi} days`;
}
