"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, BarChart3, Bell, Bot, Building2, Check, ChevronDown, ChevronsLeft, ChevronsRight, ClipboardList, Cog,
  FileClock, Headphones, LayoutDashboard, LogOut, Menu, MessagesSquare, PackageCheck, Plug, Search,
  ShieldCheck, SlidersHorizontal, Siren, Truck, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, FormEvent, ReactNode, useContext, useEffect, useRef, useState } from "react";

import { useLive, useSession } from "@/components/platform/providers";
import { cx, Tooltip } from "@/components/platform/ui";
import { api } from "@/lib/platform/api";
import { relative } from "@/lib/platform/format";
import { useLocalStorage, useNow, useOnClickOutside } from "@/lib/platform/hooks";

// ------------------------------------------------------------------ navigation
type NavItem = { href: string; label: string; icon: typeof Activity; perm: string; group: string };
export const NAV: NavItem[] = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard, perm: "dashboard.read", group: "Operate" },
  { href: "/ndr", label: "NDR cases", icon: Siren, perm: "ndr.read", group: "Operate" },
  { href: "/escalations", label: "Escalations", icon: ClipboardList, perm: "escalations.read", group: "Operate" },
  { href: "/shipments", label: "Shipments", icon: Truck, perm: "shipments.read", group: "Operate" },
  { href: "/pre-delivery", label: "Pre-delivery", icon: PackageCheck, perm: "ndr.read", group: "Operate" },
  { href: "/conversations", label: "Conversations", icon: MessagesSquare, perm: "conversations.read", group: "Customers" },
  { href: "/calls", label: "Voice calls", icon: Headphones, perm: "conversations.read", group: "Customers" },
  { href: "/agent-activity", label: "Agent activity", icon: Bot, perm: "agent_runs.read", group: "Automation" },
  { href: "/analytics", label: "Analytics", icon: BarChart3, perm: "analytics.read", group: "Automation" },
  { href: "/agent-config", label: "Agent config", icon: SlidersHorizontal, perm: "agent_config.read", group: "Configure" },
  { href: "/policies", label: "Contact policy", icon: ShieldCheck, perm: "policies.read", group: "Configure" },
  { href: "/integrations", label: "Integrations", icon: Plug, perm: "integrations.read", group: "Configure" },
  { href: "/audit", label: "Audit log", icon: FileClock, perm: "audit.read", group: "Configure" },
  { href: "/settings", label: "Settings", icon: Cog, perm: "settings.read", group: "Configure" },
];

// ------------------------------------------------------------------ global time range
export const RANGES = [
  { value: "24h", label: "Last 24 hours" }, { value: "7d", label: "Last 7 days" }, { value: "14d", label: "Last 14 days" },
  { value: "30d", label: "Last 30 days" }, { value: "90d", label: "Last 90 days" },
];
const RangeCtx = createContext<{ range: string; setRange: (r: string) => void }>({ range: "7d", setRange: () => undefined });
export const useRange = () => useContext(RangeCtx);

// ------------------------------------------------------------------ shell
export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useLocalStorage("zpy.sidebar.collapsed", false);
  const [range, setRange] = useLocalStorage("zpy.range", "7d");
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const { me } = useSession();
  useEffect(() => setMobileOpen(false), [pathname]);

  return (
    <RangeCtx.Provider value={{ range, setRange }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[200] focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <div className="flex min-h-screen">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
        <div className={cx("flex min-w-0 flex-1 flex-col transition-[padding] duration-200", collapsed ? "lg:pl-[64px]" : "lg:pl-[232px]")}>
          <TopBar onMenu={() => setMobileOpen(true)} />
          {me.isDemo && (
            <div className="border-b border-[#F6DDB5] bg-warn-soft px-4 py-1.5 text-[12px] text-warn sm:px-6" role="note">
              <strong className="font-semibold">Demo workspace.</strong> Customers, messages, calls and carrier responses here are
              simulated with fictional data. Nobody is contacted and no carrier receives a request.
            </div>
          )}
          <main id="main" className="mx-auto w-full max-w-[1480px] flex-1 px-4 py-5 sm:px-6">{children}</main>
        </div>
      </div>
    </RangeCtx.Provider>
  );
}

function Sidebar({ collapsed, onToggle, mobileOpen, onClose }: { collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { can } = useSession();
  const items = NAV.filter((n) => can(n.perm));
  const groups = Array.from(new Set(items.map((i) => i.group)));
  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-40 bg-zy-ink/50 lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        aria-label="Primary"
        className={cx(
          "fixed inset-y-0 left-0 z-50 flex flex-col bg-zy-ink text-white transition-[width,transform] duration-200",
          collapsed ? "lg:w-[64px]" : "lg:w-[232px]", "w-[248px]",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div className={cx("flex h-14 shrink-0 items-center border-b border-white/[0.07]", collapsed ? "lg:justify-center lg:px-0" : "", "px-4")}>
          <Link href="/overview" className="flex items-center gap-2" aria-label="Zippyy overview">
            {collapsed
              ? <><img src="/brand/icon-32.jpg" alt="" className="hidden h-7 w-7 rounded lg:block" /><img src="/brand/logo-on-dark.svg" alt="Zippyy" className="h-6 w-auto lg:hidden" /></>
              : <img src="/brand/logo-on-dark.svg" alt="Zippyy" className="h-6 w-auto" />}
          </Link>
          <button onClick={onClose} className="ml-auto rounded p-1 text-white/60 hover:bg-white/10 lg:hidden" aria-label="Close navigation"><X className="h-4 w-4" /></button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3 scrollbar-thin">
          {groups.map((g) => (
            <div key={g} className="mb-3">
              <p className={cx("px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-white/35", collapsed && "lg:sr-only")}>{g}</p>
              <ul className="space-y-0.5">
                {items.filter((i) => i.group === g).map((item) => {
                  const active = pathname === item.href || pathname.startsWith(item.href + "/");
                  const Icon = item.icon;
                  const link = (
                    <Link href={item.href} aria-current={active ? "page" : undefined}
                      className={cx(
                        "group relative flex h-9 items-center gap-3 rounded-md px-3 text-[13px] font-medium transition-colors",
                        active ? "bg-white/[0.08] text-white" : "text-white/65 hover:bg-white/[0.05] hover:text-white",
                        collapsed && "lg:justify-center lg:px-0",
                      )}>
                      {active && <span className="absolute left-0 top-1.5 h-6 w-[3px] rounded-r bg-zy-brand" aria-hidden />}
                      <Icon className={cx("h-[17px] w-[17px] shrink-0", active ? "text-zy-brand" : "text-white/55 group-hover:text-white/80")} aria-hidden />
                      <span className={cx("truncate", collapsed && "lg:sr-only")}>{item.label}</span>
                    </Link>
                  );
                  return <li key={item.href}><SideTip label={item.label} enabled={collapsed}>{link}</SideTip></li>;
                })}
              </ul>
            </div>
          ))}
        </nav>
        <button onClick={onToggle} className="hidden h-10 shrink-0 items-center gap-2 border-t border-white/[0.07] px-5 text-[12px] text-white/50 hover:text-white lg:flex"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
        </button>
      </aside>
    </>
  );
}

function SideTip({ label, enabled, children }: { label: string; enabled: boolean; children: ReactNode }) {
  return (
    <span className="group/st relative block">
      {children}
      {enabled && <span aria-hidden className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 hidden -translate-y-1/2 whitespace-nowrap rounded bg-zy-ink-3 px-2 py-1 text-2xs text-white shadow-pop lg:group-hover/st:block">{label}</span>}
    </span>
  );
}

// ------------------------------------------------------------------ top bar
function TopBar({ onMenu }: { onMenu: () => void }) {
  const { range, setRange } = useRange();
  const pathname = usePathname();
  const rangeRelevant = pathname.startsWith("/overview") || pathname.startsWith("/analytics");
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface/95 px-3 backdrop-blur sm:gap-3 sm:px-6">
      <button onClick={onMenu} className="rounded p-1.5 text-fg hover:bg-zy-paper-2 lg:hidden" aria-label="Open navigation"><Menu className="h-5 w-5" /></button>
      <WorkspaceSwitcher />
      <GlobalSearch />
      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        {rangeRelevant && (
          <label className="hidden md:block">
            <span className="sr-only">Time range</span>
            <select value={range} onChange={(e) => setRange(e.target.value)}
              className="h-8 rounded-md border border-line-strong bg-surface pl-2 pr-7 text-[12.5px] text-fg-strong focus:outline-none">
              {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
        )}
        <LiveIndicator />
        <Notifications />
        <UserMenu />
      </div>
    </header>
  );
}

function WorkspaceSwitcher() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();
  const router = useRouter();
  useOnClickOutside(ref, () => setOpen(false));
  const current = me.memberships.find((m) => m.merchantId === me.merchantId);

  async function switchTo(id: string) {
    setBusy(id);
    setErr(null);
    try {
      await api("/auth/switch-merchant", { method: "POST", body: { merchantId: id } });
      qc.clear();
      setOpen(false);
      router.push("/overview");
      router.refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}
        className="flex h-8 max-w-[220px] items-center gap-2 rounded-md border border-line-strong px-2 text-[13px] font-medium text-fg-strong hover:bg-zy-paper">
        <Building2 className="h-3.5 w-3.5 shrink-0 text-fg-muted" aria-hidden />
        <span className="truncate">{current?.brandName ?? "Workspace"}</span>
        {current?.isDemo && <span className="rounded bg-warn-soft px-1 text-[10px] font-semibold uppercase text-warn">Demo</span>}
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-fg-muted" aria-hidden />
      </button>
      {open && (
        <div className="absolute left-0 top-10 z-50 w-72 rounded-lg border border-line bg-surface p-1 shadow-pop" role="listbox" aria-label="Workspaces">
          <p className="px-2.5 py-1.5 text-2xs font-medium uppercase tracking-wide text-fg-subtle">Workspaces</p>
          {me.memberships.map((m) => (
            <button key={m.merchantId} role="option" aria-selected={m.merchantId === me.merchantId} disabled={!!busy}
              onClick={() => (m.merchantId === me.merchantId ? setOpen(false) : switchTo(m.merchantId))}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] hover:bg-zy-paper">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-fg-strong">{m.brandName}</span>
                <span className="block text-2xs text-fg-muted">{m.code} · {m.role.replace("_", " ")}{m.isDemo ? " · demo data" : ""}</span>
              </span>
              {m.merchantId === me.merchantId && <Check className="h-4 w-4 text-zy-brand" aria-label="Current" />}
              {busy === m.merchantId && <span className="text-2xs text-fg-muted">Switching…</span>}
            </button>
          ))}
          {err && <p className="px-2.5 py-1.5 text-2xs text-danger">{err}</p>}
        </div>
      )}
    </div>
  );
}

function GlobalSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "/" && !(e.target as HTMLElement).closest("input, textarea, select, [contenteditable]")) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  function submit(e: FormEvent) {
    e.preventDefault();
    const term = q.trim();
    if (!term) return;
    router.push(`/ndr?q=${encodeURIComponent(term)}`);
  }
  return (
    <form onSubmit={submit} role="search" className="hidden min-w-0 max-w-md flex-1 sm:block">
      <label className="relative block">
        <span className="sr-only">Search NDR cases by case ID, order, AWB, customer or phone</span>
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search case, order, AWB, customer or phone"
          className="h-8 w-full rounded-md border border-line-strong bg-zy-paper pl-8 pr-8 text-[13px] placeholder:text-fg-subtle focus:border-fg-subtle focus:bg-surface focus:outline-none" />
        <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line px-1 font-mono text-[10px] text-fg-subtle">/</kbd>
      </label>
    </form>
  );
}

function LiveIndicator() {
  const { state, lastBeat } = useLive();
  const now = useNow(5000);
  const cfg = {
    live: { dot: "bg-ok", label: "Live", text: "text-ok" },
    connecting: { dot: "bg-line-strong", label: "Connecting", text: "text-fg-muted" },
    reconnecting: { dot: "bg-warn", label: "Reconnecting", text: "text-warn" },
    offline: { dot: "bg-danger", label: "Offline", text: "text-danger" },
  }[state];
  const tip = state === "live"
    ? `Receiving updates as they happen. Last signal ${lastBeat ? relative(new Date(lastBeat).toISOString(), now) : "—"}.`
    : state === "connecting" ? "Opening the live update stream."
      : `Live updates are interrupted. Data refreshes every 30 seconds instead${lastBeat ? `; last live signal ${relative(new Date(lastBeat).toISOString(), now)}` : ""}.`;
  return (
    <Tooltip text={tip} side="bottom">
      <span className={cx("inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium", cfg.text)} role="status" aria-live="polite">
        <span className={cx("h-2 w-2 rounded-full", cfg.dot, state === "live" && "animate-pulse2")} aria-hidden />
        <span className="hidden sm:inline">{cfg.label}</span>
      </span>
    </Tooltip>
  );
}

interface QueueSummary { queues: Record<string, { total: number }>; generatedAt: string }
const ALERT_QUEUES: { key: string; label: string; href: string }[] = [
  { key: "urgent", label: "Urgent or past SLA", href: "/ndr?queue=urgent" },
  { key: "escalated", label: "Open escalations", href: "/escalations" },
  { key: "carrier_unknown", label: "Carrier outcome unknown", href: "/ndr?queue=carrier_unknown" },
  { key: "near_deadline", label: "SLA due within 4 hours", href: "/ndr?queue=near_deadline" },
  { key: "callback", label: "Callback requested", href: "/ndr?queue=callback" },
];

function Notifications() {
  const { can } = useSession();
  const { pollMs } = useLive();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => setOpen(false));
  const q = useQuery({
    queryKey: ["queues", "summary"], queryFn: () => api<QueueSummary>("/dashboard/queues"),
    enabled: can("dashboard.read"), refetchInterval: pollMs === false ? 60000 : pollMs,
  });
  if (!can("dashboard.read")) return null;
  const counts = ALERT_QUEUES.map((a) => ({ ...a, n: q.data?.queues[a.key]?.total ?? 0 }));
  const attention = (q.data?.queues.urgent?.total ?? 0) + (q.data?.queues.escalated?.total ?? 0);
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} className="relative rounded-md p-2 text-fg hover:bg-zy-paper-2" aria-expanded={open}
        aria-label={`Attention queues${attention ? `, ${attention} items need attention` : ""}`}>
        <Bell className="h-4 w-4" />
        {attention > 0 && <span className="num absolute -right-0.5 -top-0.5 min-w-[16px] rounded-full bg-zy-brand px-1 text-center text-[10px] font-semibold leading-4 text-white">{attention > 99 ? "99+" : attention}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 rounded-lg border border-line bg-surface shadow-pop">
          <div className="border-b border-line px-3 py-2">
            <p className="font-heading text-[13px] font-bold text-fg-strong">Needs attention</p>
            <p className="text-2xs text-fg-muted">Current counts across your workspace</p>
          </div>
          {q.isError ? <p className="px-3 py-3 text-[12.5px] text-danger">Couldn&apos;t load queue counts.</p> : (
            <ul className="p-1">
              {counts.map((c) => (
                <li key={c.key}>
                  <Link href={c.href} onClick={() => setOpen(false)} className="flex items-center justify-between rounded-md px-2.5 py-2 text-[13px] hover:bg-zy-paper">
                    <span className="text-fg">{c.label}</span>
                    <span className={cx("num rounded px-1.5 text-[12px] font-semibold", c.n ? "bg-zy-brand-soft text-zy-brand" : "text-fg-subtle")}>{q.isLoading ? "…" : c.n}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => setOpen(false));
  const initials = me.user.name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  async function signOut() {
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      window.location.assign("/login");
    }
  }
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Account menu"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-zy-ink text-[11px] font-semibold text-white hover:bg-zy-ink-3">
        {initials}
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-50 w-64 rounded-lg border border-line bg-surface p-1 shadow-pop">
          <div className="px-3 py-2">
            <p className="truncate text-[13px] font-medium text-fg-strong">{me.user.name}</p>
            <p className="truncate text-2xs text-fg-muted">{me.user.email}</p>
            <p className="mt-1 inline-block rounded bg-zy-paper-2 px-1.5 text-2xs capitalize text-fg">{me.role.replace("_", " ")}</p>
          </div>
          <div className="my-1 border-t border-line" />
          <Link href="/settings" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-md px-3 py-2 text-[13px] text-fg hover:bg-zy-paper">
            <Cog className="h-3.5 w-3.5" aria-hidden /> Workspace settings
          </Link>
          <button onClick={signOut} disabled={busy} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-[13px] text-fg hover:bg-zy-paper">
            <LogOut className="h-3.5 w-3.5" aria-hidden /> {busy ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}

